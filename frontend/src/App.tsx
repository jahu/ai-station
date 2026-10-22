import SitePreview from "./pages/SitePreview";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { Command } from "cmdk";
import * as Dialog from "@radix-ui/react-dialog";
import {
  Activity,
  AudioLines,
  Bot,
  Box,
  Code2,
  Command as CommandIcon,
  Film,
  FolderGit2,
  House,
  Image,
  Images,
  Layers,
  LogOut,
  PanelLeft,
  MessageSquare,
  Search,
  Settings2,
  Sparkles,
  Terminal,
  Users,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api, useHardware } from "./api";
import { Empty, PageTitle } from "./components/common";
import { Button } from "./components/ui/button";
import { Memory, MemoryDetail } from "./pages/Memory";
import { Models, ModelDetail } from "./pages/Models";
import { Agents, AgentDetail } from "./pages/Agents";
import Coding from "./pages/Coding";
import CodingSession, { CodingNav } from "./pages/CodingSessions";
import Chat from "./pages/Chat";
import Audio from "./pages/Audio";
import Avatars from "./pages/Avatars";
import Video from "./pages/Video";
import Dashboard from "./pages/Dashboard";
import { RunDetail, Runs } from "./pages/Runs";
import ImagesWorkspace from "./pages/Images";
import { Library, ArtifactDetail } from "./pages/Library";
import { SystemRoute, SystemDiagnostics } from "./pages/System";
import Settings from "./pages/Settings";
import { Projects, NewProject, ProjectDetail } from "./pages/Projects";
import type { OperatorStatus } from "./pages/OperatorLogin";

const groups: { label: string; items: [string, string, LucideIcon][] }[] = [
  {
    label: "",
    items: [
      ["/home", "Home", House],
      ["/chat", "Chat", MessageSquare],
    ],
  },
  {
    label: "CREATE",
    items: [
      ["/images", "Images", Image],
      ["/video", "Video", Film],
      ["/audio", "Audio", AudioLines],
      ["/avatars", "Avatars", Users],
    ],
  },
  {
    label: "WORKSPACE",
    items: [
      ["/coding", "Coding", Code2],
      ["/projects", "Projects", FolderGit2],
      ["/agents", "Agents", Bot],
    ],
  },
  {
    label: "MANAGE",
    items: [
      ["/models", "Models", Box],
      ["/library", "Library", Images],
      ["/runs", "Runs", Activity],
      ["/memory", "Memory", Layers],
    ],
  },
];
const destinations = [
  ...groups.flatMap((g) => g.items),
  ["/system", "System", Terminal],
  ["/settings", "Settings", Settings2],
] as [string, string, LucideIcon][];
const actions: [string, string, string][] = [
  ["/home", "Home activity", "Inspect, stop or acknowledge"],
  ["/runs", "Active runs", "Open the queue"],
  ["/settings/maintenance", "Backup and upgrade readiness", "SQLite backup"],
];

function Unavailable() {
  const { pathname } = useLocation();
  const name =
    destinations.find(([path]) => path === pathname)?.[1] ?? "Workspace";
  return (
    <>
      <PageTitle eyebrow="WORKSPACE / COMING NEXT" title={name}>
        This capability is part of the AI Station roadmap.
      </PageTitle>
      <section className="panel">
        <Empty title={`${name} is not available yet`}>
          The shared run infrastructure is ready. This workspace will become
          available when its executor, permissions, and end-to-end workflow are
          verified.
        </Empty>
      </section>
    </>
  );
}

