import { useId, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { useListKeyboard } from "./useListKeyboard";
import { isAgentToolList, type AgentToolSpec } from "./agentActivation";

type Tool = AgentToolSpec;

function toolTitle(tool: Pick<Tool, "name">) {
  return tool.name === "remember_report"
    ? "Remember reports"
    : tool.name === "remember_workflow"
      ? "Remember workflow observations"
      : tool.name === "http_fetch"
        ? "HTTP fetch"
        : tool.name;
}

export function AgentAttachedTools({
  names,
  agentId,
  tabIndex = 0,
  disabled = false,
  pending = false,
  onRemove,
}: {
  names: string[];
  agentId?: string;
  tabIndex?: number;
  disabled?: boolean;
  pending?: boolean;
  onRemove?: (name: string) => void;
}) {
  const labelId = useId();
  const catalog = useQuery({
    queryKey: ["agent-tools"],
    enabled: names.length > 0,
    queryFn: () => api<Tool[]>("/agents/tools"),
  });
  const registered = isAgentToolList(catalog.data) ? catalog.data : [];
  const byName = new Map(registered.map((tool) => [tool.name, tool]));
  const catalogReady = isAgentToolList(catalog.data);
  const rows = names.map(
    (name) =>
      byName.get(name) ?? {
        name,
        description: "",
        operational: false,
        required_permissions: [] as string[],
      },
  );
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    rows,
    (tool) => tool.name,
  );
  const active = tabIndex >= 0;
  const shortId = agentId?.slice(0, 8) ?? "";
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    event.preventDefault();
  };
  if (!names.length) return null;
  return (
    <>
      <ErrorNotice error={catalog.error} />
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a tool while the list is focused. Unavailable tools
        stay visible and block activation.
        {onRemove
          ? " Remove stays on an unavailable tool. Adding tools stays in Agents."
          : " Tools stay in Agents."}{" "}
        There is no inspectable tool-selection Run.
      </p>
      <div
        ref={listRef}
        className="agent-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {rows.map((tool, i) => {
          const current = i === index;
          const registeredTool = byName.get(tool.name);
          const removable =
            !!onRemove &&
            catalogReady &&
            (!registeredTool || !registeredTool.operational);
          const removeName = shortId
            ? `Remove tool ${tool.name} ${shortId}`
            : `Remove tool ${tool.name}`;
          return (
            <div
              key={tool.name}
              aria-label={`Tool ${tool.name}`}
              {...itemProps(i, tool.name)}
              tabIndex={active && current ? 0 : -1}
            >
              <div className="row spread">
                <div>
                  <p>
                    <strong>{toolTitle(tool)}</strong>
                    {registeredTool && !registeredTool.operational
                      ? " — Unavailable"
                      : ""}
                  </p>
                  {registeredTool ? (
                    <p className="muted">
                      {registeredTool.description}
                      {registeredTool.required_permissions.length
                        ? ` ${registeredTool.required_permissions.join(", ")}`
                        : ""}
                    </p>
                  ) : (
                    <p className="muted">Not in the tool registry.</p>
                  )}
                </div>
                {removable ? (
                  <Button
                    type="button"
                    variant="secondary"
                    tabIndex={active && current ? 0 : -1}
                    disabled={disabled || pending}
                    aria-label={removeName}
                    onClick={() => onRemove?.(tool.name)}
                  >
                    Remove
                  </Button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
