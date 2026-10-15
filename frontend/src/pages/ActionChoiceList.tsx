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
    key: "image.describe",
    title: "Inspect images",
    detail:
      "Attach up to four images. AI Station reads their contents locally and may load an installed vision model on your GPUs.",
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
    key: "audio.transcribe",
    title: "Transcribe recording",
    detail: "Turn a WAV recording into timestamped text locally on CPU.",
  },
  {
    key: "audio.speech",
    title: "Speech · read this message in Polish",
    detail: "Queues local Chatterbox speech. Not transcription or music.",
  },
  {
    key: "image.generate_video",
    title: "Image → video",
    detail: "Generate an image, then animate it locally. Keeps both results.",
  },
  {
    key: "video.generate",
    title: "Generate video",
    detail:
      "Create a silent local scene. Optionally attach one first-frame image.",
  },
  {
    key: "avatar.animate",
    title: "Animate portrait with speech",
    detail: "Queues local EchoMimic. Needs a portrait and WAV.",
  },
  {
    key: "github.inspect",
    title: "Read GitHub repository",
    detail:
      "Read open issues and PRs using a connected repository. No changes or external AI sharing.",
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
    key: "project.create",
    title: "Create project",
    detail:
      "Enter a project name. AI Station creates its Git repository and Python environment, ready for coding.",
  },
  {
    key: "project.create_code",
    title: "Create project & build",
    detail:
      "Name your project and describe the first task. Setup and isolated coding run automatically.",
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
  allowWork = true,
}: {
  value: string;
  onChange: (action: string) => void;
  disabled?: boolean;
  allowWork?: boolean;
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
        {ACTIONS.filter(
          (item) =>
            allowWork ||
            ["auto", "chat"].includes(item.key) ||
            item.key.startsWith("image.") ||
            [
              "audio.speech",
              "audio.transcribe",
              "avatar.animate",
              "video.generate",
              "github.inspect",
            ].includes(item.key),
        ).map((item) => (
          <option key={item.key} value={item.key}>
            {item.title}
          </option>
        ))}
      </select>
      <p className="muted">{selected.detail}</p>
    </div>
  );
}