export default function App() {
  const [open, setOpen] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const firstPath = useRef(true);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const isChat =
    location.pathname === "/" ||
    location.pathname === "/chat" ||
    location.pathname.startsWith("/chat/");
  const cache = useQueryClient();
  const hardware = useHardware();
  const operator = useQuery({
    queryKey: ["operator-auth"],
    queryFn: () => api<OperatorStatus>("/operator-auth"),
  });
  const logout = useMutation({
    mutationFn: () =>
      api<OperatorStatus>("/operator-auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["operator-auth"] });
    },
  });
  const sessionActive = Boolean(
    operator.data?.session_required && operator.data.authenticated,
  );
  const page = location.pathname.startsWith("/preview/")
    ? "Website preview"
    : (destinations.find(
        ([path]) => path !== "/" && location.pathname.startsWith(path),
      )?.[1] ?? (location.pathname === "/" ? "Chat" : "Workspace"));
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavigationOpen(false);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    document.addEventListener("keydown", listener);
    return () => document.removeEventListener("keydown", listener);
  }, []);
  useEffect(() => {
    document.title = `${page} · AI Station`;
  }, [page]);
  useEffect(() => {
    if (firstPath.current) {
      firstPath.current = false;
      return;
    }
    setNavigationOpen(false);
    document.getElementById("main")?.focus();
    setAnnouncement(`${page} workspace`);
  }, [location.pathname, page]);
  return (
    <div
      className={`app-shell ${isChat ? "conversation-app" : ""} ${navigationOpen ? "navigation-expanded" : ""}`}
    >
      <a
        href="#main"
        className="skip-link"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to workspace
      </a>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-symbol">
            <Sparkles size={20} />
          </div>
          <span>
            AI Station<small>YOUR PERSONAL AI WORKSTATION</small>
          </span>
        </div>
        <button
          type="button"
          className="search-button"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen(true)}
        >
          <Search size={15} />
          <span>Go to workspace…</span>
          <kbd>Ctrl K</kbd>
        </button>
        <nav id="station-navigation" aria-label="Main navigation">
          {groups.map((group) => (
            <div className="nav-group" key={group.label}>
              {group.label && <div className="nav-label">{group.label}</div>}
              {group.items.map(([path, label, Icon]) =>
                path === "/coding" ? (
                  <CodingNav key={path} />
                ) : (
                  <NavLink
                    end={path === "/"}
                    to={path}
                    key={path}
                    title={label}
                    className={({ isActive }) =>
                      isActive ||
                      (path === "/chat" && location.pathname === "/")
                        ? "active"
                        : undefined
                    }
                  >
                    <Icon size={17} />
                    {label}
                    {path === "/" && <span className="nav-marker" />}
                  </NavLink>
                ),
              )}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <NavLink to="/system" title="System">
            <Terminal size={17} />
            System
          </NavLink>
          <NavLink to="/settings" title="Settings">
            <Settings2 size={17} />
            Settings
          </NavLink>
          <div className="local-card">
            <span
              className={`status-dot ${hardware.isError ? "offline" : ""}`}
            />
            <div>
              Local workstation
              <small>
                {hardware.isPending
                  ? "Connecting…"
                  : hardware.isError
                    ? "Runner unavailable"
                    : "Host Runner connected"}
              </small>
            </div>
            <span className="tiny-tag">LOCAL</span>
          </div>
        </div>
      </aside>
      {isChat && navigationOpen && (
        <button
          className="station-navigation-backdrop"
          aria-label="Close navigation"
          onClick={() => setNavigationOpen(false)}
        />
      )}
      <div className="workspace">
        <header className="topbar">
          <div className="workspace-location">
            {isChat && (
              <Button
                variant="ghost"
                className="station-navigation-toggle"
                aria-label={
                  navigationOpen ? "Collapse navigation" : "Expand navigation"
                }
                aria-expanded={navigationOpen}
                aria-controls="station-navigation"
                onClick={() => setNavigationOpen((value) => !value)}
              >
                <PanelLeft size={18} />
              </Button>
            )}
            <span className="muted">Workspace</span>
            <span className="slash">/</span>
            {page}
          </div>
          <div className="row">
            <span className="private-label">
              <span className="status-dot" />
              {sessionActive ? "Operator session" : "Local control plane"}
            </span>
            {sessionActive ? (
              <Button
                type="button"
                variant="secondary"
                disabled={logout.isPending}
                onClick={() => logout.mutate()}
              >
                <LogOut size={15} />
                {logout.isPending ? "Signing out…" : "Sign out"}
              </Button>
            ) : null}
            <button
              className="icon-button"
              aria-label="Open command palette"
              onClick={() => setOpen(true)}
            >
              <CommandIcon size={17} />
            </button>
          </div>
        </header>
        <div
          id="route-announcer"
          className="sr-only"
          aria-live="polite"
          aria-atomic="true"
        >
          {announcement}
        </div>
        <main
          id="main"
          tabIndex={-1}
          className={isChat ? "conversation-main" : undefined}
        >
          <Routes>
            <Route path="/" element={<Chat assistant />} />
            <Route path="/home" element={<Dashboard />} />
            <Route path="/runs" element={<Runs />} />
            <Route
              path="/preview/:sourceRunId/:artifactId"
              element={<SitePreview />}
            />
            <Route path="/runs/:id" element={<RunDetail />} />
            <Route path="/coding" element={<Coding />} />
            <Route
              path="/coding/:id"
              element={<CodingSession key={location.pathname} />}
            />
            <Route path="/chat" element={<Chat assistant />} />
            <Route path="/chat/:id" element={<Chat assistant />} />
            <Route path="/images" element={<ImagesWorkspace />} />
            <Route path="/library" element={<Library />} />
            <Route path="/library/:id" element={<ArtifactDetail />} />
            <Route path="/system" element={<SystemRoute />} />
            <Route path="/system/diagnostics" element={<SystemDiagnostics />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/settings/:section" element={<Settings />} />
            <Route path="/models" element={<Models />} />
            <Route path="/models/:id" element={<ModelDetail />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/agents/:id" element={<AgentDetail />} />
            <Route path="/memory" element={<Memory />} />
            <Route path="/memory/new" element={<MemoryDetail />} />
            <Route path="/memory/:id" element={<MemoryDetail />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/projects/new" element={<NewProject />} />
            <Route path="/projects/:id" element={<ProjectDetail />} />
            <Route path="/audio" element={<Audio />} />
            <Route path="/avatars" element={<Avatars />} />
            <Route path="/video" element={<Video />} />
            <Route path="*" element={<Unavailable />} />
          </Routes>
        </main>
      </div>
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="command-dialog">
            <Dialog.Title className="sr-only">Command palette</Dialog.Title>
            <Dialog.Description className="sr-only">
              Search workspaces and station actions. Press Enter to open.
              Control K toggles this palette; Escape closes it.
            </Dialog.Description>
            <Command>
              <div className="command-input">
                <Search size={18} />
                <Command.Input
                  placeholder="Where would you like to go?"
                  aria-label="Search workspaces and actions"
                />
                <Dialog.Close
                  className="icon-button"
                  aria-label="Close command palette"
                >
                  <X size={16} />
                </Dialog.Close>
              </div>
              <Command.List>
                <Command.Empty>No matching workspace or action.</Command.Empty>
                <Command.Group heading="Actions">
                  {actions.map(([path, label, hint]) => (
                    <Command.Item
                      key={path}
                      value={`${label} ${hint}`}
                      onSelect={() => {
                        navigate(path);
                        setOpen(false);
                      }}
                    >
                      <Activity size={18} />
                      {label}
                      <span>{hint} ↵</span>
                    </Command.Item>
                  ))}
                </Command.Group>
                <Command.Group heading="Workspaces">
                  {destinations.map(([path, label, Icon]) => (
                    <Command.Item
                      key={path}
                      value={label}
                      onSelect={() => {
                        navigate(path);
                        setOpen(false);
                      }}
                    >
                      <Icon size={18} />
                      {label}
                      <span>Open workspace ↵</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              </Command.List>
              <div className="command-footer">
                ↑ ↓ to navigate{" "}
                <span>Ctrl K to open · ↵ to go · esc to close</span>
              </div>
            </Command>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
