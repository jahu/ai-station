import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { AudioLines, Settings2, Sparkles } from "lucide-react";
import { api, useHardware, type Run } from "../api";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import MediaInput from "../components/media/MediaInput";
import MediaResult from "../components/media/MediaResult";
import { mediaBusy, useMediaRun } from "../components/media/media-run";

export default function Audio() {
  const [search, setSearch] = useSearchParams();
  const cache = useQueryClient();
  const [reference, setReference] = useState(search.get("input") ?? "");
  const [text, setText] = useState("");
  const [gpu, setGpu] = useState("auto");
  const [uploading, setUploading] = useState(false);
  const hardware = useHardware();
  const runId = search.get("run") ?? "";
  const run = useMediaRun(runId);
  const generate = useMutation({
    mutationFn: () =>
      api<Run>("/audio/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, gpu, reference_artifact_id: reference }),
      }),
    onSuccess: (result) => {
      cache.setQueryData(["run", result.id], result);
      setSearch({ run: result.id });
    },
  });
  const busy = generate.isPending || mediaBusy(run.data);
  return (
    <>
      <PageTitle
        eyebrow="CREATE / AUDIO"
        title="Give your words a voice."
        action={
          <span className="media-runtime">
            <i />
            Chatterbox · Local
          </span>
        }
      >
        Natural Polish speech, shaped by your voice reference. Listen and refine
        right here.
      </PageTitle>
      <div className="media-workspace">
        <form
          className="panel media-composer"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy && !uploading) generate.mutate();
          }}
        >
          <div className="media-composer-heading">
            <AudioLines size={20} />
            <h2>Create speech</h2>
            <span>01 / Voice & text</span>
          </div>
          <fieldset disabled={uploading || busy}>
            <MediaInput
              kind="audio"
              label="Voice reference"
              hint="WAV · 0.1–60 sec · up to 20 MB"
              value={reference}
              onChange={setReference}
              disabled={uploading || busy}
              onBusy={setUploading}
            />
            <label className="media-text-label">
              <span>
                Text to speak <small>{text.length} / 1000</small>
              </span>
              <textarea
                aria-label="Text to speak"
                required
                maxLength={1000}
                rows={6}
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder="Write the words you want to hear…"
              />
            </label>
            <details className="media-advanced">
              <summary>
                <Settings2 size={15} />
                Advanced settings<span>GPU</span>
              </summary>
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
              <ErrorNotice error={hardware.error} />
            </details>
            <ErrorNotice error={generate.error} />
            <Button
              type="submit"
              className="media-generate"
              disabled={!reference || !text.trim() || uploading || busy}
            >
              <Sparkles size={17} />
              {busy ? "Generating speech…" : "Generate speech"}
            </Button>
            <p className="media-privacy">
              Your voice and text stay on this workstation.
            </p>
          </fieldset>
        </form>
        <MediaResult
          kind="audio"
          runId={runId}
          run={run.data}
          error={run.error}
        />
      </div>
    </>
  );
}
