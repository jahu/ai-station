import { useId } from "react";

const ACTIONS = [
  {
    key: "auto",
    title: "Auto — let AI Station route this task",
    detail: "Describe your task. AI Station will choose the next step.",
  },
  {
    key: "chat",
    title: "Conversation",
    detail: "Stay in chat without routing to a station action.",
  },
  {
    key: "image.generate",
    title: "Generate image",
    detail: "Create an image from your description.",
  },
  {
    key: "image.edit",
    title: "Edit image",
    detail: "Modify one image while preserving the original.",
  },
  {
    key: "image.recompose",
    title: "Recompose references",
    detail: "Combine references into a new composition.",
  },
  {
    key: "image.upscale",
    title: "Upscale image",
    detail: "Enlarge one image to four times its dimensions.",
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
    key: "system.inspect",
    title: "Inspect workstation",
    detail: "Read current GPU, CPU, RAM, storage and station activity.",
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
    detail: "Review the diff before committing to the task branch.",
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
  const id = useId();
  const selected = ACTIONS.find((item) => item.key === value) ?? ACTIONS[0];
  return (
    <div className="assistant-action-select">
      <label htmlFor={id}>Action</label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.preventDefault();
        }}
      >
        {ACTIONS.map((item) => (
          <option key={item.key} value={item.key}>
            {item.title}
          </option>
        ))}
      </select>
      <p className="muted">{selected.detail}</p>
    </div>
  );
}
