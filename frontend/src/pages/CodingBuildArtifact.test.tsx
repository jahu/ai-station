import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Run } from "../api";
import CodingBuildArtifact from "./CodingBuildArtifact";

afterEach(cleanup);
const ready = {
  id: "validation",
  status: "succeeded",
  metadata: {
    build_artifact_id: "build-archive",
    build_export: { status: "ready", file_count: 3, size_bytes: 2048 },
  },
} as unknown as Run;
function show(run?: Run) {
  render(
    <MemoryRouter>
      <CodingBuildArtifact run={run} />
    </MemoryRouter>,
  );
}

it("offers a download and Library inspection for a verified build without executing it", () => {
  show(ready);
  const section = screen.getByRole("region", { name: "Build output" });
  expect(section.textContent).toContain("3 files · 2 KB");
  const download = screen.getByRole("link", { name: "Download build" });
  expect(download.getAttribute("href")).toBe(
    "/api/artifacts/build-archive/file",
  );
  expect(download.getAttribute("download")).toBe("project-build.zip");
  expect(
    screen
      .getByRole("link", { name: "View in Library →" })
      .getAttribute("href"),
  ).toBe("/library/build-archive");
  expect(document.querySelector("iframe,object,embed,script")).toBeNull();
});

it("never publishes stale build metadata from unfinished or unsuccessful validation", () => {
  for (const status of [
    "running",
    "queued",
    "failed",
    "canceled",
    "interrupted",
  ]) {
    show({ ...ready, status } as Run);
    expect(screen.queryByRole("link", { name: "Download build" })).toBeNull();
    cleanup();
  }
});

it("does not fabricate downloads for old reports or missing output", () => {
  show({ ...ready, metadata: {} });
  expect(screen.queryByRole("region", { name: "Build output" })).toBeNull();
  cleanup();
  show({
    ...ready,
    metadata: {
      build_export: {
        status: "unavailable",
        reason: "No dist directory was produced by this build.",
      },
    },
  });
  expect(screen.getByText(/Build download unavailable/)).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Download build" })).toBeNull();
});
