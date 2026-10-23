import { useState } from "react";
import {
  Image,
  Music2,
  AudioLines,
  Film,
  UserRound,
  Settings2,
  Plus,
  X,
} from "lucide-react";
import MediaInput from "../components/media/MediaInput";
import { Button } from "../components/ui/button";
import { useHardware } from "../api";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import MusicScope from "./MusicScope";
import AgentVideoScope from "./AgentVideoScope";
import AgentAvatarScope from "./AgentAvatarScope";
import {
  agentMediaIssue,
  newAgentMedia,
  type AgentMediaScope,
  type ImageMediaRequest,
} from "./agent-media";

export default function AgentMediaScopeEditor({
  value,
  goal,
  disabled,
  onChange,
  onBusy,
  readiness,
}: {
  value?: AgentMediaScope | null;
  goal: string;
  disabled: boolean;
  onChange: (scope: AgentMediaScope) => void;
  onBusy: (busy: boolean) => void;
  readiness?: Partial<
    Record<AgentMediaScope["kind"], { ready: boolean; reason?: string | null }>
  >;
}) {
  const [uploading, setUploading] = useState(false);
  const hardware = useHardware();
  const scope = value ?? newAgentMedia("image", goal);
  const image = scope.kind === "image" ? scope.request : null;
  const caption =
    scope.kind === "avatar"
      ? (scope.request.speech_text ?? scope.request.prompt)
      : scope.kind === "video"
        ? scope.request.prompt
        : scope.kind === "music"
          ? scope.request.caption
          : scope.kind === "speech"
            ? scope.request.text
            : image?.mode === "img2img"
              ? (image.edit_prompt ?? "")
              : (image?.prompt ?? "");
  const issue = agentMediaIssue(scope);
  const OutputIcon =
    scope.kind === "avatar"
      ? UserRound
      : scope.kind === "video"
        ? Film
        : scope.kind === "speech"
          ? AudioLines
          : scope.kind === "music"
            ? Music2
            : Image;
  function updateImage(patch: Partial<ImageMediaRequest>) {
    if (scope.kind === "image")
      onChange({ ...scope, request: { ...scope.request, ...patch } });
  }
  return (
    <section className="agent-media-scope" aria-label="Media output settings">
      <div className="media-composer-heading">
        <OutputIcon size={20} />
        <h3>Your agent's output</h3>
        <span>LOCAL</span>
      </div>
      <p className="muted">
        The result appears in this workspace and Library. Review the creative
        direction and output settings before enabling.
      </p>
      {readiness?.[scope.kind]?.ready === false && (
        <p className="error" role="status">
          {readiness[scope.kind]?.reason ||
            "The selected local media engine is unavailable."}{" "}
          You can save this draft and enable it after setup.
        </p>
      )}
      <fieldset disabled={disabled || uploading}>
        <div className="mode-tabs" aria-label="Media output type">
          {(["image", "music", "speech", "video", "avatar"] as const).map(
            (kind) => (
              <button
                type="button"
                key={kind}
                aria-pressed={scope.kind === kind}
                className={scope.kind === kind ? "active" : ""}
                onClick={() =>
                  onChange({
                    ...newAgentMedia(kind, goal),
                    description_source: scope.description_source,
                  })
                }
              >
                {kind === "avatar" ? (
                  <UserRound size={16} />
                ) : kind === "video" ? (
                  <Film size={16} />
                ) : kind === "image" ? (
                  <Image size={16} />
                ) : kind === "speech" ? (
                  <AudioLines size={16} />
                ) : (
                  <Music2 size={16} />
                )}
                {kind === "avatar"
                  ? "Avatar"
                  : kind === "video"
                    ? "Video"
                    : kind === "image"
                      ? "Image"
                      : kind === "speech"
                        ? "Speech"
                        : "Music"}
              </button>
            ),
          )}
        </div>
        {scope.kind === "avatar" && (
          <label>
            Speech source
            <select
              aria-label="Agent avatar speech source"
              value={
                scope.request.speech_text !== null ? "generated" : "recording"
              }
              onChange={(event) =>
                onChange({
                  ...scope,
                  request: {
                    ...scope.request,
                    speech_text:
                      event.target.value === "generated"
                        ? goal.slice(0, 1000)
                        : null,
                  },
                })
              }
            >
              <option value="generated">Write new speech in Polish</option>
              <option value="recording">
                Use the complete saved recording
              </option>
            </select>
          </label>
        )}
        {image && (
          <label>
            Image operation
            <select
              aria-label="Agent image operation"
              value={image.mode}
              onChange={(event) => {
                const mode = event.target.value as ImageMediaRequest["mode"];
                onChange({
                  kind: "image",
                  description_source:
                    mode === "upscale" ? "fixed" : scope.description_source,
                  request: {
                    mode,
                    backend: "qwen",
                    prompt: caption || goal,
                    edit_prompt: caption || goal,
                    input_artifact_ids:
                      mode === "t2i"
                        ? []
                        : image.input_artifact_ids?.slice(
                              0,
                              mode === "recompose" ? 8 : 1,
                            ).length
                          ? image.input_artifact_ids.slice(
                              0,
                              mode === "recompose" ? 8 : 1,
                            )
                          : [""],
                    gpu: image.gpu ?? "auto",
                  },
                });
              }}
            >
              <option value="t2i">Generate</option>
              <option value="img2img">Edit an image</option>
              <option value="recompose">Recompose from references</option>
              <option value="upscale">Upscale 4×</option>
            </select>
          </label>
        )}
        {image?.mode !== "upscale" && (
          <>
            <label>
              Description policy
              <select
                aria-label="Media description policy"
                value={scope.description_source}
                onChange={(event) =>
                  onChange({
                    ...scope,
                    description_source: event.target.value as "fixed" | "goal",
                    ...(scope.kind === "music" && event.target.value === "fixed"
                      ? { lyrics_source: "fixed" as const }
                      : {}),
                  })
                }
              >
                <option value="goal">
                  Let Local AI prepare it from the goal and sources
                </option>
                <option value="fixed">
                  Use this exact description every time
                </option>
              </select>
            </label>
            <p className="muted">
              {scope.description_source === "goal"
                ? "Your selected local model writes the description. The references and settings below stay fixed."
                : "Runs directly with the media engine. No language model is needed."}
            </p>
            <label>
              {scope.kind === "speech" ||
              (scope.kind === "avatar" && scope.request.speech_text !== null)
                ? "Spoken text or writing instructions"
                : scope.kind === "avatar"
                  ? "Motion direction"
                  : "Creative direction"}
              <textarea
                aria-label="Media creative direction"
                rows={4}
                required
                maxLength={
                  scope.kind === "avatar"
                    ? scope.request.speech_text !== null
                      ? 1000
                      : 2000
                    : scope.kind === "music"
                      ? 512
                      : scope.kind === "speech"
                        ? 1000
                        : scope.kind === "video"
                          ? 2000
                          : 10000
                }
                value={caption}
                onChange={(event) =>
                  scope.kind === "avatar"
                    ? onChange({
                        ...scope,
                        request: {
                          ...scope.request,
                          ...(scope.request.speech_text !== null
                            ? { speech_text: event.target.value }
                            : { prompt: event.target.value }),
                        },
                      })
                    : scope.kind === "video"
                      ? onChange({
                          ...scope,
                          request: {
                            ...scope.request,
                            prompt: event.target.value,
                          },
                        })
                      : scope.kind === "speech"
                        ? onChange({
                            ...scope,
                            request: {
                              ...scope.request,
                              text: event.target.value,
                            },
                          })
                        : scope.kind === "music"
                          ? onChange({
                              ...scope,
                              request: {
                                ...scope.request,
                                caption: event.target.value,
                              },
                            })
                          : updateImage(
                              image?.mode === "img2img"
                                ? { edit_prompt: event.target.value }
                                : { prompt: event.target.value },
                            )
                }
                placeholder={
                  scope.kind === "speech"
                    ? "Write the exact Polish text, or describe the short briefing your agent should write…"
                    : "Describe the mood, subject and style your agent should create…"
                }
              />
            </label>
          </>
        )}
        {scope.kind === "avatar" && (
          <AgentAvatarScope
            value={scope.request}
            disabled={disabled || uploading}
            onChange={(request) => onChange({ ...scope, request })}
            onBusy={(busy) => {
              setUploading(busy);
              onBusy(busy);
            }}
          />
        )}
        {scope.kind === "video" && (
          <AgentVideoScope
            value={scope.request}
            onChange={(request) => onChange({ ...scope, request })}
            disabled={disabled || uploading}
            onBusy={(busy) => {
              setUploading(busy);
              onBusy(busy);
            }}
          />
        )}
        {scope.kind === "speech" && (
          <>
            <p className="muted">
              Speech in Polish. Your selected recording provides the voice
              reference. Goal mode writes the spoken text; the voice stays
              fixed.
            </p>
            <MediaInput
              kind="audio"
              label="Voice reference"
              hint="Choose or upload a clear PCM WAV recording, 0.1–60 seconds."
              value={scope.request.reference_artifact_id ?? ""}
              disabled={disabled || uploading}
              onChange={(id) =>
                onChange({
                  ...scope,
                  request: {
                    ...scope.request,
                    reference_artifact_id: id || null,
                  },
                })
              }
              onBusy={(busy) => {
                setUploading(busy);
                onBusy(busy);
              }}
            />
            <details>
              <summary>
                <Settings2 size={15} />
                Advanced speech settings
              </summary>
              <p className="muted">
                Chatterbox · local · at most 1000 characters per execution.
              </p>
              <GpuTargetChoiceList
                value={scope.request.gpu ?? "auto"}
                gpus={hardware.data?.gpus ?? []}
                onChange={(gpu) =>
                  onChange({ ...scope, request: { ...scope.request, gpu } })
                }
              />
            </details>
          </>
        )}
        {scope.kind === "music" && (
          <MusicScope
            value={scope.request}
            descriptionLength={caption.trim().length}
            allowAutomaticDuration={false}
            lyricsSource={scope.lyrics_source ?? "fixed"}
            onLyricsSourceChange={
              scope.description_source === "goal"
                ? (lyrics_source) => onChange({ ...scope, lyrics_source })
                : undefined
            }
            onChange={(options, rememberedSource) =>
              onChange({
                ...scope,
                lyrics_source:
                  options.instrumental !== false
                    ? "fixed"
                    : (rememberedSource ??
                      (scope.request.instrumental !== false &&
                      scope.description_source === "goal"
                        ? "goal"
                        : (scope.lyrics_source ?? "fixed"))),
                request: {
                  ...scope.request,
                  ...options,
                  duration_seconds: options.duration_seconds ?? 30,
                },
              })
            }
          />
        )}
        {image && (
          <>
            {image.mode !== "t2i" && (
              <p className="muted">
                {image.mode === "img2img"
                  ? "Preserves the original image as much as possible."
                  : image.mode === "recompose"
                    ? "Preserves identity while allowing clothing, pose and composition to change."
                    : "Makes the reviewed image four times larger. Research tools are available with Generate, Edit and Recompose."}
              </p>
            )}
            {image.mode === "t2i" && (
              <label>
                Image model
                <select
                  aria-label="Agent image model"
                  value={image.backend ?? "qwen"}
                  onChange={(event) =>
                    updateImage({
                      backend: event.target.value as "qwen" | "juggernaut",
                      seed: null,
                    })
                  }
                >
                  <option value="qwen">Qwen</option>
                  <option value="juggernaut">Juggernaut</option>
                </select>
              </label>
            )}
            {image.mode !== "t2i" && (
              <div className="agent-media-references">
                {(image.input_artifact_ids?.length
                  ? image.input_artifact_ids
                  : [""]
                ).map((id, index) => (
                  <div key={index}>
                    <MediaInput
                      kind="image"
                      label={`Reference image ${index + 1}`}
                      hint={
                        image.mode === "recompose"
                          ? "Identity and reference for the new composition."
                          : "Choose the image this agent may use."
                      }
                      value={id}
                      disabled={disabled || uploading}
                      onChange={(next) => {
                        const ids = [...(image.input_artifact_ids ?? [""])];
                        ids[index] = next;
                        updateImage({ input_artifact_ids: ids });
                      }}
                      onBusy={(busy) => {
                        setUploading(busy);
                        onBusy(busy);
                      }}
                    />
                    {image.mode === "recompose" &&
                      (image.input_artifact_ids?.length ?? 0) > 1 && (
                        <Button
                          type="button"
                          variant="ghost"
                          aria-label={`Remove reference image ${index + 1}`}
                          onClick={() =>
                            updateImage({
                              input_artifact_ids:
                                image.input_artifact_ids?.filter(
                                  (_, item) => item !== index,
                                ),
                            })
                          }
                        >
                          <X size={14} />
                          Remove
                        </Button>
                      )}
                  </div>
                ))}
                {image.mode === "recompose" &&
                  (image.input_artifact_ids?.length ?? 0) < 8 && (
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() =>
                        updateImage({
                          input_artifact_ids: [
                            ...(image.input_artifact_ids ?? [""]),
                            "",
                          ],
                        })
                      }
                    >
                      <Plus size={14} />
                      Add reference
                    </Button>
                  )}
              </div>
            )}
            <details>
              <summary>
                <Settings2 size={15} />
                Advanced image settings
              </summary>
              <div className="agent-fields">
                {image.mode === "img2img" && (
                  <label>
                    Maximum side
                    <input
                      type="number"
                      min={256}
                      max={4096}
                      step={32}
                      value={image.max_side ?? 1216}
                      onChange={(event) =>
                        updateImage({ max_side: Number(event.target.value) })
                      }
                    />
                  </label>
                )}
                {["t2i", "recompose"].includes(image.mode) && (
                  <>
                    {(["width", "height"] as const).map((key) => (
                      <label key={key}>
                        {key === "width" ? "Width" : "Height"}
                        <input
                          type="number"
                          min={256}
                          max={2048}
                          step={32}
                          value={image[key] ?? (key === "width" ? 832 : 1216)}
                          onChange={(event) =>
                            updateImage({ [key]: Number(event.target.value) })
                          }
                        />
                      </label>
                    ))}
                  </>
                )}
                {image.mode !== "upscale" && (
                  <label>
                    Steps
                    <input
                      type="number"
                      min={1}
                      max={150}
                      value={image.steps ?? (image.mode === "t2i" ? 35 : 30)}
                      onChange={(event) =>
                        updateImage({ steps: Number(event.target.value) })
                      }
                    />
                  </label>
                )}
                <GpuTargetChoiceList
                  value={image.gpu ?? "auto"}
                  gpus={hardware.data?.gpus ?? []}
                  onChange={(gpu) => updateImage({ gpu })}
                />
                {["t2i", "recompose"].includes(image.mode) && (
                  <label>
                    Guidance (CFG)
                    <input
                      type="number"
                      min={0}
                      max={30}
                      step={0.1}
                      value={image.cfg ?? (image.mode === "t2i" ? 5 : 6)}
                      onChange={(event) =>
                        updateImage({ cfg: Number(event.target.value) })
                      }
                    />
                  </label>
                )}
                {image.mode === "t2i" && image.backend === "juggernaut" && (
                  <label>
                    Seed
                    <input
                      type="number"
                      min={0}
                      max={4294967295}
                      value={image.seed ?? ""}
                      placeholder="42 by default"
                      onChange={(event) =>
                        updateImage({
                          seed: event.target.value
                            ? Number(event.target.value)
                            : null,
                        })
                      }
                    />
                  </label>
                )}
              </div>
            </details>
          </>
        )}
      </fieldset>
      {issue && (
        <p className="notice" role="status">
          {issue}
        </p>
      )}
    </section>
  );
}
