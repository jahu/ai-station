import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ResourceWaitNotice from "./ResourceWaitNotice";
import type { ResourceWait } from "../api";

afterEach(cleanup);
const wait: ResourceWait = {
  run_id: "queued-video",
  reason: "memory",
  checked_at: "2026-10-23T12:00:00Z",
  required_mib: 16384,
  available_mib: 12288,
  reserved_mib: 2048,
  headroom_mib: 1024,
};
const mount = (value?: ResourceWait | null) =>
  render(
    <MemoryRouter>
      <ResourceWaitNotice wait={value} />
    </MemoryRouter>,
  );
it("shows observed RAM, other reservations, automatic retry and the actual waiting Run", () => {
  mount(wait);
  expect(screen.getByText("Waiting for memory")).toBeTruthy();
  expect(
    screen.getByText(/RAM needed: 16.0 GiB · Available when checked: 12.0 GiB/),
  ).toBeTruthy();
  expect(screen.getByText(/Other active Runs reserve 2.0 GiB/)).toBeTruthy();
  expect(screen.getByText(/Safety headroom: 1.0 GiB/)).toBeTruthy();
  expect(screen.getByText(/retry automatically/)).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Inspect waiting Run" })
      .getAttribute("href"),
  ).toBe("/runs/queued-video");
  expect(screen.queryByText("Waiting for an available GPU")).toBeNull();
});
it("does not turn an unavailable RAM sensor into zero available memory", () => {
  mount({ ...wait, available_mib: null });
  expect(screen.getByText(/Available when checked: Unknown/)).toBeTruthy();
});
it("shows GPU admission separately without inventing RAM shortage or a device", () => {
  mount({ ...wait, reason: "gpu" });
  expect(screen.getByText("Waiting for an available GPU")).toBeTruthy();
  expect(screen.queryByText(/RAM needed/)).toBeNull();
  expect(screen.queryByText(/GPU [0-9]/)).toBeNull();
});
it("renders nothing before any resource observation exists", () => {
  mount(null);
  expect(screen.queryByLabelText("Resource wait")).toBeNull();
});
