import { useId, useState, type KeyboardEvent } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Sparkles, X } from "lucide-react";
import { api, useHardware, type Artifact, type Run } from "../api";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import LibraryPicker from "../components/media/LibraryPicker";
import { useListKeyboard } from "./useListKeyboard";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import {
  ImageBackendChoiceList,
  type ImageBackend,
} from "./ImageBackendChoiceList";

const modes = {
  t2i: "Generate",
  img2img: "Edit",
  recompose: "Recompose",
  upscale: "Upscale",
};
type Mode = keyof typeof modes;

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
  // Remount when navigating here from a Library action.
  return (
    <ImageForm
      key={search.toString()}
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
  const [ids, setIds] = useState<string[]>(initialInput ? [initialInput] : []);
  const [localError, setLocalError] = useState<Error | null>(null);
  const hardware = useHardware();
  const navigate = useNavigate();
  const cache = useQueryClient();
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
    onSuccess: (run) => {
      void cache.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/runs/${run.id}`);
    },
  });
  const source = sources[0]?.data;
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
      <div className="mode-tabs" aria-label="Image operation">
        {Object.entries(modes).map(([key, label]) => (
          <button
            key={key}
            aria-pressed={mode === key}
            disabled={upload.isPending || create.isPending}
            onClick={() => {
              setMode(key as Mode);
              setSteps(key === "t2i" ? 35 : 30);
              setCfg(key === "recompose" ? 6 : 5);
              setIds((current) =>
                key === "recompose" ? current : current.slice(0, 1),
              );
              setLocalError(null);
              create.reset();
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <form
        className="image-workspace"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
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
            <p className="muted">RealESRGAN increases each dimension by 4×.</p>
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
                  {upload.isPending ? "Uploading…" : "Drop source images here"}
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
            disabled={
              create.isPending || upload.isPending || missing || !!oversized
            }
          >
            <Sparkles size={16} />
            {create.isPending
              ? "Queueing…"
              : `Queue ${modes[mode].toLowerCase()}`}
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
              GPU discovery is unavailable. The worker will verify the runner
              before execution.
            </p>
          )}
          <p className="muted">
            Jobs use the configured native pipeline and installed models.
            Missing models fail with an inspectable error; downloads are
            disabled.
          </p>
          <p className="muted">
            Follow progress, logs and cancellation in Runs. Completed images
            appear in Library.
          </p>
        </aside>
      </form>
    </>
  );
}
