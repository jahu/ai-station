import { useState, type CSSProperties, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowUpRight,
  Archive,
  Check,
  Clapperboard,
  Layers,
  Plus,
  RotateCcw,
} from "lucide-react";
import { api } from "../api";
import { useAccount } from "../account-context";
import { Empty, ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import type { CreativeSession } from "../components/creative/creative-context";
import {
  creativeJson,
  initialDefinition,
  type CreativeDefinition,
  type CreativeProject,
} from "../components/creative/creative-project";
import "./Studio.css";
import "./StudioMaterial.css";
import StudioMaterials from "./StudioMaterials";
import { useCreativeEntry as useStudioEntry } from "../components/creative/useCreativeEntry";

const projectUrl = "/creative/projects";
const font = {
  sans: "Inter, system-ui, sans-serif",
  humanist: "'Trebuchet MS', sans-serif",
  editorial: "Georgia, serif",
  mono: "monospace",
};
const format = {
  reel: "Social reel",
  presentation: "Presentation",
  film: "Film",
};
const audio = {
  voice_music: "Voice + music",
  voice: "Voiceover",
  music: "Music",
  silent: "No audio",
};
const date = (value: string) =>
  new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });

function Swatches({ colors }: { colors: string[] }) {
  return (
    <span className="studio-swatches" aria-label="Project palette">
      {colors.map((color, i) => (
        <i key={i} style={{ background: color }} title={color} />
      ))}
    </span>
  );
}

