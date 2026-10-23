import { expect, it } from "vitest";
import { canRegenerateResponse, visionReplies } from "./vision-replies";

type Message = Parameters<typeof visionReplies>[0][number];
function fixture(): Message[] {
  return [
    {
      id: "user",
      role: "user",
      content: "Describe this picture",
      run_id: "root-run",
      run_status: "succeeded",
      metadata: {},
    },
    {
      id: "notice",
      role: "assistant",
      content: "Reading image pixels with the selected model.",
      run_id: "root-run",
      run_status: "succeeded",
      task_status: "succeeded",
      metadata: { orchestration: true },
      steps: [
        {
          id: "root-run",
          capability: "assistant.orchestrate",
          status: "succeeded",
        },
        { id: "vision-run", capability: "chat.vision", status: "succeeded" },
      ],
    },
    {
      id: "answer",
      role: "assistant",
      content: "A red rectangle.",
      run_id: "vision-run",
      run_status: "succeeded",
      metadata: { vision_model: "local-vision" },
    },
  ];
}

it("presents the original Vision answer once, with the original execution record attached", () => {
  const messages = fixture(),
    before = structuredClone(messages);
  const projected = visionReplies(messages);
  expect(projected.visible).toEqual([messages[0], messages[2]]);
  expect(projected.visible[1]).toBe(messages[2]);
  expect(projected.executions.get("answer")).toBe(messages[1]);
  expect(messages).toEqual(before);
});

it.each([
  [
    "streaming",
    (rows: Message[]) => {
      rows[2].metadata.partial = true;
    },
  ],
  [
    "active task",
    (rows: Message[]) => {
      rows[1].task_status = "running";
    },
  ],
  [
    "failed reply",
    (rows: Message[]) => {
      rows[2].run_status = "failed";
    },
  ],
  [
    "missing answer",
    (rows: Message[]) => {
      rows[2].content = " ";
    },
  ],
  [
    "unrelated Run",
    (rows: Message[]) => {
      rows[2].run_id = "other-run";
    },
  ],
  [
    "superseded history",
    (rows: Message[]) => {
      rows[2].metadata.superseded = true;
    },
  ],
  [
    "additional source cards",
    (rows: Message[]) => {
      rows[1].metadata.page_read = { urls: ["https://example.org"] };
    },
  ],
  [
    "other workflow actions",
    (rows: Message[]) => {
      rows[1].steps!.push({
        id: "photo",
        capability: "image.generate",
        status: "succeeded",
      });
    },
  ],
] as const)("preserves separate rows for %s", (_label, change) => {
  const messages = fixture();
  change(messages);
  expect(visionReplies(messages).visible).toEqual(messages);
  expect(visionReplies(messages).executions.size).toBe(0);
});

it("does not associate an answer across a later user turn", () => {
  const messages = fixture();
  messages.splice(2, 0, { ...messages[0], id: "later-user" });
  expect(visionReplies(messages).visible).toEqual(messages);
});

it("does not choose between duplicate answers or competing execution records", () => {
  const messages = fixture();
  messages.push({ ...messages[2], id: "another-answer" });
  expect(visionReplies(messages).executions.size).toBe(0);
  const competing = fixture();
  competing.splice(2, 0, { ...competing[1], id: "other-notice" });
  expect(visionReplies(competing).visible).toEqual(competing);
});

it("keeps working text regeneration and rejects tool/Work replay even when the routing notice is hidden", () => {
  const messages = fixture();
  expect(canRegenerateResponse(messages)).toBe(false);
  const text = [
    { ...messages[0], run_id: "text-run" },
    { ...messages[2], run_id: "text-run", metadata: {} },
  ];
  expect(canRegenerateResponse(text)).toBe(true);
  expect(canRegenerateResponse([...messages, ...text])).toBe(true);
  expect(canRegenerateResponse([messages[0]])).toBe(false);
  expect(canRegenerateResponse([...text, messages[0]])).toBe(false);
  messages[1].metadata.routing_only = true;
  expect(canRegenerateResponse(messages)).toBe(false);
});
