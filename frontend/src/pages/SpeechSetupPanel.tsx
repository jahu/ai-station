import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  AudioLines,
  ArrowRight,
  Check,
  Download,
  RotateCcw,
  Square,
  Film,
} from "lucide-react";
import { api, type Run } from "../api";
import { Badge, ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";
import { randomId } from "../lib/random-id";

type Family = "speech" | "music" | "video";
const profiles = {
  speech: "chatterbox-v3-linux-x86-64-python312-v1",
  music: "ace-step15-turbo-linux-x86-64-python312-v1",
  video: "wan22-5b-linux-x86-64-python312-v1",
};
const destination = (family: Family) =>
  family === "video"
    ? "/video"
    : family === "music"
      ? "/audio?mode=music"
      : "/audio";
const content = {
  speech: {
    title: "Speech",
    heading: "Speech & voice cloning",
    description:
      "Bring your words to life with a voice recording. Local Polish speech, delivery controls and no cloud account.",
    ready:
      "Add a short voice recording in Audio, enter your text and generate.",
    model: "Chatterbox Multilingual v3",
    open: "Open Audio",
  },
  music: {
    title: "Music",
    heading: "Music & soundtracks",
    description:
      "Turn a description into an instrumental or a song with your own lyrics. Create locally, keep every version.",
    ready:
      "Describe an idea in Music, choose an instrumental or your own lyrics, and create a track.",
    model: "ACE-Step 1.5 Turbo",
    open: "Open Music",
  },
  video: {
    title: "Video",
    heading: "Video & animation",
    description:
      "Bring a scene or your own image to life. Create clips and longer films, with saved versions and progress.",
    ready:
      "Describe a scene or add a first-frame image in Video. Create a clip or plan a longer film in the same saved workspace.",
    model: "Wan 2.2 5B",
    open: "Open Video",
  },
};
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const size = (bytes: number) =>
  bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(2)} GiB`
    : bytes >= 1024 ** 2
      ? `${(bytes / 1024 ** 2).toFixed(1)} MiB`
      : `${Math.max(0, bytes / 1024).toFixed(1)} KiB`;
const post = (body: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
type Catalog = {
  can_prepare: boolean;
  installation_available: boolean;
  installation_notice?: string;
  manifest_sha256: string;
  recipe?: {
    profile: string;
    license_notice: string;
    inputs: { filename: string; kind: string; size_bytes: number }[];
  };
  existing_speech?: { available: boolean; source: string };
  existing_music?: { available: boolean; source: string };
  existing_video?: { available: boolean; source: string };
  recommendation?: { fits: boolean; reason: string };
  storage?: {
    free_bytes: number;
    download_bytes: number;
    required_bytes: number;
    cached_bytes_estimate: number;
  };
  licenses?: { name: string; url: string }[];
};
type Preparation = {
  id: string;
  manifest_sha256: string;
  attempt: number;
  run: Run;
  resume_allowed: boolean;
  progress: {
    phase?: string;
    received_bytes?: number;
    expected_bytes?: number;
    current_file?: string;
    completed_files?: number;
    file_count?: number;
  };
};
const phases: Record<string, string> = {
  downloading_files: "Downloading speech files",
  verifying_files: "Checking cached files",
  files_verified: "Files verified · preparing the speech engine",
  verifying_inputs: "Verifying installation inputs",
  creating_environment: "Preparing the local speech engine",
  installing_dependencies: "Installing the speech engine",
  building_sdk: "Preparing speech and watermark components",
  checking_environment: "Checking the offline installation",
  environment_prepared: "Speech engine prepared",
};

function Attempt({
  value,
  canPrepare,
  refresh,
  family,
  ready,
  available,
  manifest,
}: {
  value: Preparation;
  canPrepare: boolean;
  refresh: () => void;
  family: Family;
  ready: boolean;
  available: boolean;
  manifest?: string;
}) {
  const title = content[family].title;
  const Icon = family === "video" ? Film : AudioLines;
  const familyPhases =
    family === "speech"
      ? phases
      : {
          ...phases,
          downloading_files: `Downloading ${family} files`,
          files_verified: `Files verified · preparing the ${family} engine`,
          creating_environment: `Preparing the local ${family} engine`,
          installing_dependencies: `Installing the ${family} engine`,
          preparing_sdk: `Preparing the ${family} SDK`,
          environment_prepared: `${title} engine prepared`,
        };
  const receipt = useRef<{ run: string; id: string } | null>(null);
  const active = !terminal.has(value.run.status);
  const action = useMutation({
    mutationFn: (kind: "cancel" | "resume") => {
      if (!receipt.current || receipt.current.run !== value.run.id)
        receipt.current = { run: value.run.id, id: randomId() };
      return api(
        `/setup/runtimes/preparations/${value.id}/${kind}`,
        post(
          kind === "resume"
            ? {
                client_request_id: receipt.current.id,
                expected_run_id: value.run.id,
              }
            : {},
        ),
      );
    },
    onSuccess: refresh,
  });
  const downloading = ["downloading_files", "verifying_files"].includes(
    value.progress.phase ?? "",
  );
  const total = value.progress.expected_bytes ?? 0;
  const received = Math.max(
    0,
    Math.min(total, value.progress.received_bytes ?? 0),
  );
  const label =
    value.run.status === "succeeded"
      ? ready
        ? family === "video"
          ? "Ready for your first film"
          : family === "music"
            ? "Ready for your first track"
            : "Ready for your first recording"
        : "Installation prepared"
      : value.run.status === "queued"
        ? "Waiting for available resources"
        : value.run.status === "cancel_requested"
          ? "Stopping safely…"
          : value.run.status === "canceled"
            ? "Stopped · downloaded files are kept"
            : active
              ? (familyPhases[value.progress.phase ?? ""] ??
                `Preparing ${family}`)
              : "Preparation needs attention";
  return (
    <article
      className="setup-runtime-attempt"
      aria-label={`${title} preparation ${value.id.slice(0, 8)}`}
    >
      <div className="row spread">
        <strong>{label}</strong>
        <Badge status={value.run.status} />
      </div>
      {active && (
        <>
          {downloading && total > 0 ? (
            <progress
              aria-label={`${title} files progress`}
              value={received}
              max={total}
            />
          ) : (
            <progress aria-label={`${title} engine preparation`} />
          )}
          <p className="muted setup-small" role="status">
            {downloading
              ? `${size(received)} of ${size(total)} · ${value.progress.current_file ?? "verified local files"}`
              : "This can take a few minutes. You can leave this page; preparation keeps running."}
          </p>
        </>
      )}
      {!active && value.run.error_message && (
        <p className="notice">{value.run.error_message}</p>
      )}
      <ErrorNotice error={action.error} />
      <div className="row speech-setup-actions">
        {canPrepare && active && (
          <Button
            variant="secondary"
            disabled={
              action.isPending || value.run.status === "cancel_requested"
            }
            onClick={() => action.mutate("cancel")}
          >
            <Square size={14} /> Stop {family} setup
          </Button>
        )}
        {canPrepare && value.resume_allowed && (
          <Button
            variant="secondary"
            disabled={
              action.isPending ||
              !available ||
              value.manifest_sha256 !== manifest
            }
            onClick={() => action.mutate("resume")}
          >
            <RotateCcw size={15} /> Resume {family} setup
          </Button>
        )}
        {value.run.status === "succeeded" && ready && (
          <Button asChild>
            <Link to={destination(family)}>
              <Icon size={16} /> Create {family}
            </Link>
          </Button>
        )}
        <Link className="text-link" to={`/runs/${value.run.id}`}>
          View details
        </Link>
        <small className="muted">
          Attempt {value.attempt} ·{" "}
          {new Date(value.run.created_at).toLocaleString()}
        </small>
      </div>
    </article>
  );
}

export default function SpeechSetupPanel() {
  return <EnvironmentSetupPanel family="speech" />;
}

export function EnvironmentSetupPanel({ family }: { family: Family }) {
  const profile = profiles[family];
  const title = content[family].title;
  const Icon = family === "video" ? Film : AudioLines;
  const [search] = useSearchParams();
  const [opened, setExpanded] = useState(false);
  const expanded = opened || search.get("capability") === family;
  const cache = useQueryClient();
  const catalog = useQuery({
    queryKey: [`${family}-setup-catalog`],
    queryFn: () => api<Catalog>(`/setup/runtimes?profile=${profile}`),
    enabled: expanded,
  });
  const history = useQuery({
    queryKey: [`${family}-preparations`],
    queryFn: () =>
      api<Preparation[]>(`/setup/runtimes/preparations?profile=${profile}`),
    enabled: expanded,
    refetchInterval: (query) =>
      query.state.data?.some((row) => !terminal.has(row.run.status))
        ? 1000
        : false,
  });
  const data = catalog.data;
  const token = useRef<{ hash: string; id: string } | null>(null);
  const [accepted, setAccepted] = useState("");
  const [showManaged, setShowManaged] = useState(false);
  const completed = useRef(new Set<string>());
  const section = useRef<HTMLElement>(null);
  useEffect(() => {
    if (expanded && search.get("capability") === family)
      section.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [expanded, search, family]);
  const refresh = () => {
    void cache.invalidateQueries({ queryKey: [`${family}-preparations`] });
    void cache.invalidateQueries({ queryKey: [`${family}-setup-catalog`] });
    void cache.invalidateQueries({ queryKey: [`${family}-capabilities`] });
  };
  useEffect(() => {
    for (const row of history.data ?? [])
      if (
        row.run.status === "succeeded" &&
        !completed.current.has(row.run.id)
      ) {
        completed.current.add(row.run.id);
        void cache.invalidateQueries({ queryKey: [`${family}-setup-catalog`] });
        void cache.invalidateQueries({ queryKey: [`${family}-capabilities`] });
        void cache.invalidateQueries({ queryKey: ["models"] });
      }
  }, [history.data, cache, family]);
  const prepare = useMutation({
    mutationFn: () => {
      if (!data?.recipe || accepted !== data.manifest_sha256)
        throw new Error("Review the model and component licenses first.");
      if (!token.current || token.current.hash !== data.manifest_sha256)
        token.current = { hash: data.manifest_sha256, id: randomId() };
      return api(
        "/setup/runtimes",
        post({
          client_request_id: token.current.id,
          profile,
          manifest_sha256: data.manifest_sha256,
          license_accepted: true,
        }),
      );
    },
    onSuccess: refresh,
  });
  const existing = history.data?.find(
    (row) =>
      !terminal.has(row.run.status) ||
      (row.resume_allowed && row.manifest_sha256 === data?.manifest_sha256),
  );
  const existingRuntime =
    family === "video"
      ? data?.existing_video
      : family === "music"
        ? data?.existing_music
        : data?.existing_speech;
  const ready = existingRuntime?.available === true;
  const storageFits =
    !data?.storage || data.storage.free_bytes >= data.storage.required_bytes;
  return (
    <section
      className={`panel setup-runtime setup-${family}`}
      aria-label={`Local ${family} setup`}
      ref={section}
    >
      <div className="speech-setup-heading">
        <div className="speech-setup-icon">
          <Icon size={24} />
        </div>
        <div>
          <h2>{content[family].heading}</h2>
          <p className="muted">{content[family].description}</p>
        </div>
        {ready && (
          <span className="setup-fit">
            <Check size={14} /> Ready
          </span>
        )}
      </div>
      {!expanded ? (
        <Button variant="secondary" onClick={() => setExpanded(true)}>
          Set up {family} <ArrowRight size={15} />
        </Button>
      ) : (
        <>
          <ErrorNotice
            error={catalog.error ?? history.error ?? prepare.error}
          />
          {catalog.isPending ? (
            <Loading />
          ) : !data?.recipe ? (
            <p className="notice">
              {title} setup could not be inspected.{" "}
              <Link to="/system">Open Diagnostics</Link>
            </p>
          ) : (
            <>
              {ready && (
                <div className="speech-setup-ready">
                  <p>
                    <strong>Your {family} engine is ready.</strong>{" "}
                    {content[family].ready}
                  </p>
                  <Button asChild>
                    <Link to={destination(family)}>
                      {content[family].open} <ArrowRight size={15} />
                    </Link>
                  </Button>
                  {existingRuntime?.source === "configured" && (
                    <button
                      className="text-link"
                      type="button"
                      onClick={() => setShowManaged(!showManaged)}
                    >
                      {showManaged
                        ? "Hide managed installation"
                        : "Advanced: install a managed copy"}
                    </button>
                  )}
                </div>
              )}
              {(!ready || showManaged) && (
                <>
                  <div className="speech-setup-facts">
                    <div>
                      <small>MODEL</small>
                      <strong>{content[family].model}</strong>
                    </div>
                    <div>
                      <small>DOWNLOAD</small>
                      <strong>
                        {size(
                          data.storage?.download_bytes ??
                            data.recipe.inputs.reduce(
                              (sum, item) => sum + item.size_bytes,
                              0,
                            ),
                        )}
                      </strong>
                    </div>
                    <div>
                      <small>HARDWARE</small>
                      <strong>
                        One NVIDIA GPU · {family === "speech" ? "6" : "12"} GiB
                        VRAM
                      </strong>
                    </div>
                  </div>
                  <p className="muted setup-small">
                    {data.recommendation?.reason ??
                      "Compatibility is checked on your workstation before installation."}{" "}
                    {data.storage &&
                      `${size(data.storage.free_bytes)} free · ${size(data.storage.required_bytes)} needed during setup. Cached files are checked and reused.`}
                  </p>
                  {family === "music" && (
                    <p className="muted setup-small">
                      This profile offloads parts of the model to CPU: short
                      tracks reserve 12 GiB RAM, tracks over a minute reserve 18
                      GiB. Model weights and lyrics remain local.
                    </p>
                  )}
                  {family === "video" && (
                    <p className="muted setup-small">
                      This profile uses CPU offload within 11 GiB RAM. Its
                      landscape format is 1280 × 704 with at least 20 steps.
                      Longer films retain their own saved progress and versions.
                    </p>
                  )}
                  {ready && (
                    <p className="notice">
                      Your configured {family} integration keeps its settings.
                      This prepares an additional managed copy.
                    </p>
                  )}
                  <details className="speech-setup-sources">
                    <summary>Sources, licenses and download details</summary>
                    <p className="setup-small muted">
                      {data.recipe.license_notice ??
                        "Models, runtime and bundled components retain their individual licenses. Review the sources before installation."}
                    </p>
                    <div className="speech-setup-license-links">
                      {data.licenses?.map((item) => (
                        <a
                          key={item.url}
                          href={item.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {item.name}
                        </a>
                      ))}
                    </div>
                    <ul>
                      {data.recipe.inputs.map((item) => (
                        <li key={item.filename}>
                          <span>{item.filename}</span>
                          <small className="muted">
                            {item.kind} · {size(item.size_bytes)}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </details>
                  {!data.can_prepare ? (
                    <p className="notice">
                      Your administrator can install shared models. Your
                      recordings, prompts and generated results stay private.
                    </p>
                  ) : (
                    !existing && (
                      <>
                        {!data.installation_available && (
                          <p className="notice">
                            {data.installation_notice ??
                              `This ${family} profile is not available on this workstation.`}{" "}
                            <Link to="/system">View Diagnostics</Link>
                          </p>
                        )}
                        {!storageFits && (
                          <p className="notice">
                            More free storage is needed before {family} setup
                            can begin.
                          </p>
                        )}
                        <label className="setup-license">
                          <input
                            type="checkbox"
                            checked={accepted === data.manifest_sha256}
                            onChange={(event) =>
                              setAccepted(
                                event.target.checked
                                  ? data.manifest_sha256
                                  : "",
                              )
                            }
                            disabled={
                              !data.installation_available || prepare.isPending
                            }
                          />
                          <span>
                            I have reviewed the {family} model and bundled
                            component licenses.
                          </span>
                        </label>
                        <Button
                          disabled={
                            !data.installation_available ||
                            !storageFits ||
                            accepted !== data.manifest_sha256 ||
                            prepare.isPending
                          }
                          onClick={() => prepare.mutate()}
                        >
                          <Download size={16} />{" "}
                          {prepare.isPending
                            ? `Starting ${family} setup…`
                            : `Download & set up ${family}`}
                        </Button>
                      </>
                    )
                  )}
                </>
              )}
            </>
          )}
          {history.data?.map((value) => (
            <Attempt
              key={value.id}
              value={value}
              canPrepare={data?.can_prepare ?? false}
              refresh={refresh}
              family={family}
              ready={ready}
              available={data?.installation_available ?? false}
              manifest={data?.manifest_sha256}
            />
          ))}
        </>
      )}
    </section>
  );
}
