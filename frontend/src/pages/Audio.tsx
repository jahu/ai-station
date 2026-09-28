import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, useHardware, type Artifact, type Run } from "../api";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";

export default function Audio() {
  const [search] = useSearchParams();
  const [reference, setReference] = useState(search.get("input") ?? "");
  const [text, setText] = useState("");
  const [gpu, setGpu] = useState("auto");
  const hardware = useHardware();
  const navigate = useNavigate();
  const source = useQuery({
    queryKey: ["artifact", reference],
    queryFn: () => api<Artifact>(`/artifacts/${reference}`),
    enabled: Boolean(reference),
  });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return api<Artifact>("/audio/uploads", { method: "POST", body });
    },
    onSuccess: (artifact) => setReference(artifact.id),
  });
  const generate = useMutation({
    mutationFn: () =>
      api<Run>("/audio/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, gpu, reference_artifact_id: reference }),
      }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });
  return (
    <>
      <PageTitle
        eyebrow="CREATE / LOCAL SPEECH"
        title="Give your words a voice."
      >
        Polish speech with Chatterbox, using a short voice reference. Audio
        stays on your workstation.
      </PageTitle>
      <ErrorNotice
        error={upload.error ?? generate.error ?? source.error ?? hardware.error}
      />
      <form
        className="panel content-panel"
        onSubmit={(event) => {
          event.preventDefault();
          generate.mutate();
        }}
      >
        <fieldset disabled={upload.isPending || generate.isPending}>
          <label>
            Voice reference · WAV
            <input
              type="file"
              accept="audio/wav,.wav"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) upload.mutate(file);
              }}
            />
          </label>
          <p className="muted">
            Use a clear mono or stereo recording, 0.1–60 seconds, up to 20 MiB.
          </p>
          {source.data && (
            <div className="content-panel">
              <strong>{source.data.original_filename}</strong>
              <audio
                controls
                preload="metadata"
                src={`/api/artifacts/${source.data.id}/file`}
                aria-label="Voice reference preview"
              />
              <Button
                type="button"
                variant="secondary"
                onClick={() => setReference("")}
              >
                Remove reference
              </Button>
            </div>
          )}
          <label>
            Text to speak
            <textarea
              required
              maxLength={1000}
              rows={6}
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Witaj w AI Station."
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
            Generation appears in Runs with live logs and cancellation. The
            resulting WAV is saved in your Library with its reference and text.
          </p>
          <Button
            type="submit"
            disabled={
              !reference ||
              !text.trim() ||
              upload.isPending ||
              generate.isPending
            }
          >
            Generate speech
          </Button>
        </fieldset>
      </form>
    </>
  );
}
