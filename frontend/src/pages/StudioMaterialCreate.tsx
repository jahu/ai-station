import { useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Clapperboard } from "lucide-react";
import { api } from "../api";
import { useAccount } from "../account-context";
import { ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import {
  creativeJson,
  initialDefinition,
  type CreativeDefaults,
  type CreativeProject,
} from "../components/creative/creative-project";
import { randomId } from "../lib/random-id";
import { useCreativeEntry } from "../components/creative/useCreativeEntry";
import {
  audioNames,
  formatNames,
  materialBase,
  type StudioMaterial,
  type StudioOptions,
} from "./studio-material";
import "./Studio.css";
import "./StudioMaterial.css";

export default function StudioMaterialCreate() {
  const [query] = useSearchParams();
  const { user } = useAccount();
  const projectId = query.get("project");
  const project = useQuery({
    queryKey: ["creative-project", user?.id, projectId],
    enabled: !!projectId,
    queryFn: ({ signal }) =>
      api<CreativeProject>(`/creative/projects/${projectId}`, { signal }),
  });
  if (projectId && project.isPending) return <Loading />;
  if (projectId && project.error) return <ErrorNotice error={project.error} />;
  return <CreateForm key={projectId ?? "standalone"} project={project.data} />;
}

function CreateForm({ project }: { project?: CreativeProject }) {
  useCreativeEntry(project?.id);
  const navigate = useNavigate();
  const [brief, setBrief] = useState("");
  const [title, setTitle] = useState("");
  const [options, setOptions] = useState<StudioOptions>(
    project?.defaults ?? initialDefinition().defaults,
  );
  const receipt = useRef<{ fingerprint: string; id: string } | null>(null);
  const create = useMutation({
    mutationFn: (body: unknown) =>
      api<StudioMaterial>(materialBase, creativeJson("POST", body)),
    onSuccess: (row) => navigate(`/studio/materials/${row.id}`),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    const body = {
      title: title.trim() || brief.trim().slice(0, 80),
      brief: brief.trim(),
      creative_project_id: project?.id ?? null,
      options,
    };
    const fingerprint = JSON.stringify(body);
    if (receipt.current?.fingerprint !== fingerprint)
      receipt.current = { fingerprint, id: randomId() };
    create.mutate({ ...body, client_request_id: receipt.current.id });
  }
  return (
    <div className="studio studio-material-create">
      <Link
        className="studio-back"
        to={project ? `/studio/${project.id}` : "/studio"}
      >
        <ArrowLeft size={15} />
        {project?.name ?? "Studio"}
      </Link>
      <PageTitle eyebrow="STUDIO / NEW MATERIAL" title="What's the story?">
        {project
          ? `A new material for ${project.name}. Its visual identity and editorial direction stay with your project.`
          : "A standalone idea, with a home for its script, shots and versions."}
      </PageTitle>
      <form onSubmit={submit} className="panel studio-material-brief">
        <Clapperboard size={30} className="studio-material-emblem" />
        <label>
          Your brief
          <textarea
            required
            rows={6}
            value={brief}
            maxLength={12000}
            placeholder="What should the audience see, feel and take away? Describe the story, the look and the sound you have in mind."
            onChange={(e) => setBrief(e.target.value)}
          />
        </label>
        <label>
          Working title <span className="muted">optional</span>
          <input
            value={title}
            maxLength={160}
            placeholder="Give this story a name"
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <MaterialOptions value={options} onChange={setOptions} />
        <ErrorNotice error={create.error} />
        <div className="studio-material-submit">
          <span>Your first step is an editable storyboard.</span>
          <Button
            disabled={
              create.isPending || !brief.trim() || !!project?.archived_at
            }
            type="submit"
          >
            {create.isPending ? "Creating…" : "Create material"}
            <ArrowRight size={16} />
          </Button>
        </div>
      </form>
    </div>
  );
}

export function MaterialOptions({
  value,
  onChange,
  disabled = false,
}: {
  value: StudioOptions;
  onChange: (value: StudioOptions) => void;
  disabled?: boolean;
}) {
  function changeWords(key: "minimum" | "maximum", text: string) {
    const limits = { ...value.narration_words };
    if (text === "") delete limits[key];
    else limits[key] = Number(text);
    onChange({
      ...value,
      narration_words: Object.keys(limits).length ? limits : undefined,
    });
  }
  return (
    <fieldset className="studio-material-options" disabled={disabled}>
      <legend>The shape of your story</legend>
      <label>
        Format
        <select
          value={value.format}
          onChange={(e) =>
            onChange({
              ...value,
              format: e.target.value as CreativeDefaults["format"],
            })
          }
        >
          {Object.entries(formatNames).map(([key, name]) => (
            <option key={key} value={key}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Canvas
        <select
          value={value.aspect}
          onChange={(e) =>
            onChange({
              ...value,
              aspect: e.target.value as CreativeDefaults["aspect"],
            })
          }
        >
          <option value="portrait">Portrait · 9:16</option>
          <option value="landscape">Widescreen · 16:9</option>
          <option value="square">Square · 1:1</option>
        </select>
      </label>
      <label>
        Target length · seconds
        <input
          type="number"
          min={5}
          max={600}
          required
          value={value.duration_seconds}
          onChange={(e) =>
            onChange({ ...value, duration_seconds: Number(e.target.value) })
          }
        />
      </label>
      <label>
        Sound
        <select
          value={value.audio}
          onChange={(e) => {
            const audio = e.target.value as CreativeDefaults["audio"];
            onChange({
              ...value,
              audio,
              narration_words: ["voice", "voice_music"].includes(audio)
                ? value.narration_words
                : undefined,
            });
          }}
        >
          {Object.entries(audioNames).map(([key, name]) => (
            <option key={key} value={key}>
              {name}
            </option>
          ))}
        </select>
      </label>
      {["voice", "voice_music"].includes(value.audio) && (
        <details
          className="studio-script-limits"
          open={!!value.narration_words || undefined}
        >
          <summary>
            Narration length <small>Optional</small>
          </summary>
          <p>
            Set a spoken word target when you need one. Leave both fields empty
            for a freely paced script.
          </p>
          <div className="studio-script-limits-fields">
            <label>
              Minimum spoken words
              <input
                type="number"
                min={1}
                max={value.narration_words?.maximum ?? 3000}
                step={1}
                value={value.narration_words?.minimum ?? ""}
                onChange={(e) => changeWords("minimum", e.target.value)}
              />
            </label>
            <label>
              Maximum spoken words
              <input
                type="number"
                min={value.narration_words?.minimum ?? 1}
                max={3000}
                step={1}
                value={value.narration_words?.maximum ?? ""}
                onChange={(e) => changeWords("maximum", e.target.value)}
              />
            </label>
          </div>
          {value.narration_words && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => onChange({ ...value, narration_words: undefined })}
            >
              Clear word limits
            </Button>
          )}
        </details>
      )}
    </fieldset>
  );
}
