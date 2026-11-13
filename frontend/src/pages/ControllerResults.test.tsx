import { afterEach, expect, it } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Artifact } from "../api";
import type { ActionResult } from "./AssistantActions";
import ControllerResults from "./ControllerResults";

afterEach(cleanup);

it("keeps agent-definition review outside collapsed execution history", () => {
  render(
    <MemoryRouter>
      <ControllerResults
        result={{ task_status: "succeeded", controller_steps: [] }}
        active
        drafts={<p>Review the disabled agent definition</p>}
      >
        {() => <p>Detailed tool history</p>}
      </ControllerResults>
    </MemoryRouter>,
  );
  expect(screen.getByText("Review the disabled agent definition")).toBeTruthy();
  expect(screen.queryByText("Detailed tool history")).toBeNull();
});

function image(id: string): Artifact {
  return {
    id,
    type: "image",
    mime_type: "image/png",
    original_filename: `${id}.png`,
    title: `Result ${id}`,
    metadata: {},
    parent_artifact_ids: [],
    size_bytes: 100,
    created_at: "2026-11-13T00:00:00Z",
    run_id: `run-${id}`,
  };
}

function step(artifact: Artifact, tool = "image.edit") {
  return {
    index: 1,
    tool,
    reason: "Create the requested result",
    status: "succeeded",
    run_id: `run-${artifact.id}`,
    sources: [],
    result: { steps: [], artifacts: [artifact] },
  };
}

function view(result: ActionResult) {
  return (
    <MemoryRouter>
      <p>The requested results are ready.</p>
      <ControllerResults result={result} active>
        {() => <p>Detailed tool history</p>}
      </ControllerResults>
    </MemoryRouter>
  );
}

it("presents three final images before collapsed activity with Library and full-file links", () => {
  render(
    view({
      task_status: "succeeded",
      controller_steps: ["1", "2", "3"].map((id) => step(image(id))),
    }),
  );
  const gallery = screen.getByRole("region", { name: "Generated results" });
  const activity = screen.getByRole("region", { name: "Task activity" });
  expect(
    within(gallery)
      .getAllByRole("img")
      .map((img) => img.getAttribute("src")),
  ).toEqual(["1", "2", "3"].map((id) => `/api/artifacts/${id}/file`));
  expect(
    gallery.compareDocumentPosition(activity) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    screen
      .getByText("The requested results are ready.")
      .compareDocumentPosition(gallery) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    within(gallery)
      .getByRole("link", { name: "Result 1" })
      .getAttribute("href"),
  ).toBe("/library/1");
  const toggle = screen.getByRole("button", { name: /Task activity/ });
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByText("Detailed tool history")).toBeNull();
  fireEvent.click(toggle);
  expect(screen.getByText("Detailed tool history")).toBeTruthy();
  expect(within(gallery).getAllByRole("img")).toHaveLength(3);
});

it("shows active work, collapses at completion and preserves an explicit reopening across updates", () => {
  const result = {
    task_status: "running",
    controller_steps: [step(image("1"))],
  };
  const mounted = render(view(result));
  const toggle = () => screen.getByRole("button", { name: /Task activity/ });
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(toggle());
  mounted.rerender(view({ ...result }));
  expect(toggle().getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(toggle());
  mounted.rerender(view({ ...result, task_status: "succeeded" }));
  expect(toggle().getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(toggle());
  mounted.rerender(view({ ...result, task_status: "succeeded" }));
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
});

it("excludes sources, internal/rejected/deleted candidates and duplicate outputs from the result gallery", () => {
  render(
    view({
      task_status: "failed",
      controller_steps: [
        step(image("reference"), "web.image_import"),
        step({
          ...image("rejected"),
          metadata: { image_edit_review: { status: "rejected" } },
        }),
        step({
          ...image("pending"),
          metadata: { image_edit_review: { status: "pending" } },
        }),
        step({ ...image("internal"), metadata: { internal_media: true } }),
        step({ ...image("deleted"), trashed_at: "2026-11-13T01:00:00Z" }),
        step(image("accepted")),
        { ...step(image("accepted")), run_id: "another-step" },
      ],
    }),
  );
  expect(
    screen.getAllByRole("img").map((img) => img.getAttribute("alt")),
  ).toEqual(["Result accepted"]);
  expect(
    screen
      .getByRole("button", { name: /Task activity/ })
      .getAttribute("aria-expanded"),
  ).toBe("false");
});
