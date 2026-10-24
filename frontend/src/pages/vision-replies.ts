/** Presentation only: persisted messages and execution ownership remain unchanged. */
type Message = {
  id: string;
  role: string;
  content: string;
  run_id: string | null;
  run_status: string | null;
  task_status?: string;
  steps?: { id: string; capability: string; status: string }[];
  metadata: {
    orchestration?: boolean;
    agent_control?: unknown;
    partial?: boolean;
    superseded?: boolean;
    routing_only?: boolean;
    vision_model?: string;
    page_read?: unknown;
    web_search?: unknown;
    agent_id?: string;
    attachments?: unknown[];
    reasoning_text?: string;
  };
};
const INSPECTION_STEPS = new Set([
  "assistant.orchestrate",
  "chat.vision",
  "runtime.load",
  "runtime.stop",
]);

export function visionReplies<T extends Message>(messages: T[]) {
  const candidates = new Map<string, T[]>();
  for (const [index, root] of messages.entries()) {
    if (
      root.role !== "assistant" ||
      !root.metadata.orchestration ||
      root.metadata.partial ||
      root.metadata.superseded ||
      root.metadata.routing_only ||
      root.run_status !== "succeeded" ||
      root.task_status !== "succeeded" ||
      root.metadata.page_read ||
      root.metadata.web_search ||
      root.metadata.agent_id ||
      root.metadata.attachments?.length ||
      root.metadata.reasoning_text ||
      !root.steps?.length ||
      !root.steps.some(
        (step) =>
          step.id === root.run_id &&
          step.capability === "assistant.orchestrate",
      ) ||
      !root.steps.every(
        (step) =>
          step.status === "succeeded" && INSPECTION_STEPS.has(step.capability),
      )
    )
      continue;
    const visions = root.steps.filter(
      (step) => step.capability === "chat.vision",
    );
    if (visions.length !== 1) continue;
    const following: T[] = [];
    for (let next = index + 1; next < messages.length; next++) {
      const message = messages[next];
      if (message.role === "user") break;
      if (message.run_id === visions[0].id && message.role === "assistant")
        following.push(message);
    }
    if (following.length !== 1) continue;
    const reply = following[0];
    if (
      reply.run_status !== "succeeded" ||
      !reply.content.trim() ||
      !reply.metadata.vision_model ||
      reply.metadata.partial ||
      reply.metadata.superseded ||
      reply.metadata.routing_only ||
      reply.metadata.orchestration
    )
      continue;
    candidates.set(reply.id, [...(candidates.get(reply.id) ?? []), root]);
  }
  const executions = new Map<string, T>();
  for (const [replyId, roots] of candidates) {
    if (roots.length === 1) executions.set(replyId, roots[0]);
  }
  const folded = new Set([...executions.values()].map((message) => message.id));
  return {
    visible: messages.filter(
      (message) => !message.metadata.routing_only && !folded.has(message.id),
    ),
    executions,
  };
}

export function canRegenerateResponse(messages: Message[]) {
  const user = messages.filter((message) => message.role === "user").at(-1);
  if (!user) return false;
  const reply = messages
    .slice(messages.indexOf(user) + 1)
    .filter((message) => message.role === "assistant")
    .at(-1);
  if (!reply || reply.metadata.orchestration || reply.metadata.agent_control)
    return false;
  // The existing API rejects replaying a tool/Work action from its original user Run.
  return !messages.some(
    (message) =>
      user.run_id &&
      message.run_id === user.run_id &&
      (message.metadata.orchestration || message.metadata.agent_control),
  );
}
