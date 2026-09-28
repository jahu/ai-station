import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, useHardware, type Artifact, type Run } from "../api";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";

export default function Avatars({ video = false }: { video?: boolean }) {
  const navigate = useNavigate();
  const [image, setImage] = useState("");
  const [audio, setAudio] = useState("");
  const [prompt, setPrompt] = useState(
    "A person speaking naturally, static camera.",
  );
  const [size, setSize] = useState(384);
  const [frames, setFrames] = useState(81);
  const [steps, setSteps] = useState(8);
  const [seed, setSeed] = useState(43);
  const [gpu, setGpu] = useState("auto");
  const hardware = useHardware();
  const library = useQuery({
    queryKey: ["avatar-inputs"],
    queryFn: () => api<Artifact[]>("/artifacts"),
  });
  const upload = useMutation({
    mutationFn: async ({
      file,
      kind,
    }: {
      file: File;
      kind: "image" | "audio";
    }) => {
      const body = new FormData();
      body.append("file", file);
      const artifact = await api<Artifact>(
        kind === "image" ? "/images/uploads" : "/audio/uploads",
        { method: "POST", body },
      );
      return { artifact, kind };
    },
    onSuccess: ({ artifact, kind }) => {
      if (kind === "image") setImage(artifact.id);
      else setAudio(artifact.id);
      void library.refetch();
    },
  });
  const generate = useMutation({
    mutationFn: () =>
      api<Run>("/avatars/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_artifact_id: image,
          audio_artifact_id: audio,
          prompt,
          size,
          frames,
          steps,
          seed,
          gpu,
        }),
      }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });
  return (
    <>
      <PageTitle
        eyebrow={video ? "CREATE / LOCAL VIDEO" : "CREATE / LOCAL AVATARS"}
        title="Bring a portrait to life."
      >
        EchoMimic animates a portrait using your speech recording. Create a
        short MP4 with synchronized audio, entirely on your workstation.
      </PageTitle>
      <ErrorNotice
        error={
          upload.error ?? generate.error ?? library.error ?? hardware.error
        }
      />
      <form
        className="panel content-panel"
        onSubmit={(event) => {
          event.preventDefault();
          generate.mutate();
        }}
      >
        <fieldset disabled={upload.isPending || generate.isPending}>
          {(["image", "audio"] as const).map((kind) => (
            <div key={kind} className="content-panel">
              <label>
                {kind === "image"
                  ? "Portrait from Library"
                  : "Speech from Library"}
                <select
                  value={kind === "image" ? image : audio}
                  onChange={(event) =>
                    (kind === "image" ? setImage : setAudio)(event.target.value)
                  }
                >
                  <option value="">
                    Choose {kind === "image" ? "a portrait" : "a WAV recording"}
                  </option>
                  {library.data
                    ?.filter((a) => a.type === kind)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.original_filename || a.id}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                {kind === "image" ? "Upload portrait" : "Upload speech"}
                <input
                  type="file"
                  accept={
                    kind === "image" ? "image/png,image/jpeg" : "audio/wav,.wav"
                  }
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) upload.mutate({ file, kind });
                  }}
                />
              </label>
              {kind === "image" && image && (
                <img
                  src={`/api/artifacts/${image}/thumbnail`}
                  alt="Portrait preview"
                  style={{ maxWidth: 256, maxHeight: 256 }}
                />
              )}
              {kind === "audio" && audio && (
                <audio
                  controls
                  preload="metadata"
                  src={`/api/artifacts/${audio}/file`}
                  aria-label="Speech preview"
                />
              )}
            </div>
          ))}
          <label>
            Scene and motion
            <textarea
              required
              maxLength={2000}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
            />
          </label>
          <label>
            Resolution
            <select
              aria-label="Resolution"
              value={size}
              onChange={(event) => setSize(Number(event.target.value))}
            >
              {[256, 384, 512].map((n) => (
                <option key={n} value={n}>
                  {n} × {n} area · preserves aspect ratio
                </option>
              ))}
            </select>
          </label>
          <label>
            Maximum duration
            <select
              aria-label="Maximum duration"
              value={frames}
              onChange={(event) => setFrames(Number(event.target.value))}
            >
              {[17, 33, 49, 65, 81].map((n) => (
                <option key={n} value={n}>
                  {(n / 25).toFixed(2)} seconds
                </option>
              ))}
            </select>
          </label>
          <label>
            Steps
            <input
              type="number"
              min={4}
              max={30}
              value={steps}
              onChange={(event) => setSteps(Number(event.target.value))}
            />
          </label>
          <label>
            Seed
            <input
              type="number"
              min={0}
              max={2147483647}
              value={seed}
              onChange={(event) => setSeed(Number(event.target.value))}
            />
          </label>
          <label>
            GPU
            <select
              value={gpu}
              onChange={(event) => setGpu(event.target.value)}
            >
              <option value="auto">Auto · available GPU</option>
              {hardware.data?.gpus.map((device) => (
                <option key={device.index} value={device.index}>
                  GPU {device.index} · {device.name}
                </option>
              ))}
            </select>
          </label>
          <p className="muted">
            Use a clear portrait and 0.68–60 seconds of PCM WAV speech. The clip
            uses the start of your recording, capped at the selected duration.
            Follow progress or cancel in Runs; the result appears in Library.
          </p>
          <Button
            type="submit"
            disabled={
              !image ||
              !audio ||
              !prompt.trim() ||
              upload.isPending ||
              generate.isPending
            }
          >
            Generate avatar video
          </Button>
        </fieldset>
      </form>
    </>
  );
}
