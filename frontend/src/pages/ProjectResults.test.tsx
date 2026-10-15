import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { RunEvent } from "../api";
import { DependencyResults, ValidationResults } from "./ProjectResults";

afterEach(() => cleanup());

const event = (
  id: string,
  type: string,
  payload: Record<string, unknown>,
): RunEvent => ({
  id,
  sequence: 1,
  event_type: type,
  payload,
  created_at: "2026-10-09T12:00:00Z",
});

it("lists saved validation commands without inventing a child Run", () => {
  render(
    <ValidationResults
      events={[
        event("val-test", "validation.completed", {
          kind: "test",
          argv: ["pytest", "-q"],
          exit_code: 0,
          duration_seconds: 1.2,
        }),
      ]}
    />,
  );
  expect(
    screen.getByRole("heading", { name: "Project validation" }),
  ).toBeTruthy();
  expect(screen.getByText("test")).toBeTruthy();
  expect(screen.getByText(/\["pytest","-q"\]/)).toBeTruthy();
  expect(screen.queryByRole("link")).toBeNull();
});

it("moves through validation commands with arrow keys", () => {
  render(
    <ValidationResults
      events={[
        event("val-test", "validation.completed", {
          kind: "test",
          argv: ["pytest", "-q"],
          exit_code: 0,
          duration_seconds: 1.2,
        }),
        event("val-lint", "validation.completed", {
          kind: "lint",
          argv: ["ruff", "check"],
          exit_code: 1,
          duration_seconds: 0.4,
        }),
      ]}
    />,
  );
  const first = screen.getByLabelText("Command test val-test");
  const second = screen.getByLabelText("Command lint val-lint");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Project validation" }),
  ).toBeTruthy();
  expect(
    screen.getByText(/Arrow keys choose a validation command/),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});

it("moves through dependency installs with arrow keys", () => {
  render(
    <DependencyResults
      events={[
        event("dep-vendor", "dependencies.completed", {
          manifest: "requirements.txt",
          source: "vendor",
          specifiers: ["demo==1.0"],
          exit_code: 0,
          duration_seconds: 2.5,
          network: false,
        }),
        event("dep-pypi", "dependencies.completed", {
          manifest: "pyproject.toml",
          source: "pypi",
          specifiers: ["httpx==0.27.0"],
          exit_code: 0,
          duration_seconds: 4.1,
          network: true,
        }),
      ]}
    />,
  );
  const first = screen.getByLabelText("Install requirements.txt dep-vendor");
  const second = screen.getByLabelText("Install pyproject.toml dep-pypi");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Project dependencies" }),
  ).toBeTruthy();
  expect(screen.getByText(/offline vendor/)).toBeTruthy();
  expect(screen.getByText(/PyPI/)).toBeTruthy();
  expect(screen.queryByRole("link")).toBeNull();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement).toBe(second);
});

it("identifies npm results and disabled lifecycle scripts without a PyPI label", () => {
  render(
    <DependencyResults
      events={[
        event("dep-node", "dependencies.completed", {
          ecosystem: "node",
          lock_generated: true,
          manifest: "package-lock.json",
          source: "npm",
          specifiers: ["is-number@7.0.0"],
          exit_code: 0,
          duration_seconds: 0.5,
          network: true,
        }),
      ]}
    />,
  );
  expect(
    screen.getByText(/npm registry · lifecycle scripts disabled/),
  ).toBeTruthy();
  expect(screen.queryByText(/PyPI/)).toBeNull();
  expect(screen.getByText(/lockfile created offline/)).toBeTruthy();
  expect(
    screen.getByLabelText("Install package-lock.json dep-node"),
  ).toBeTruthy();
});