export function Studio() {
  useStudioEntry();
  const { user } = useAccount();
  const [archived, setArchived] = useState(false);
  const projects = useInfiniteQuery({
    queryKey: ["creative-projects", user?.id, archived],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      api<CreativeProject[]>(
        `${projectUrl}?archived=${archived}&limit=50&offset=${pageParam}`,
        { signal },
      ),
    getNextPageParam: (last, pages) =>
      last.length === 50
        ? pages.reduce((count, page) => count + page.length, 0)
        : undefined,
  });
  const rows = projects.data?.pages.flat() ?? [];
  return (
    <div className="studio">
      <PageTitle
        eyebrow="CREATE / STUDIO"
        title="A home for every creative direction"
        action={
          <Button asChild>
            <Link to="/studio/new">
              <Plus size={16} /> New project
            </Link>
          </Button>
        }
      >
        Keep a brand, a course or a series together. Give each project its own
        visual identity and voice.
      </PageTitle>
      <StudioMaterials />
      <div className="studio-toolbar">
        <div className="mode-tabs" aria-label="Creative project status">
          <button
            type="button"
            className={!archived ? "active" : ""}
            aria-pressed={!archived}
            onClick={() => setArchived(false)}
          >
            Your projects
          </button>
          <button
            type="button"
            className={archived ? "active" : ""}
            aria-pressed={archived}
            onClick={() => setArchived(true)}
          >
            Archived
          </button>
        </div>
        <span>One identity. Many stories.</span>
      </div>
      <ErrorNotice error={projects.error} />
      {projects.isPending ? (
        <Loading />
      ) : rows.length ? (
        <>
          <div className="studio-grid">
            {rows.map((project) => (
              <Link
                className="studio-project"
                key={project.id}
                to={`/studio/${project.id}`}
              >
                <div
                  className="studio-project-cover"
                  style={{
                    background: project.identity.colors[1] ?? "#171b1b",
                    color: project.identity.colors[0] ?? "#A8CC74",
                    fontFamily: font[project.identity.typography],
                  }}
                >
                  <span className="studio-project-mark">
                    {project.name.slice(0, 2).toLocaleUpperCase()}
                  </span>
                  <span className="studio-cover-kind">
                    <Clapperboard size={14} /> {format[project.defaults.format]}
                  </span>
                  <span className="studio-cover-line" aria-hidden="true" />
                </div>
                <div className="studio-project-body">
                  <div className="studio-project-title">
                    <h2>{project.name}</h2>
                    <ArrowUpRight size={18} />
                  </div>
                  <p>
                    {project.description ||
                      "A space for your next creative direction."}
                  </p>
                  <div className="studio-project-footer">
                    <Swatches colors={project.identity.colors} />
                    <span>Updated {date(project.updated_at)}</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
          {projects.hasNextPage && (
            <Button
              variant="secondary"
              disabled={projects.isFetchingNextPage}
              onClick={() => void projects.fetchNextPage()}
            >
              {projects.isFetchingNextPage ? "Loading…" : "Show more projects"}
            </Button>
          )}
        </>
      ) : (
        !projects.error && (
          <section className="panel studio-empty">
            <Layers size={34} />
            <h2>
              {archived
                ? "Your archived projects will stay here"
                : "Start with a world of your own"}
            </h2>
            <p>
              {archived
                ? "Archiving keeps your identity, saved work and history. Restore a project whenever you need it."
                : "A learning platform. Your personal brand. A new series. Save the look, audience and tone once, then keep related work in one place."}
            </p>
            {!archived && (
              <Button asChild>
                <Link to="/studio/new">
                  <Plus size={16} /> Create your first project
                </Link>
              </Button>
            )}
          </section>
        )
      )}
    </div>
  );
}

export function StudioProject({ create = false }: { create?: boolean }) {
  const { id } = useParams();
  const { user } = useAccount();
  const project = useQuery({
    queryKey: ["creative-project", user?.id, id],
    queryFn: ({ signal }) =>
      api<CreativeProject>(`${projectUrl}/${id}`, { signal }),
    enabled: !create && !!id,
  });
  if (!create && project.isPending) return <Loading />;
  if (!create && project.error) return <ErrorNotice error={project.error} />;
  return <ProjectEditor key={create ? "new" : id} project={project.data} />;
}

function ProjectEditor({ project }: { project?: CreativeProject }) {
  useStudioEntry();
  const { user } = useAccount();
  const cache = useQueryClient();
  const navigate = useNavigate();
  const [definition, setDefinition] = useState<CreativeDefinition>(() =>
    project
      ? {
          name: project.name,
          description: project.description,
          aliases: project.aliases,
          identity: structuredClone(project.identity),
          defaults: structuredClone(project.defaults),
          logo_artifact_id: project.logo_artifact_id,
        }
      : initialDefinition(),
  );
  const [aliases, setAliases] = useState(project?.aliases.join(", ") ?? "");
  const [saved, setSaved] = useState(false);
  const materials = useQuery({
    queryKey: ["creative-project-work", user?.id, project?.id],
    queryFn: ({ signal }) =>
      api<CreativeSession[]>(
        `/creative/sessions?creative_project_id=${project?.id}&limit=100`,
        { signal },
      ),
    enabled: !!project,
  });
  const save = useMutation({
    mutationFn: () =>
      api<CreativeProject>(
        project ? `${projectUrl}/${project.id}` : projectUrl,
        creativeJson(project ? "PUT" : "POST", {
          ...definition,
          aliases: aliases
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean),
          ...(project ? { expected_version: project.version } : {}),
        }),
      ),
    onSuccess: (next) => {
      cache.setQueryData(["creative-project", user?.id, next.id], next);
      void cache.invalidateQueries({
        queryKey: ["creative-projects", user?.id],
      });
      setSaved(true);
      if (!project) navigate(`/studio/${next.id}`, { replace: true });
    },
  });
  const archive = useMutation({
    mutationFn: () =>
      api<CreativeProject>(
        `${projectUrl}/${project?.id}/archive`,
        creativeJson("PATCH", {
          expected_version: project?.version,
          archived: !project?.archived_at,
        }),
      ),
    onSuccess: (next) => {
      cache.setQueryData(["creative-project", user?.id, next.id], next);
      void cache.invalidateQueries({
        queryKey: ["creative-projects", user?.id],
      });
    },
  });
  const busy = save.isPending || archive.isPending;
  const readOnly = !!project?.archived_at;
  function change(value: Partial<CreativeDefinition>) {
    setDefinition((prev) => ({ ...prev, ...value }));
    setSaved(false);
  }
  function identity(
    key: keyof CreativeDefinition["identity"],
    value: string | string[],
  ) {
    change({ identity: { ...definition.identity, [key]: value } });
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!readOnly) save.mutate();
  }
  const palette = definition.identity.colors;
  return (
    <div className="studio">
      <Link to="/studio" className="studio-back">
        <ArrowLeft size={15} /> All creative projects
      </Link>
      <PageTitle
        eyebrow="STUDIO / CREATIVE IDENTITY"
        title={project?.name ?? "A new creative direction"}
        action={
          project && (
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => archive.mutate()}
            >
              {readOnly ? <RotateCcw size={15} /> : <Archive size={15} />}
              {readOnly ? "Restore project" : "Archive"}
            </Button>
          )
        }
      >
        {readOnly
          ? "Archived. Your identity and previous work are preserved."
          : "The shared brief for your materials. Save a clear direction; refine each story separately."}
      </PageTitle>
      <ErrorNotice error={save.error ?? archive.error} />
      {project && (
        <StudioMaterials projectId={project.id} readOnly={readOnly} />
      )}
      <div className="studio-editor-layout">
        <form onSubmit={submit} className="studio-editor">
          <fieldset disabled={busy || readOnly}>
            <section className="panel studio-section">
              <div className="studio-section-label">
                <span>01</span>
                <h2>The project</h2>
              </div>
              <label>
                Project name
                <input
                  required
                  maxLength={160}
                  value={definition.name}
                  placeholder="Your brand, course or series"
                  onChange={(e) => change({ name: e.target.value })}
                />
              </label>
              <label>
                What is this project about?
                <textarea
                  maxLength={4000}
                  rows={3}
                  value={definition.description}
                  placeholder="What you create, why it matters, and what makes it yours."
                  onChange={(e) => change({ description: e.target.value })}
                />
              </label>
              <label>
                Other names or domains
                <input
                  value={aliases}
                  maxLength={4000}
                  placeholder="Your website, an abbreviation, another project name"
                  onChange={(e) => {
                    setAliases(e.target.value);
                    setSaved(false);
                  }}
                />
                <small>
                  Separate with commas. These help recognize the project when
                  you mention it.
                </small>
              </label>
            </section>
            <section className="panel studio-section">
              <div className="studio-section-label">
                <span>02</span>
                <h2>Look & feel</h2>
              </div>
              <div
                className="studio-palette"
                role="group"
                aria-label="Brand colors"
              >
                {palette.map((color, i) => (
                  <label key={i}>
                    <input
                      aria-label={`Brand color ${i + 1}`}
                      type="color"
                      value={color}
                      onChange={(e) =>
                        identity(
                          "colors",
                          palette.map((c, n) =>
                            n === i ? e.target.value.toUpperCase() : c,
                          ),
                        )
                      }
                    />
                    <span>{color}</span>
                    {palette.length > 1 && (
                      <button
                        type="button"
                        aria-label={`Remove brand color ${i + 1}`}
                        onClick={() =>
                          identity(
                            "colors",
                            palette.filter((_, n) => n !== i),
                          )
                        }
                      >
                        Remove
                      </button>
                    )}
                  </label>
                ))}
                {palette.length < 8 && (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => identity("colors", [...palette, "#808080"])}
                  >
                    <Plus size={14} /> Add color
                  </Button>
                )}
              </div>
              <label>
                Typography
                <select
                  value={definition.identity.typography}
                  onChange={(e) => identity("typography", e.target.value)}
                >
                  <option value="sans">Modern sans · clear & versatile</option>
                  <option value="humanist">
                    Humanist · warm & approachable
                  </option>
                  <option value="editorial">
                    Editorial · elegant & thoughtful
                  </option>
                  <option value="mono">Monospace · precise & technical</option>
                </select>
              </label>
              <label>
                Visual direction
                <textarea
                  rows={3}
                  maxLength={4000}
                  value={definition.identity.visual_direction}
                  placeholder="Describe the mood, composition, imagery and motion you want. What should we avoid?"
                  onChange={(e) => identity("visual_direction", e.target.value)}
                />
              </label>
            </section>
            <section className="panel studio-section">
              <div className="studio-section-label">
                <span>03</span>
                <h2>Voice & audience</h2>
              </div>
              <label>
                Who is it for?
                <input
                  maxLength={2000}
                  value={definition.identity.audience}
                  placeholder="Describe your audience"
                  onChange={(e) => identity("audience", e.target.value)}
                />
              </label>
              <label>
                Tone
                <input
                  maxLength={2000}
                  value={definition.identity.tone}
                  placeholder="For example: direct, warm, curious. Explain without jargon."
                  onChange={(e) => identity("tone", e.target.value)}
                />
              </label>
              <label>
                Language
                <input
                  maxLength={80}
                  value={definition.identity.language}
                  placeholder="Use the language of each brief"
                  onChange={(e) => identity("language", e.target.value)}
                />
              </label>
              <label>
                Editorial rules
                <textarea
                  rows={3}
                  maxLength={4000}
                  value={definition.identity.editorial_rules}
                  placeholder="Your recurring messages, preferred wording, calls to action and things to avoid."
                  onChange={(e) => identity("editorial_rules", e.target.value)}
                />
              </label>
              <label>
                Audio direction
                <textarea
                  rows={2}
                  maxLength={2000}
                  value={definition.identity.audio_direction}
                  placeholder="Describe the narration style and soundtrack mood."
                  onChange={(e) => identity("audio_direction", e.target.value)}
                />
              </label>
            </section>
            <details className="panel studio-section">
              <summary>
                Production defaults{" "}
                <small>Each material can override these</small>
              </summary>
              <div className="studio-defaults">
                <label>
                  Material
                  <select
                    value={definition.defaults.format}
                    onChange={(e) => {
                      const value = e.target
                        .value as CreativeDefinition["defaults"]["format"];
                      change({
                        defaults: {
                          ...definition.defaults,
                          format: value,
                          aspect: value === "reel" ? "portrait" : "landscape",
                        },
                      });
                    }}
                  >
                    {Object.entries(format).map(([key, title]) => (
                      <option value={key} key={key}>
                        {title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Canvas
                  <select
                    value={definition.defaults.aspect}
                    onChange={(e) =>
                      change({
                        defaults: {
                          ...definition.defaults,
                          aspect: e.target
                            .value as CreativeDefinition["defaults"]["aspect"],
                        },
                      })
                    }
                  >
                    <option value="portrait">Portrait · 9:16</option>
                    <option value="landscape">Widescreen · 16:9</option>
                    <option value="square">Square · 1:1</option>
                  </select>
                </label>
                <label>
                  Target length (seconds)
                  <input
                    type="number"
                    required
                    min={5}
                    max={600}
                    step={1}
                    value={definition.defaults.duration_seconds}
                    onChange={(e) =>
                      change({
                        defaults: {
                          ...definition.defaults,
                          duration_seconds: e.target.valueAsNumber,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  Audio
                  <select
                    value={definition.defaults.audio}
                    onChange={(e) =>
                      change({
                        defaults: {
                          ...definition.defaults,
                          audio: e.target
                            .value as CreativeDefinition["defaults"]["audio"],
                        },
                      })
                    }
                  >
                    {Object.entries(audio).map(([key, title]) => (
                      <option value={key} key={key}>
                        {title}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </details>
          </fieldset>
          {!readOnly && (
            <div className="studio-save">
              <p aria-live="polite">
                {saved ? (
                  <>
                    <Check size={15} /> Identity saved
                  </>
                ) : project ? (
                  "New work uses the saved identity. Earlier versions stay intact."
                ) : (
                  "Only a name is required. Refine the rest whenever you like."
                )}
              </p>
              <Button type="submit" disabled={busy}>
                {save.isPending
                  ? "Saving…"
                  : project
                    ? "Save identity"
                    : "Create project"}
              </Button>
            </div>
          )}
        </form>
        <aside className="studio-inspector">
          <div
            className="studio-preview"
            style={
              {
                "--studio-accent": palette[0] ?? "#A8CC74",
                background: palette[1] ?? "#101311",
                color: palette[2] ?? "#F7F8F4",
                fontFamily: font[definition.identity.typography],
              } as CSSProperties
            }
          >
            <span className="studio-preview-label">IDENTITY PREVIEW</span>
            <span className="studio-preview-rule" />
            <h2>{definition.name || "Your next chapter"}</h2>
            <p>
              {definition.identity.tone ||
                "A recognizable voice. A consistent world."}
            </p>
            <div className="studio-preview-meta">
              <span>{format[definition.defaults.format]}</span>
              <span>
                {definition.defaults.aspect === "portrait"
                  ? "9:16"
                  : definition.defaults.aspect === "landscape"
                    ? "16:9"
                    : "1:1"}
              </span>
            </div>
          </div>
          <p className="studio-preview-note">
            A style reference, not a rendered material. Your script and scenes
            will have their own layout.
          </p>
          {project && (
            <section className="panel studio-section studio-materials">
              <h2>Saved work</h2>
              <p>Assets and edits grouped with this project.</p>
              <ErrorNotice error={materials.error} />
              {materials.isPending ? (
                <Loading />
              ) : materials.data?.length ? (
                <nav aria-label="Project materials">
                  {materials.data.map((item) => (
                    <Link to={workspaceLink(item)} key={item.id}>
                      <span>
                        {item.title}
                        <small>
                          {item.capability} · {date(item.updated_at)}
                        </small>
                      </span>
                      <ArrowUpRight size={15} />
                    </Link>
                  ))}
                </nav>
              ) : (
                !materials.error && (
                  <Empty title="Room for your next story">
                    Related assets and edits will appear here.
                  </Empty>
                )
              )}
              {!readOnly && (
                <div className="studio-asset-actions">
                  <Button asChild variant="secondary">
                    <Link to={`/images?project=${project.id}`}>
                      Create an image
                    </Link>
                  </Button>
                  <Button asChild variant="ghost">
                    <Link to={`/video?project=${project.id}`}>
                      Create a scene
                    </Link>
                  </Button>
                </div>
              )}
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}

function workspaceLink(item: CreativeSession) {
  const path = {
    images: "/images",
    video: "/video",
    avatars: "/avatars",
    timeline: "/video",
    speech: "/audio",
    music: "/audio",
    effects: "/audio",
  }[item.capability];
  const query = new URLSearchParams({ session: item.id });
  if (item.capability === "timeline") query.set("mode", "edit");
  if (item.capability === "music") query.set("mode", "music");
  if (item.capability === "effects") query.set("mode", "effects");
  if (item.creative_project_id) query.set("project", item.creative_project_id);
  return `${path}?${query}`;
}
