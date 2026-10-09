import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

const ACTIONS = [
  {
    key: "auto",
    title: "Auto — let AI Station route this task",
    detail: "Uses the existing capability planner. Permissions stay unchanged.",
  },
  {
    key: "chat",
    title: "Conversation",
    detail: "Stay in chat without routing to a station action.",
  },
  {
    key: "image.generate",
    title: "Generate image",
    detail: "Queues the existing photo Generate Run.",
  },
  {
    key: "image.edit",
    title: "Edit image",
    detail: "Queues the existing photo Edit Run.",
  },
  {
    key: "image.recompose",
    title: "Recompose references",
    detail: "Queues the existing photo Recompose Run.",
  },
  {
    key: "image.upscale",
    title: "Upscale image",
    detail: "Queues the existing 4× Upscale Run.",
  },
  {
    key: "audio.speech",
    title: "Speech · read this message in Polish",
    detail: "Queues local Chatterbox speech. Not transcription or music.",
  },
  {
    key: "avatar.animate",
    title: "Animate portrait with speech",
    detail: "Queues local EchoMimic. Needs a portrait and WAV.",
  },
  {
    key: "agent.create",
    title: "Create agent",
    detail: "Saves a disabled definition. Activation stays explicit.",
  },
  {
    key: "coding.local",
    title: "Coding with Local AI",
    detail: "Uses this conversation's local model in an owned worktree.",
  },
  {
    key: "coding.cursor",
    title: "Coding with Cursor",
    detail: "Requires explicit external-AI consent.",
  },
  {
    key: "coding.codex",
    title: "Coding with Codex",
    detail: "Requires explicit external-AI consent.",
  },
  {
    key: "coding.commit",
    title: "Commit reviewed changes",
    detail: "A model plan cannot grant Git write.",
  },
  {
    key: "coding.publish",
    title: "Publish reviewed commit to GitHub",
    detail: "Requires the existing exact-scope approval.",
  },
  {
    key: "runtime.load",
    title: "Load local GGUF",
    detail: "Starts only an owned llama.cpp instance.",
  },
  {
    key: "runtime.stop",
    title: "Unload owned llama.cpp",
    detail: "External Ollama or ComfyUI processes are not stopped.",
  },
] as const;

export type AssistantAction = (typeof ACTIONS)[number]["key"];

export function ActionChoiceList({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (action: string) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [...ACTIONS];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.key,
    { initialKey: value },
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, summary, select")) return;
    if (event.key === " " && target.closest("input")) return;
    const item = items[index];
    if (!item || disabled) return;
    event.preventDefault();
    onChange(item.key);
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose an assistant action while the list is focused. Space
        or Enter selects it. Enter does not send. There is no inspectable
        action-selection Run.
      </p>
      <div
        ref={listRef}
        className="assistant-action-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Action ${item.key}`}
              {...itemProps(i, item.key)}
            >
              <label className="agent-tool">
                <input
                  type="radio"
                  name={labelId}
                  checked={value === item.key}
                  disabled={disabled}
                  tabIndex={current ? 0 : -1}
                  onChange={() => onChange(item.key)}
                />
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.detail}</small>
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}
