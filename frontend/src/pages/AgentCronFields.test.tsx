import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AgentCronFields from "./AgentCronFields";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(initial = "0 9 * * *") {
  const save = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ["UTC", "Europe/Warsaw", "America/New_York"],
    })),
  );
  function Form() {
    const [cron, setCron] = useState(initial),
      [zone, setZone] = useState("UTC");
    return (
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save({ cron_expr: cron, schedule_timezone: zone });
        }}
      >
        <AgentCronFields
          cron={cron}
          timezone={zone}
          onCron={setCron}
          onTimezone={setZone}
        />
        <button>Save</button>
      </form>
    );
  }
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <Form />
    </QueryClientProvider>,
  );
  return save;
}

it("edits a daily wall-clock hour and selected zone without running or saving automatically", async () => {
  const save = mount();
  expect((screen.getByLabelText("Daily time") as HTMLInputElement).value).toBe(
    "09:00",
  );
  await screen.findByRole("option", { name: "America/New_York" });
  fireEvent.change(screen.getByLabelText("Daily time"), {
    target: { value: "09:30" },
  });
  fireEvent.change(screen.getByLabelText("Schedule timezone"), {
    target: { value: "America/New_York" },
  });
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(save).toHaveBeenCalledWith({
    cron_expr: "30 9 * * *",
    schedule_timezone: "America/New_York",
  });
});

it("retains existing custom cron and UTC until the operator explicitly changes them", async () => {
  const save = mount("0 7 * * 1-5");
  expect(
    (screen.getByLabelText("Schedule pattern") as HTMLSelectElement).value,
  ).toBe("custom");
  expect(
    (screen.getByLabelText("Cron expression") as HTMLInputElement).value,
  ).toBe("0 7 * * 1-5");
  await waitFor(() =>
    expect(screen.getByLabelText("Schedule timezone")).toBeTruthy(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(save).toHaveBeenCalledWith({
    cron_expr: "0 7 * * 1-5",
    schedule_timezone: "UTC",
  });
  fireEvent.change(screen.getByLabelText("Schedule pattern"), {
    target: { value: "daily" },
  });
  expect((screen.getByLabelText("Daily time") as HTMLInputElement).value).toBe(
    "09:00",
  );
});
