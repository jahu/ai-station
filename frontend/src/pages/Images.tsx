import { useId, useState, type KeyboardEvent } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Sparkles, X } from "lucide-react";
import { api, useHardware, type Artifact, type Run } from "../api";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import LibraryPicker from "../components/media/LibraryPicker";
import MediaResult from "../components/media/MediaResult";
import {
  mediaBusy,
  useMediaRun,
  useImageWorkflow,
} from "../components/media/media-run";
import { useListKeyboard } from "./useListKeyboard";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import {
  ImageBackendChoiceList,
  type ImageBackend,
} from "./ImageBackendChoiceList";
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
        Arrow keys choose a source while the list is focused. Remove stays on
        the selected image. Enter does not queue a Run. There is no inspectable
        source Run.
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
  // Remount when Library chooses a different operation or source, not when a
  // generation Run is recorded in the URL.
  return (
    <ImageForm
      key={`${search.get("mode") ?? ""}|${search.get("input") ?? ""}`}
      initialMode={search.get("mode") ?? "t2i"}
      initialInput={search.get("input")}
    />
  );
}
function ImageForm({
  initialMode,
  initialInput,
}: {
  initialMode: string;
  initialInput: string | null;
}) {
  const [mode, setMode] = useState<Mode>(
    Object.hasOwn(modes, initialMode) ? (initialMode as Mode) : "t2i",
  );
  const [backend, setBackend] = useState<ImageBackend>("qwen");
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [width, setWidth] = useState(832);
  const [height, setHeight] = useState(1216);
  const [steps, setSteps] = useState(mode === "t2i" ? 35 : 30);
  const [cfg, setCfg] = useState(mode === "recompose" ? 6 : 5);
  const [seed, setSeed] = useState(42);
  const [maxSide, setMaxSide] = useState(1216);
  const [gpu, setGpu] = useState("auto");
  const [upscaleResult, setUpscaleResult] = useState(false);
  const [ids, setIds] = useState<string[]>(initialInput ? [initialInput] : []);
  const [localError, setLocalError] = useState<Error | null>(null);
  const hardware = useHardware();
  const [search, setSearch] = useSearchParams();
  const cache = useQueryClient();
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
    const maximum = mode === "recompose" ? 8 : 1;
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
    mutationFn: () => {
      const parameters: Record<string, unknown> = {
        mode,
        gpu,
        backend: mode === "t2i" ? backend : "qwen",
        input_artifact_ids: mode === "t2i" ? [] : ids,
        upscale_result: mode !== "upscale" && upscaleResult,
      };
      if (mode === "t2i" || mode === "recompose")
        Object.assign(parameters, { prompt, width, height, steps, cfg });
      if (mode === "img2img")
        Object.assign(parameters, {
          edit_prompt: prompt,
          max_side: maxSide,
          steps,
        });
      if (mode === "t2i" && backend === "juggernaut")
        Object.assign(parameters, { seed, negative });
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
    (!!run.data?.parameters?.upscale_result && workflow.isPending);
  const oversized =
    mode === "upscale" && source?.metadata.width && source.metadata.height
      ? source.metadata.width * source.metadata.height * 16 > 64 * 1024 * 1024
      : false;
  const missing =
    mode !== "t2i" &&
    (!ids.length || sources.some((s) => s.isPending || s.isError));
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
        Create and transform images with your local photo pipeline.
      </PageTitle>
      <ImageOperationChoiceList
        value={mode}
        disabled={upload.isPending || busy}
        onChange={(key) => {
          setMode(key);
          setSteps(key === "t2i" ? 35 : 30);
          setCfg(key === "recompose" ? 6 : 5);
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
            if (!busy && !upload.isPending) create.mutate();
          }}
        >
          <fieldset
            className="image-workspace"
            disabled={upload.isPending || busy}
          >
            <section className="panel content-panel image-form">
              <div className="row spread">
                <h2>{modes[mode]}</h2>
                <span className="chip">LOCAL · photo_pipe</span>
              </div>
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
                    limit={(mode === "recompose" ? 8 : 1) - ids.length}
                    busy={upload.isPending}
                    onSelect={(items) => {
                      const maximum = mode === "recompose" ? 8 : 1;
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
                </>
              )}
              {mode !== "upscale" && (
                <label>
                  {mode === "img2img" ? "Edit instruction" : "Prompt"}
                  <textarea
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
              {mode === "t2i" && backend === "juggernaut" && (
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
                  sources.find((s) => s.error)?.error ??
                  null
                }
              />
              <Button
                type="submit"
                disabled={busy || upload.isPending || missing || !!oversized}
              >
                <Sparkles size={16} />
                {busy ? "Generating…" : `Queue ${modes[mode].toLowerCase()}`}
              </Button>
            </section>
            <aside className="panel content-panel image-form">
              <h2>Generation settings</h2>
              {mode === "t2i" && (
                <div>
                  <span>Backend</span>
                  <ImageBackendChoiceList
                    value={backend}
                    disabled={create.isPending || upload.isPending}
                    onChange={setBackend}
                  />
                </div>
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
                        onChange={(e) => setWidth(e.target.valueAsNumber)}
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
                        onChange={(e) => setHeight(e.target.valueAsNumber)}
                      />
                    </label>
                  </div>
                  <label>
                    CFG
                    <input
                      type="number"
                      min={0}
                      max={30}
                      step={0.1}
                      value={cfg}
                      onChange={(e) => setCfg(e.target.valueAsNumber)}
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
                    max={4096}
                    step={32}
                    value={maxSide}
                    onChange={(e) => setMaxSide(e.target.valueAsNumber)}
                  />
                </label>
              )}
              {mode !== "upscale" && (
                <label>
                  Steps
                  <input
                    type="number"
                    min={1}
                    max={150}
                    value={steps}
                    onChange={(e) => setSteps(e.target.valueAsNumber)}
                  />
                </label>
              )}
              {mode === "t2i" && backend === "juggernaut" && (
                <label>
                  Seed
                  <input
                    type="number"
                    min={0}
                    max={4294967295}
                    value={seed}
                    onChange={(e) => setSeed(e.target.valueAsNumber)}
                  />
                </label>
              )}
              <div>
                <span>GPU</span>
                <GpuTargetChoiceList
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
                Jobs use the configured native pipeline and installed models.
                Missing models fail with an inspectable error; downloads are
                disabled.
              </p>
              <p className="muted">
                Generation stays in this workspace. Stop it here, inspect
                lineage on the finished image, and open the Run only for logs.
                Failed, canceled or interrupted generation can retry here as a
                new run. Completed images also remain in Library.
              </p>
            </aside>
          </fieldset>
        </form>
        <MediaResult
          kind="image"
          runId={activeRun?.id ?? runId}
          run={activeRun}
          steps={workflow.data?.steps}
          error={run.error ?? workflow.error}
        />
      </div>
    </>
  );
}
