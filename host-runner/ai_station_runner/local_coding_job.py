"""Local coding inference through the private Runner bridge."""

import json
import os
import signal
import sys
import time
from uuid import UUID

import httpx

from ai_station_runner import public_http
from ai_station_runner.coding_files import proposal_prompt
from ai_station_runner.coding_job import execute_proposal
from ai_station_runner.config import get_settings
from ai_station_runner.local_coding_runs import directory, load_request


def collect_proposal(body, selected, references=None):
    message = proposal_prompt(
        prompt=body.prompt, selected=selected, guidance=body.guidance, references=references
    )
    return collect_completion(body, message, max_tokens=8192)


def collect_completion(body, message, *, max_tokens=2048):
    managed = body.model.startswith("llamacpp:")
    if managed:
        instance_id = str(UUID(body.endpoint.removeprefix("llamacpp:")))
        target = f"http://runner/v1/llama/{instance_id}"
        headers, model = {}, instance_id
    else:
        target = "http://runner/v1/llm"
        headers, model = {"X-AI-Station-Endpoint": body.endpoint}, body.model
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": message
                + "\nReturn only the requested JSON, without reasoning or Markdown.\n/no_think",
            }
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "stream": True,
    }
    content, buffer, size = [], b"", 0
    done, finished = False, False
    started = time.monotonic()
    last_progress = started
    characters = 0
    transport = httpx.HTTPTransport(uds=get_settings().socket_path())
    with httpx.Client(
        transport=transport, timeout=httpx.Timeout(300, connect=10), trust_env=False, follow_redirects=False
    ) as client:
        with client.stream("POST", target + "/chat/completions", headers=headers, json=payload) as response:
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", ""):
                raise ValueError("Local coding requires a streaming response")
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 2 * 1024 * 1024 or time.monotonic() - started > 900:
                    raise ValueError("Local coding exceeded its response limit")
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        done = True
                        break
                    event = json.loads(data)
                    if not isinstance(event, dict) or event.get("error"):
                        raise ValueError("Local model returned an inference error")
                    choices = event.get("choices", [])
                    if not isinstance(choices, list) or len(choices) > 1:
                        raise ValueError("Local coding requires one completion")
                    for choice in choices:
                        delta = choice.get("delta", {})
                        if delta.get("tool_calls") or delta.get("function_call"):
                            raise ValueError("Local coding does not allow model tool calls")
                        reason = choice.get("finish_reason")
                        if reason is not None:
                            if reason == "length":
                                raise ValueError(
                                    "Local coding output was truncated by the model's output/context "
                                    f"limit (requested output budget: {max_tokens} tokens). "
                                    "No proposal was applied. Increase model context or split the task."
                                )
                            if reason != "stop":
                                raise ValueError(f"Local coding completion rejected: finish_reason={reason}")
                            finished = True
                        text = delta.get("content")
                        if text is not None:
                            if not isinstance(text, str):
                                raise ValueError("Local coding requires text content")
                            content.append(text)
                            characters += len(text)
                            if time.monotonic() - last_progress >= 10:
                                print(
                                    json.dumps({"event": "coding.generating", "characters": characters}),
                                    flush=True,
                                )
                                last_progress = time.monotonic()
                if done:
                    break
    if not done or not finished:
        raise ValueError("Local coding response ended without confirmed completion")
    return "".join(content), {"name": "local-openai-compatible", "model": body.model}


def execute(run_id):
    if os.getpid() != os.getpgrp():
        raise ValueError("Local coding requires an owned process group")
    # Bound a silent or stalled stream, including time spent waiting for headers.
    signal.alarm(1200)
    body = load_request(run_id)
    discover = None
    references = []
    if body.explore:
        from ai_station_runner.coding_exploration import explore

        def discover(workspace):
            selected, observations = explore(
                workspace,
                body.prompt,
                body.guidance,
                lambda message: collect_completion(body, message)[0],
                web=True,
            )
            references[:] = public_http.proposal_references(observations)
            return selected, observations

    execute_proposal(
        run_id,
        body,
        directory(run_id),
        lambda selected: collect_proposal(body, selected, references),
        location="local",
        discover=discover,
    )
    signal.alarm(0)


if __name__ == "__main__":
    try:
        execute(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
