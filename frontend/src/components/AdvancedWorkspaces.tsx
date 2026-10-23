import { useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { NavLink, useLocation } from "react-router-dom";
import { FolderGit2, Wrench, X } from "lucide-react";
import { CodingNav } from "../pages/CodingSessions";

export default function AdvancedWorkspaces() {
  const [open, setOpen] = useState(false);
  const navigating = useRef(false);
  const { pathname } = useLocation();
  const active = /^\/(coding|projects)(\/|$)/.test(pathname);
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        if (value) navigating.current = false;
        setOpen(value);
      }}
    >
      <Dialog.Trigger
        className={`advanced-navigation-trigger ${active ? "active" : ""}`}
        title="Advanced workspaces"
        aria-label="Advanced workspaces"
      >
        <Wrench size={17} aria-hidden="true" />
        <span>Advanced</span>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="advanced-workspaces-dialog"
          onCloseAutoFocus={(event) => {
            // Route changes focus the main workspace; dismissing returns to the trigger.
            if (navigating.current) {
              event.preventDefault();
              document.getElementById("main")?.focus();
            }
          }}
        >
          <div className="row spread">
            <Dialog.Title>Advanced workspaces</Dialog.Title>
            <Dialog.Close
              className="icon-button"
              aria-label="Close advanced workspaces"
            >
              <X size={18} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted">
            Existing coding conversations and reusable project resources. For
            everyday tasks, start in Chat or Agents.
          </Dialog.Description>
          {open && (
            <nav
              aria-label="Advanced workspaces"
              onClick={(event) => {
                if ((event.target as HTMLElement).closest("a")) {
                  navigating.current = true;
                  setOpen(false);
                }
              }}
            >
              <CodingNav />
              <NavLink to="/projects">
                <FolderGit2 size={17} aria-hidden="true" />
                Projects
              </NavLink>
            </nav>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
