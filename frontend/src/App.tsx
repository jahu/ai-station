import { useEffect, useState } from "react";
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
  MessageSquare,
  Search,
  Settings2,
  Sparkles,
  Terminal,
  Users,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useHardware } from "./api";
import { Empty, PageTitle } from "./components/common";
import Dashboard from "./pages/Dashboard";
import { RunDetail, Runs } from "./pages/Runs";
import ImagesWorkspace from "./pages/Images";
import { Library, ArtifactDetail } from "./pages/Library";
import System from "./pages/System";

const groups: { label: string; items: [string, string, LucideIcon][] }[] = [
  {
    label: "",
    items: [
      ["/", "Home", House],
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
  const navigate = useNavigate();
  const location = useLocation();
  const hardware = useHardware();
  const page =
    destinations.find(
      ([path]) => path !== "/" && location.pathname.startsWith(path),
    )?.[1] ?? "Home";
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    document.addEventListener("keydown", listener);
    return () => document.removeEventListener("keydown", listener);
  }, []);
  return (
    <div className="app-shell">
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
        <button className="search-button" onClick={() => setOpen(true)}>
          <Search size={15} />
          <span>Go to workspace…</span>
          <kbd>Ctrl K</kbd>
        </button>
        <nav aria-label="Main navigation">
          {groups.map((group) => (
            <div className="nav-group" key={group.label}>
              {group.label && <div className="nav-label">{group.label}</div>}
              {group.items.map(([path, label, Icon]) => (
                <NavLink end={path === "/"} to={path} key={path}>
                  <Icon size={17} />
                  {label}
                  {path === "/" && <span className="nav-marker" />}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <NavLink to="/system">
            <Terminal size={17} />
            System
          </NavLink>
          <NavLink to="/settings">
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
      <div className="workspace">
        <header className="topbar">
          <div>
            <span className="muted">Workspace</span>
            <span className="slash">/</span>
            {page}
          </div>
          <div className="row">
            <span className="private-label">
              <span className="status-dot" />
              Local control plane
            </span>
            <button
              className="icon-button"
              aria-label="Open command palette"
              onClick={() => setOpen(true)}
            >
              <CommandIcon size={17} />
            </button>
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/runs" element={<Runs />} />
            <Route path="/runs/:id" element={<RunDetail />} />
            <Route path="/images" element={<ImagesWorkspace />} />
            <Route path="/library" element={<Library />} />
            <Route path="/library/:id" element={<ArtifactDetail />} />
            <Route path="/system" element={<System />} />
            <Route path="/settings" element={<System />} />
            <Route path="*" element={<Unavailable />} />
          </Routes>
        </main>
      </div>
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="command-dialog">
            <Dialog.Title className="sr-only">Go to workspace</Dialog.Title>
            <Dialog.Description className="sr-only">
              Search AI Station workspaces, then press Enter to open one.
            </Dialog.Description>
            <Command>
              <div className="command-input">
                <Search size={18} />
                <Command.Input placeholder="Where would you like to go?" />
                <Dialog.Close
                  className="icon-button"
                  aria-label="Close command palette"
                >
                  <X size={16} />
                </Dialog.Close>
              </div>
              <Command.List>
                <Command.Empty>No matching workspace.</Command.Empty>
                {destinations.map(([path, label, Icon]) => (
                  <Command.Item
                    key={path}
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
              </Command.List>
              <div className="command-footer">
                ↑ ↓ to navigate <span>↵ to open · esc to close</span>
              </div>
            </Command>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
