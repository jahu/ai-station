import { useId, useState, type KeyboardEvent } from "react";
import { useSearchParams, Link } from "react-router-dom";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ImagePlus, Sparkles, X } from "lucide-react";
import { api, useHardware, type Artifact, type Run } from "../api";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import {
  useCreative,
  useCreativeDraft,
} from "../components/creative/creative-context";
import LibraryPicker from "../components/media/LibraryPicker";
import MediaResult from "../components/media/MediaResult";
import {
  PromptTranslationControl,
  type TranslationOptions,
} from "../components/media/PromptTranslation";
import {
  mediaBusy,
  useMediaRun,
  useImageWorkflow,
} from "../components/media/media-run";
import { useListKeyboard } from "./useListKeyboard";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import {
  imageSettings,
  type ImageSettings,
  type ImageModelCatalog,
  type ImageModelDefaults,
} from "./image-models";
import {
  ImageOperationChoiceList,
  type ImageOperation,
} from "./ImageOperationChoiceList";

const modes = {
  t2i: "Generate",
  img2img: "Edit",
  recompose: "Recompose",
  upscale: "Upscale",
};
type Mode = ImageOperation;

function SourceStrip({
  ids,
  busy,
  onChange,
}: {
  ids: string[];
  busy: boolean;
  onChange: (ids: string[]) => void;
}) {
  const labelId = useId();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    ids,
    (id) => id,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key === "Enter") event.preventDefault();
  };
  if (!ids.length) return null;
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Selected references · arrow keys move between images.
      </p>
      <div
        ref={listRef}
        className="source-strip"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {ids.map((id, i) => {
          const current = i === index;
          const shortId = id.slice(0, 8);
          return (
            <div
              key={id}
              aria-label={`Source ${i + 1} ${shortId}`}
              {...itemProps(i, id)}
            >
              <img
                src={`/api/artifacts/${id}/thumbnail`}
                alt={`Reference ${i + 1}`}
              />
              <button
                type="button"
                className="icon-button"
                aria-label={`Remove source ${i + 1} ${shortId}`}
                tabIndex={current ? 0 : -1}
                disabled={busy}
                onClick={() => onChange(ids.filter((value) => value !== id))}
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </>
  );
}

export default function Images() {
  const [search] = useSearchParams();
  const creative = useCreative();
  // Remount when Library chooses a different operation or source, not when a
  // generation Run is recorded in the URL.
  return (
    <ImageForm
      key={`${creative?.formKey ?? ""}|${search.get("mode") ?? ""}|${search.get("input") ?? ""}|${search.get("model") ?? ""}`}
      initialMode={search.get("mode") ?? "t2i"}
      initialInput={search.get("input")}
      initialModel={search.get("model")}
    />
  );
}
function ImageForm({
  initialMode,
  initialInput,
  initialModel,
}: {
  initialMode: string;
  initialInput: string | null;
  initialModel: string | null;
}) {
  const creative = useCreative();
  const [initial] = useState(() => creative?.draft ?? {});
  const restored = (initial.formState ?? initial) as Record<string, unknown>;
  const startingMode = String(restored.mode ?? initialMode);
  const [mode, setMode] = useState<Mode>(
    Object.hasOwn(modes, startingMode) ? (startingMode as Mode) : "t2i",
  );
  const [choices, setChoices] = useState<Partial<Record<Mode, string>>>(
    restored.choices
      ? (restored.choices as Partial<Record<Mode, string>>)
      : initialModel
        ? {
            [Object.hasOwn(modes, startingMode) ? startingMode : "t2i"]:
              initialModel,
          }
        : {},
  );
  const catalog = useQuery({
    queryKey: ["image-models"],
    queryFn: () => api<ImageModelCatalog>("/images/models"),
  });
  const [translation, setTranslation] = useState<TranslationOptions>(
    (restored.translation as TranslationOptions | undefined) ?? {
      mode: "inherit",
      review: false,
      protected_terms: [],
    },
  );
  const restoredChoice = initial.model_id
    ? (catalog.data?.items.find(
        (item) => item.definition_id === initial.model_id,
      )?.id ?? `unavailable:${String(initial.model_id)}`)
    : initial.backend
      ? startingMode === "upscale"
        ? "realesrgan"
        : String(initial.backend)
      : undefined;
  const choiceId =
    choices[mode] ??
    (mode === startingMode ? restoredChoice : undefined) ??
    catalog.data?.defaults.choices[mode] ??
    (mode === "upscale" ? "realesrgan" : "qwen");
  const selectedModel = catalog.data?.items.find(
    (model) => model.id === choiceId,
  );
  const backend = selectedModel?.backend ?? "qwen";
  const krea = backend === "krea2";
  const settingsKey = `${mode}:${choiceId}`;
  const [overrides, setOverrides] = useState<
    Record<string, Partial<ImageSettings>>
  >(
    (restored.overrides as
      Record<string, Partial<ImageSettings>> | undefined) ?? {},
  );
  const restoredSettings = Object.fromEntries(
    Object.keys(imageSettings(selectedModel, mode))
      .filter((key) => initial[key] !== undefined)
      .map((key) => [key, initial[key]]),
  ) as Partial<ImageSettings>;
  const settings = {
    ...imageSettings(selectedModel, mode),
    ...(mode === startingMode && choiceId === restoredChoice
      ? restoredSettings
      : {}),
    ...overrides[settingsKey],
  };
  const { width, height, steps, cfg, seed, max_side: maxSide } = settings;
  function setSetting<K extends keyof ImageSettings>(
    key: K,
    value: ImageSettings[K],
  ) {
    setOverrides((current) => ({
      ...current,
      [settingsKey]: { ...current[settingsKey], [key]: value },
    }));
  }
  const [prompt, setPrompt] = useState(
    String(
      startingMode === "t2i"
        ? (restored.prompt ?? "")
        : (restored.edit_prompt ?? restored.prompt ?? ""),
    ),
  );
  const [negative, setNegative] = useState(String(restored.negative ?? ""));
  const [gpu, setGpu] = useState(String(restored.gpu ?? "auto"));
  const [upscaleResult, setUpscaleResult] = useState(
    Boolean(restored.upscaleResult ?? restored.upscale_result),
  );
  const [portraitStyling, setPortraitStyling] = useState(
    Boolean(
      restored.portraitStyling ??
      (mode === "t2i" && initial.prompt_style === "pipeline"),
    ),
  );
  const [classicEdit, setClassicEdit] = useState(
    Boolean(
      restored.classicEdit ??
      (mode !== "t2i" && initial.prompt_style === "pipeline"),
    ),
  );
  const [ids, setIds] = useState<string[]>(
    (restored.ids ??
      restored.input_artifact_ids ??
      (initialInput ? [initialInput] : [])) as string[],
  );
  useCreativeDraft({
    formState: {
      mode,
      choices: selectedModel ? { ...choices, [mode]: choiceId } : choices,
      overrides: selectedModel
        ? { ...overrides, [settingsKey]: settings }
        : overrides,
      prompt,
      negative,
      gpu,
      upscaleResult,
      portraitStyling,
      classicEdit,
      ids,
      translation,
    },
  });
  const [localError, setLocalError] = useState<Error | null>(null);
  const hardware = useHardware();
  const [search, setSearch] = useSearchParams();
  const cache = useQueryClient();
  const saveDefault = useMutation({
    mutationFn: () =>
      api<ImageModelDefaults>("/images/defaults", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode,
          choice: choiceId,
          revision: catalog.data?.defaults.revision,
        }),
      }),
    onSuccess: (defaults) =>
      cache.setQueryData<ImageModelCatalog>(["image-models"], (current) =>
        current ? { ...current, defaults } : current,
      ),
    onError: () => {
      void cache.invalidateQueries({ queryKey: ["image-models"] });
    },
  });
  const maximumSources =
    mode === "recompose" ? (selectedModel?.maximum_references ?? 8) : 1;
  const runId = search.get("run") ?? "";
  const run = useMediaRun(runId);
  const workflow = useImageWorkflow(run.data);
  const activeRun = workflow.data?.steps.at(-1) ?? run.data;
  const sources = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["artifact", id],
      queryFn: () => api<Artifact>(`/artifacts/${id}`),
    })),
  });
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const results: Artifact[] = [];
      for (const file of files) {
        const data = new FormData();
        data.append("file", file);
        const artifact = await api<Artifact>("/images/uploads", {
          method: "POST",
          body: data,
        });
        cache.setQueryData(["artifact", artifact.id], artifact);
        results.push(artifact);
        // Keep completed uploads if a later file is rejected.
        setIds((current) => [...current, artifact.id]);
      }
      return results;
    },
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["artifacts"] });
    },
  });
  function addFiles(files: File[]) {
    setLocalError(null);
    if (upload.isPending) return;
    const maximum = maximumSources;
    if (files.length + ids.length > maximum) {
      setLocalError(
        new Error(
          `This mode accepts ${maximum} source image${maximum > 1 ? "s" : ""}. Remove a source before adding another.`,
        ),
      );
      return;
    }
    if (files.some((f) => f.size > 20 * 1024 * 1024)) {
      setLocalError(new Error("Each image must be at most 20 MiB."));
      return;
    }
    upload.mutate(files);
  }
  const create = useMutation({
    mutationFn: async () => {
      if (!selectedModel?.available || !selectedModel.modes.includes(mode))
        throw new Error("Choose an available model for this operation.");
      const parameters: Record<string, unknown> = {
        mode,
        gpu,
        backend,
        input_artifact_ids: mode === "t2i" ? [] : ids,
        upscale_result: mode !== "upscale" && upscaleResult,
      };
      if (
        mode !== "upscale" &&
        (translation.mode !== "inherit" ||
          translation.review ||
          translation.protected_terms.length)
      )
        parameters.translation = translation;
      if (selectedModel.definition_id)
        parameters.model_id = selectedModel.definition_id;
      if (mode === "t2i" || mode === "recompose")
        Object.assign(parameters, { prompt, width, height, steps, cfg });
      if (mode === "t2i")
        parameters.prompt_style = portraitStyling ? "pipeline" : "prompt";
      if (mode === "img2img" || mode === "recompose")
        parameters.prompt_style = classicEdit ? "pipeline" : "instruction";
      if (mode === "img2img")
        Object.assign(parameters, {
          edit_prompt: prompt,
          max_side: maxSide,
          steps,
        });
      if ((mode === "t2i" && backend === "juggernaut") || krea)
        Object.assign(parameters, { seed, negative });
      if (krea && mode !== "t2i")
        Object.assign(parameters, {
          cfg,
          reference_strength: settings.reference_strength,
          reference_layout: settings.reference_layout,
          grounding_px: settings.grounding_px,
        });
      if (creative) {
        const turn = await creative.generate(parameters, {
          feedback: creative.draft._creative_parent_turn_id ? prompt : "",
        });
        if (!turn.run)
          throw new Error(
            "Generation was queued; refresh its workspace to inspect the result.",
          );
        return turn.run;
      }
      return api<Run>("/images/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parameters),
      });
    },
    onSuccess: (result) => {
      cache.setQueryData(["run", result.id], result);
      void cache.invalidateQueries({ queryKey: ["runs"] });
      setSearch((current) => {
        const next = new URLSearchParams(current);
        next.set("run", result.id);
        return next;
      });
    },
  });
  const source = sources[0]?.data;
  const busy =
    create.isPending ||
    mediaBusy(activeRun) ||
    (!!(
      run.data?.parameters?.upscale_result || run.data?.parameters?.video_prompt
    ) &&
      workflow.isPending);
  const promptStatus = (
    run.data?.metadata?.prompt_translation as { status: string } | undefined
  )?.status;
  const generationProgress =
    promptStatus === "waiting_for_review"
      ? "Waiting for prompt review"
      : promptStatus === "queued"
        ? "Preparing prompt…"
        : "Generating…";
  const oversized =
    mode === "upscale" && source?.metadata.width && source.metadata.height
      ? source.metadata.width * source.metadata.height * 16 > 64 * 1024 * 1024
      : false;
  const missing =
    mode !== "t2i" &&
    (!ids.length || sources.some((s) => s.isPending || s.isError));
  const unavailable =
    !selectedModel?.available || !selectedModel.modes.includes(mode);
  const tooManySources = mode !== "t2i" && ids.length > maximumSources;
  return (
    <>
      <PageTitle
        eyebrow="CREATE / IMAGES"
        title="Make room for imagination."
        action={
          <Button asChild variant="secondary">
            <Link to="/library">Open Library</Link>
          </Button>
        }
      >
        Create and transform images with your local models.
      </PageTitle>
      <ImageOperationChoiceList
        value={mode}
        disabled={upload.isPending || busy}
        onChange={(key) => {
          setMode(key);
          setIds((current) =>
            key === "recompose" ? current : current.slice(0, 1),
          );
          setLocalError(null);
          create.reset();
        }}
      />
      <div className="image-live-workspace">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy && !upload.isPending && !unavailable && !tooManySources)
              create.mutate();
          }}
        >
          <fieldset
            className="image-workspace"
            disabled={upload.isPending || busy}
          >
            <section className="panel content-panel image-form">
              <div className="row spread">
                <h2>{modes[mode]}</h2>
                <span className="chip">
                  LOCAL ·{" "}
                  {krea
                    ? "Krea 2"
                    : mode === "upscale"
                      ? "RealESRGAN"
                      : backend === "juggernaut"
                        ? "Juggernaut"
                        : "Qwen"}
                </span>
              </div>
              <label>
                Model
                <select
                  value={choiceId}
                  disabled={catalog.isPending || busy}
                  onChange={(event) => {
                    setChoices((current) => ({
                      ...current,
                      [mode]: event.target.value,
                    }));
                    setLocalError(null);
                    saveDefault.reset();
                  }}
                >
                  {!selectedModel && (
                    <option value={choiceId}>
                      {catalog.isPending
                        ? "Loading models…"
                        : "Selected model unavailable"}
                    </option>
                  )}
                  {catalog.data?.items
                    .filter((model) => model.modes.includes(mode))
                    .map((model) => (
                      <option
                        key={model.id}
                        value={model.id}
                        disabled={!model.available}
                      >
                        {model.name}
                        {!model.available ? " · unavailable" : ""}
                      </option>
                    ))}
                </select>
              </label>
              <div className="row spread">
                <small className="muted">
                  {catalog.data?.defaults.choices[mode] === choiceId
                    ? `Default for ${modes[mode]}`
                    : "Selected for this image"}
                </small>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={
                    unavailable ||
                    saveDefault.isPending ||
                    catalog.data?.defaults.choices[mode] === choiceId
                  }
                  onClick={() => saveDefault.mutate()}
                >
                  {saveDefault.isPending ? "Saving…" : "Use as default"}
                </Button>
              </div>
              <ErrorNotice error={saveDefault.error} />
              {catalog.isSuccess && unavailable && (
                <p className="notice">
                  This model is unavailable for this operation. Choose another
                  model or check <Link to="/models">Models</Link>.
                </p>
              )}
              {catalog.error && (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => void catalog.refetch()}
                >
                  Retry models
                </Button>
              )}
              {krea && (
                <p className="muted">
                  Uses {selectedModel?.gpu_count ?? 2} GPU
                  {selectedModel?.gpu_count === 1 ? "" : "s"} · all inference on
                  GPU.
                </p>
              )}
              {mode === "img2img" && (
                <p className="muted">
                  Preserves the original image as much as possible.
                </p>
              )}
              {mode === "recompose" && (
                <p className="muted">
                  Preserves identity while allowing pose, clothing, scene and
                  composition to change.
                </p>
              )}
              {mode === "upscale" && (
                <p className="muted">
                  RealESRGAN increases each dimension by 4×.
                </p>
              )}
              {mode !== "t2i" && (
                <>
                  <label
                    className="upload-zone"
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      addFiles(Array.from(e.dataTransfer.files));
                    }}
                  >
                    <ImagePlus size={28} />
                    <strong>
                      {upload.isPending
                        ? "Uploading…"
                        : "Drop source images here"}
                    </strong>
                    <span>or choose PNG, JPEG, WebP · 20 MiB each</span>
                    <input
                      aria-label="Upload source images"
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      multiple={mode === "recompose"}
                      disabled={upload.isPending}
                      onChange={(e) => {
                        addFiles(Array.from(e.target.files ?? []));
                        e.target.value = "";
                      }}
                    />
                  </label>
                  <LibraryPicker
                    kind="image"
                    existing={ids}
                    limit={Math.max(0, maximumSources - ids.length)}
                    busy={upload.isPending}
                    onSelect={(items) => {
                      const maximum = maximumSources;
                      if (items.length + ids.length > maximum) {
                        setLocalError(
                          new Error(
                            `This mode accepts ${maximum} source image${maximum > 1 ? "s" : ""}. Remove a source before adding another.`,
                          ),
                        );
                        return;
                      }
                      setLocalError(null);
                      for (const artifact of items) {
                        cache.setQueryData(["artifact", artifact.id], artifact);
                      }
                      setIds((current) => [
                        ...current,
                        ...items.map((artifact) => artifact.id),
                      ]);
                    }}
                  />
                  <SourceStrip
                    ids={ids}
                    busy={upload.isPending}
                    onChange={setIds}
                  />
                  {krea && mode === "recompose" && (
                    <p className="muted">
                      Up to two references: scene or appearance first, subject
                      second.{" "}
                      {ids.length === 2 && (
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() =>
                            setIds(([first, second]) => [second, first])
                          }
                        >
                          Swap references
                        </Button>
                      )}
                    </p>
                  )}
                  {tooManySources && (
                    <p className="notice">
                      This model accepts {maximumSources} references. Remove
                      extra images before continuing.
                    </p>
                  )}
                </>
              )}
              {mode !== "upscale" && (
                <label>
                  {mode === "img2img" ? "Edit instruction" : "Prompt"}
                  <textarea
                    aria-label={mode === "img2img" ? "Edit instruction" : "Prompt"}
                    required
                    maxLength={10000}
                    rows={6}
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder={
                      mode === "img2img"
                        ? "Describe what to change…"
                        : "Describe the scene, subject, light, and mood…"
                    }
                  />
                </label>
              )}
              {((mode === "t2i" && backend === "juggernaut") || krea) && (
                <label>
                  Negative prompt
                  <textarea
                    rows={2}
                    maxLength={10000}
                    value={negative}
                    onChange={(e) => setNegative(e.target.value)}
                    placeholder="Elements to avoid…"
                  />
                </label>
              )}
              {mode !== "upscale" && (
                <PromptTranslationControl
                  value={translation}
                  onChange={setTranslation}
                  disabled={busy}
                />
              )}
              {mode !== "upscale" && (
                <label className="image-workflow-option">
                  <input
                    type="checkbox"
                    checked={upscaleResult}
                    onChange={(event) => setUpscaleResult(event.target.checked)}
                  />
                  <span>
                    Upscale result 4×
                    <small>
                      Generate or edit first, then enlarge automatically. Both
                      images stay in Library.
                    </small>
                  </span>
                </label>
              )}
              {mode === "upscale" && source?.metadata.width && (
                <p className={oversized ? "notice" : "muted"}>
                  Expected output: {source.metadata.width * 4} ×{" "}
                  {(source.metadata.height ?? 0) * 4}
                  {oversized
                    ? " — exceeds the 64 megapixel limit. Choose a smaller source."
                    : ""}
                </p>
              )}
              <ErrorNotice
                error={
                  localError ??
                  upload.error ??
                  create.error ??
                  catalog.error ??
                  sources.find((s) => s.error)?.error ??
                  null
                }
              />
              <Button
                type="submit"
                disabled={
                  busy ||
                  upload.isPending ||
                  missing ||
                  !!oversized ||
                  unavailable ||
                  tooManySources
                }
              >
                <Sparkles size={16} />
                {busy
                  ? generationProgress
                  : `Queue ${modes[mode].toLowerCase()}`}
              </Button>
            </section>
            <aside className="panel content-panel image-form">
              <h2>Generation settings</h2>
              {mode === "t2i" && backend === "qwen" && (
                <label className="image-workflow-option">
                  <input
                    type="checkbox"
                    aria-label="Add portrait styling"
                    checked={portraitStyling}
                    disabled={busy}
                    onChange={(e) => setPortraitStyling(e.target.checked)}
                  />
                  <span>
                    Add portrait styling
                    <small>
                      Adds skin, hair and eye detail. Leave off for scenes,
                      products and illustrations.
                    </small>
                  </span>
                </label>
              )}
              {backend === "qwen" &&
                (mode === "img2img" || mode === "recompose") && (
                  <label className="image-workflow-option">
                    <input
                      type="checkbox"
                      aria-label="Use classic identity template"
                      checked={classicEdit}
                      disabled={busy}
                      onChange={(event) => setClassicEdit(event.target.checked)}
                    />
                    <span>
                      Use classic identity template
                      <small>
                        Off follows your edit directly. On adds the original
                        identity and photo-detail instructions.
                      </small>
                    </span>
                  </label>
                )}
              {(mode === "t2i" || mode === "recompose") && (
                <>
                  <div className="field-pair">
                    <label>
                      Width
                      <input
                        type="number"
                        min={256}
                        max={2048}
                        step={32}
                        value={width}
                        onChange={(e) =>
                          setSetting("width", e.target.valueAsNumber)
                        }
                      />
                    </label>
                    <label>
                      Height
                      <input
                        type="number"
                        min={256}
                        max={2048}
                        step={32}
                        value={height}
                        onChange={(e) =>
                          setSetting("height", e.target.valueAsNumber)
                        }
                      />
                    </label>
                  </div>
                  <label>
                    CFG
                    <input
                      type="number"
                      min={krea ? 1 : 0}
                      max={krea ? 10 : 30}
                      step={0.1}
                      value={cfg}
                      onChange={(e) =>
                        setSetting("cfg", e.target.valueAsNumber)
                      }
                    />
                  </label>
                </>
              )}
              {mode === "img2img" && (
                <label>
                  Maximum side
                  <input
                    type="number"
                    min={256}
                    max={krea ? 2048 : 4096}
                    step={32}
                    value={maxSide}
                    onChange={(e) =>
                      setSetting("max_side", e.target.valueAsNumber)
                    }
                  />
                </label>
              )}
              {mode !== "upscale" && (
                <label>
                  Steps
                  <input
                    type="number"
                    min={1}
                    max={krea ? 100 : 150}
                    value={steps}
                    onChange={(e) =>
                      setSetting("steps", e.target.valueAsNumber)
                    }
                  />
                </label>
              )}
              {((mode === "t2i" && backend === "juggernaut") || krea) && (
                <label>
                  Seed
                  <input
                    type="number"
                    min={0}
                    max={4294967295}
                    value={seed}
                    onChange={(e) => setSetting("seed", e.target.valueAsNumber)}
                  />
                </label>
              )}
              {krea && mode !== "t2i" && (
                <details>
                  <summary>Reference settings</summary>
                  <label>
                    Reference strength
                    <input
                      type="number"
                      min={0}
                      max={8}
                      step={0.1}
                      value={settings.reference_strength}
                      onChange={(event) =>
                        setSetting(
                          "reference_strength",
                          event.target.valueAsNumber,
                        )
                      }
                    />
                  </label>
                  <label>
                    Composition
                    <select
                      value={settings.reference_layout}
                      onChange={(event) =>
                        setSetting(
                          "reference_layout",
                          event.target
                            .value as ImageSettings["reference_layout"],
                        )
                      }
                    >
                      <option value="aligned">Preserve original layout</option>
                      <option value="beside">
                        Allow a new pose and layout
                      </option>
                    </select>
                  </label>
                  <label>
                    Reference detail
                    <input
                      type="number"
                      min={384}
                      max={1024}
                      step={64}
                      value={settings.grounding_px}
                      onChange={(event) =>
                        setSetting("grounding_px", event.target.valueAsNumber)
                      }
                    />
                  </label>
                  {mode === "img2img" && (
                    <label>
                      CFG
                      <input
                        type="number"
                        min={1}
                        max={10}
                        step={0.1}
                        value={cfg}
                        onChange={(event) =>
                          setSetting("cfg", event.target.valueAsNumber)
                        }
                      />
                    </label>
                  )}
                </details>
              )}
              {selectedModel?.file && (
                <details>
                  <summary>Model details</summary>
                  <p className="muted">{selectedModel.file.filename}</p>
                  {selectedModel.license_url && (
                    <a
                      href={selectedModel.license_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Model license and usage terms
                    </a>
                  )}
                  {krea && (
                    <p className="muted">
                      V2 edit LoRA: personal / non-commercial use; commercial
                      use requires the author's agreement.
                    </p>
                  )}
                </details>
              )}
              <div>
                <span>{krea ? "Primary GPU" : "GPU"}</span>
                <GpuTargetChoiceList
                  hint={
                    krea && selectedModel?.gpu_count !== 1
                      ? "Choose the GPU for the image model. The encoder uses another available card."
                      : "Auto chooses the next available GPU."
                  }
                  value={gpu}
                  gpus={hardware.data?.gpus ?? []}
                  disabled={create.isPending || upload.isPending}
                  onChange={setGpu}
                />
              </div>
              {hardware.error && (
                <p className="muted">
                  GPU discovery is unavailable. The worker will verify the
                  runner before execution.
                </p>
              )}
              <p className="muted">
                Results appear here and in Library. You can stop generation or
                inspect its settings and logs at any time.
              </p>
            </aside>
          </fieldset>
        </form>
        {!creative && (
          <MediaResult
            kind={
              activeRun?.capability === "video.generate" ? "video" : "image"
            }
            videoMode="scene"
            runId={activeRun?.id ?? runId}
            run={activeRun}
            steps={workflow.data?.steps}
            error={run.error ?? workflow.error}
          />
        )}
      </div>
    </>
  );
}
