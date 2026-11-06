import AgentImageModel from "./AgentImageModel";
import "./AgentImageScenes.css";
import { useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Image,
  Music2,
  AudioLines,
  Film,
  UserRound,
  Settings2,
  Plus,
  X,
  Waves,
} from "lucide-react";
import MediaInput from "../components/media/MediaInput";
import { Button } from "../components/ui/button";
import { api, useHardware } from "../api";
import SpeechEngineFields from "../components/media/SpeechEngineFields";
import { useSpeechModels } from "../components/media/speech-models";
import type { SpeechCapabilities } from "../components/media/speech-delivery";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import MusicScope from "./MusicScope";
import AgentVideoScope from "./AgentVideoScope";
import AgentEffectsScope from "./AgentEffectsScope";
import AgentAvatarScope from "./AgentAvatarScope";
import { useWholeAvatarCapabilities } from "../components/media/AvatarWholeProfile";
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
  const cache = useQueryClient();
  const [uploading, setUploading] = useState(false);
  const hardware = useHardware();
  const wholeAvatar = useWholeAvatarCapabilities();
  const scope = value ?? newAgentMedia("image", goal);
  const speechModelId =
    scope.kind === "speech" ? scope.request.model_id : undefined;
  const speechModels = useSpeechModels(scope.kind === "speech");
  const speech = useQuery({
    queryKey: speechModelId
      ? ["speech-capabilities", speechModelId]
      : ["speech-capabilities"],
    queryFn: () =>
      api<SpeechCapabilities>(
        speechModelId
          ? `/audio/models/${speechModelId}/capabilities`
          : "/audio/capabilities",
      ),
    enabled: scope.kind === "speech",
    staleTime: 30000,
    refetchInterval: (query) =>
      query.state.data?.engines?.fish_s2_pro?.readiness === "checking"
        ? 2000
        : false,
  });
  const effects = useQuery({
    queryKey: ["effects-capabilities"],
    queryFn: () =>
      api<{ available: boolean; readiness?: string; reason?: string }>(
        "/audio/effects/capabilities",
      ),
    enabled: scope.kind === "effects",
    staleTime: 30000,
    refetchInterval: (q) =>
      q.state.data?.readiness === "checking" ? 1000 : false,
  });
  useEffect(() => {
    if (effects.data?.available)
      void cache.invalidateQueries({ queryKey: ["agent-tools"] });
  }, [effects.data?.available, cache]);
  const videoModelId =
    scope.kind === "video" ? scope.request.model_id : undefined;
  const selectedVideo = useQuery({
    queryKey: ["video-capabilities", videoModelId],
    enabled: !!videoModelId,
    queryFn: () =>
      api<{ available: boolean; reason?: string }>(
        `/video/models/${videoModelId}/capabilities`,
      ),
  });
  const musicModelId =
    scope.kind === "music" ? scope.request.model_id : undefined;
  const selectedMusic = useQuery({
    queryKey: ["music-capabilities", musicModelId],
    enabled: !!musicModelId,
    queryFn: () =>
      api<{ available: boolean; reason?: string }>(
        `/audio/music/models/${musicModelId}/capabilities`,
      ),
  });
  const selectedReadiness = musicModelId
    ? {
        ready: selectedMusic.isPending
          ? undefined
          : selectedMusic.data?.available === true,
        reason:
          selectedMusic.error?.message ??
          selectedMusic.data?.reason ??
          "Checking selected music model…",
      }
    : videoModelId
      ? {
          ready: selectedVideo.isPending
            ? undefined
            : selectedVideo.data?.available === true,
          reason:
            selectedVideo.error?.message ??
            selectedVideo.data?.reason ??
            "Checking selected video model…",
        }
      : speechModelId
        ? {
            ready: speech.isPending
              ? undefined
              : speech.data?.available === true,
            reason: speech.error?.message ?? "Checking selected speech model…",
          }
        : scope.kind === "speech" && scope.request.engine === "fish_s2_pro"
          ? {
              ready:
                speech.data?.engines?.fish_s2_pro?.available === true &&
                (scope.request.voice_source !== "model" ||
                  speech.data?.engines?.fish_s2_pro?.voice_sources?.includes(
                    "model",
                  ) === true),
              reason:
                scope.request.voice_source === "model" &&
                speech.data &&
                !speech.data.engines?.fish_s2_pro?.voice_sources?.includes(
                  "model",
                )
                  ? "Update AI Station or choose a voice recording."
                  : (speech.data?.engines?.fish_s2_pro?.reason ??
                    "Checking expressive speech setup…"),
            }
          : scope.kind === "effects"
            ? {
                ready: effects.data?.available === true,
                reason: effects.data?.reason ?? "Checking sound effects setup…",
              }
            : readiness?.[scope.kind];
  const recordedWhole =
    scope.kind === "avatar" &&
    !!scope.request.generation_profile &&
    scope.request.speech_text === null;
  const image = scope.kind === "image" ? scope.request : null;
  const caption =
    scope.kind === "avatar"
      ? (scope.request.speech_text ?? scope.request.prompt)
      : scope.kind === "video" || scope.kind === "effects"
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
    scope.kind === "effects"
      ? Waves
      : scope.kind === "avatar"
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
  function changeImageMode(mode: ImageMediaRequest["mode"]) {
    if (!image) return;
    const keepKrea =
      image.backend === "krea2" && !!image.model_id && mode !== "upscale";
    onChange({
      kind: "image",
      description_source:
        mode === "upscale"
          ? "fixed"
          : mode === "recompose"
            ? "goal"
            : scope.description_source,
      ...(mode === "recompose" ? { vary_scenes: true } : {}),
      request: {
        mode,
        backend: keepKrea ? "krea2" : "qwen",
        ...(keepKrea
          ? {
              model_id: image.model_id,
              steps: image.steps ?? 8,
              cfg: image.cfg ?? 1,
              seed: image.seed ?? 42,
            }
          : {}),
        ...(keepKrea && mode !== "t2i"
          ? {
              reference_layout:
                mode === "recompose"
                  ? ("beside" as const)
                  : ("aligned" as const),
              reference_strength: mode === "recompose" ? 2 : 4,
              grounding_px: image.grounding_px ?? 768,
            }
          : {}),
        ...(mode === "recompose"
          ? { prompt_style: "instruction" as const }
          : {}),
        prompt: caption || goal,
        edit_prompt: caption || goal,
        input_artifact_ids:
          mode === "t2i"
            ? []
            : image.input_artifact_ids?.slice(0, mode === "recompose" ? 8 : 1)
                  .length
              ? image.input_artifact_ids.slice(0, mode === "recompose" ? 8 : 1)
              : [""],
        gpu: image.gpu ?? "auto",
      },
    });
  }
  const imageGoal = !!image && scope.description_source === "goal";
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
      {selectedReadiness?.ready === false && (
        <p className="error" role="status">
          {selectedReadiness.reason ||
            "The selected local media engine is unavailable."}{" "}
          You can save this draft and enable it after setup.
        </p>
      )}
      <fieldset disabled={disabled || uploading}>
        <div className="mode-tabs" aria-label="Media output type">
          {(
            ["image", "music", "speech", "video", "avatar", "effects"] as const
          ).map((kind) => (
            <button
              type="button"
              key={kind}
              aria-pressed={scope.kind === kind}
              className={scope.kind === kind ? "active" : ""}
              onClick={() =>
                onChange({
                  ...newAgentMedia(
                    kind,
                    goal,
                    wholeAvatar.data?.available === true,
                  ),
                  description_source: scope.description_source,
                })
              }
            >
              {kind === "effects" ? (
                <Waves size={16} />
              ) : kind === "avatar" ? (
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
              {kind === "effects"
                ? "Sound effects"
                : kind === "avatar"
                  ? "Avatar"
                  : kind === "video"
                    ? "Video"
                    : kind === "image"
                      ? "Image"
                      : kind === "speech"
                        ? "Speech"
                        : "Music"}
            </button>
          ))}
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
                  description_source:
                    event.target.value === "recording" &&
                    scope.request.generation_profile
                      ? "fixed"
                      : scope.description_source,
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
              onChange={(event) =>
                changeImageMode(event.target.value as ImageMediaRequest["mode"])
              }
            >
              <option value="t2i">Create from text</option>
              <option value="img2img">
                Small changes to the reference image
              </option>
              <option value="recompose">New variations from references</option>
              <option value="upscale">Upscale 4×</option>
            </select>
          </label>
        )}
        {image?.mode === "img2img" && (
          <div className="agent-image-purpose notice">
            <div>
              <strong>Want a new composition or setting?</strong>
              <p>
                Small edits stay close to the reference. Variations follow your
                brief to decide which features stay consistent and which may
                change.
              </p>
            </div>
            <Button
              type="button"
              variant="secondary"
              onClick={() => changeImageMode("recompose")}
            >
              Use variations
            </Button>
          </div>
        )}
        {image?.mode === "recompose" &&
          scope.kind === "image" &&
          scope.description_source === "goal" && (
            <label className="agent-image-variety">
              <input
                type="checkbox"
                checked={scope.vary_scenes === true}
                onChange={(event) =>
                  onChange({
                    ...scope,
                    vary_scenes: event.target.checked,
                    request: {
                      ...image,
                      ...(event.target.checked
                        ? { prompt_style: "instruction" as const }
                        : {}),
                    },
                  })
                }
              />
              <span>
                <strong>Vary results between runs</strong>
                <small>
                  Plan changes appropriate to your subject and instruction. Use
                  the last three completed runs to avoid repeating the same
                  idea.
                </small>
              </span>
            </label>
          )}
        {image?.backend === "krea2" &&
          (image.mode === "img2img" || image.mode === "recompose") && (
            <label>
              Reference composition
              <select
                aria-label="Agent reference composition"
                value={image.reference_layout ?? "aligned"}
                onChange={(event) =>
                  updateImage({
                    reference_layout: event.target.value as
                      "aligned" | "beside",
                  })
                }
              >
                <option value="aligned">Keep reference framing</option>
                <option value="beside">Allow new viewpoints</option>
              </select>
              <small>
                Allow new viewpoints for changes to camera angle or composition.
                Your brief decides which features stay consistent.
              </small>
            </label>
          )}
        {image?.mode !== "upscale" && !recordedWhole && (
          <>
            <label>
              {image ? "On each run" : "Description policy"}
              <select
                aria-label="Media description policy"
                value={scope.description_source}
                onChange={(event) =>
                  onChange({
                    ...scope,
                    description_source: event.target.value as "fixed" | "goal",
                    ...(scope.kind === "image" && event.target.value === "fixed"
                      ? { vary_scenes: false }
                      : {}),
                    ...(scope.kind === "music" && event.target.value === "fixed"
                      ? { lyrics_source: "fixed" as const }
                      : {}),
                  })
                }
              >
                <option value="goal">
                  {image
                    ? "Prepare an image from my instruction"
                    : "Let Local AI prepare it from the goal and sources"}
                </option>
                <option value="fixed">
                  {image
                    ? "Use an exact image prompt"
                    : "Use this exact description every time"}
                </option>
              </select>
            </label>
            <p className="muted">
              {scope.description_source === "goal"
                ? image
                  ? "Your main instruction above drives each image. The local model prepares the image prompt; references and generation settings stay as reviewed."
                  : "Your selected local model writes the description. The references and settings below stay fixed."
                : "Runs directly with the media engine. No language model is needed."}
            </p>
            <ImageGuidance
              advanced={imageGoal}
              saved={caption !== goal && !!caption}
            >
              <label>
                {scope.kind === "speech" ||
                (scope.kind === "avatar" && scope.request.speech_text !== null)
                  ? "Spoken text or writing instructions"
                  : scope.kind === "avatar"
                    ? "Motion direction"
                    : imageGoal
                      ? "Optional visual details"
                      : "Creative direction"}
                <textarea
                  aria-label="Media creative direction"
                  rows={4}
                  required={!imageGoal}
                  maxLength={
                    scope.kind === "avatar"
                      ? scope.request.speech_text !== null
                        ? 1000
                        : 2000
                      : scope.kind === "music"
                        ? 512
                        : scope.kind === "speech"
                          ? 1000
                          : scope.kind === "video" || scope.kind === "effects"
                            ? 2000
                            : 10000
                  }
                  value={imageGoal && caption === goal ? "" : caption}
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
                      : scope.kind === "effects"
                        ? onChange({
                            ...scope,
                            request: {
                              ...scope.request,
                              prompt: event.target.value,
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
                                    ? {
                                        edit_prompt:
                                          imageGoal && !event.target.value
                                            ? goal
                                            : event.target.value,
                                      }
                                    : {
                                        prompt:
                                          imageGoal && !event.target.value
                                            ? goal
                                            : event.target.value,
                                      },
                                )
                  }
                  placeholder={
                    scope.kind === "speech"
                      ? "Write the exact Polish text, or describe the short briefing your agent should write…"
                      : "Describe the mood, subject and style your agent should create…"
                  }
                />
              </label>{" "}
            </ImageGuidance>
          </>
        )}
        {scope.kind === "avatar" && (
          <AgentAvatarScope
            value={scope.request}
            disabled={disabled || uploading}
            onChange={(request) =>
              onChange({
                ...scope,
                request,
                description_source:
                  request.generation_profile && request.speech_text === null
                    ? "fixed"
                    : scope.description_source,
              })
            }
            onBusy={(busy) => {
              setUploading(busy);
              onBusy(busy);
            }}
          />
        )}
        {scope.kind === "effects" && (
          <AgentEffectsScope
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
            <SpeechEngineFields
              modelId={scope.request.model_id}
              models={speechModels.data?.items}
              onModel={(id) =>
                onChange({
                  ...scope,
                  request: {
                    ...scope.request,
                    model_id: id,
                    engine: undefined,
                    direction: undefined,
                    pace: undefined,
                    voice_source: undefined,
                  },
                })
              }
              engine={scope.request.engine ?? ""}
              direction={scope.request.direction ?? "natural"}
              pace={scope.request.pace ?? "natural"}
              capabilities={speech.data}
              voiceSource={scope.request.voice_source ?? "reference"}
              onVoiceSource={(voice_source) =>
                onChange({
                  ...scope,
                  request: {
                    ...scope.request,
                    voice_source,
                    reference_artifact_id:
                      voice_source === "model"
                        ? null
                        : scope.request.reference_artifact_id,
                  },
                })
              }
              onEngine={(engine) => {
                const request = { ...scope.request };
                delete request.engine;
                delete request.model_id;
                delete request.direction;
                delete request.pace;
                delete request.delivery;
                delete request.voice_source;
                onChange({
                  ...scope,
                  request: {
                    ...request,
                    ...(engine === "fish_s2_pro"
                      ? {
                          engine: "fish_s2_pro" as const,
                          direction: "natural" as const,
                          pace: "natural" as const,
                          ...(!request.reference_artifact_id &&
                          speech.data?.engines?.fish_s2_pro?.voice_sources?.includes(
                            "model",
                          )
                            ? { voice_source: "model" as const }
                            : {}),
                        }
                      : {}),
                  },
                });
              }}
              onDirection={(direction) =>
                onChange({
                  ...scope,
                  request: {
                    ...scope.request,
                    direction: direction as typeof scope.request.direction,
                  },
                })
              }
              onPace={(pace) =>
                onChange({
                  ...scope,
                  request: {
                    ...scope.request,
                    pace: pace as typeof scope.request.pace,
                  },
                })
              }
            />
            <p className="muted">
              {scope.request.voice_source === "model"
                ? "Fish generates the voice. Goal mode writes fresh words for each execution."
                : "Speech in Polish. Your selected recording provides the voice reference. Goal mode writes the spoken text; the voice stays fixed."}
            </p>
            {scope.request.voice_source !== "model" && (
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
            )}
            <details>
              <summary>
                <Settings2 size={15} />
                Advanced speech settings
              </summary>
              <p className="muted">
                {scope.request.engine === "fish_s2_pro"
                  ? "Fish S2 Pro · local · Auto reserves two compatible GPUs."
                  : "Chatterbox · local · at most 1000 characters per execution."}
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
                    ? "Uses the references according to your brief: keep requested features and vary only the relevant aspects."
                    : "Makes the reviewed image four times larger. Research tools are available with Generate, Edit and Recompose."}
              </p>
            )}
            {image.mode === "t2i" && (
              <AgentImageModel
                request={image}
                disabled={disabled || uploading}
                onChange={(request) =>
                  onChange({ ...scope, kind: "image", request })
                }
              />
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
                    Negative prompt
                    <textarea
                      aria-label="Agent negative prompt"
                      value={image.negative ?? ""}
                      placeholder="Optional: what to avoid"
                      onChange={(event) =>
                        updateImage({ negative: event.target.value || null })
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

function ImageGuidance({
  advanced,
  saved,
  children,
}: {
  advanced: boolean;
  saved: boolean;
  children: ReactNode;
}) {
  return advanced ? (
    <details className="agent-image-guidance">
      <summary>
        Additional visual details{saved ? " · saved" : " (optional)"}
      </summary>
      <p className="muted">
        Optional style constraints. Your main instruction takes priority. Leave
        empty to use that instruction alone.
      </p>
      {children}
    </details>
  ) : (
    <>{children}</>
  );
}
