import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  ConversationModeChoiceList,
  ConversationProviderChoiceList,
  type SavedChatMode,
} from "./ChatSettingsChoiceLists";
import type { ChatProviderInfo } from "./ChatProviders";

afterEach(cleanup);

const local: ChatProviderInfo = {
  id: "builtin-id",
  key: "local-openai-compatible",
  name: "Local OpenAI-compatible",
  kind: "openai-compatible",
  location: "local",
  endpoint: "http://localhost:8080/v1",
  default_model: "test-model",
  builtin: true,
  enabled: true,
  secret_source: "none",
  secret_ref: "",
  secret_present: false,
  models: ["test-model"],
  status: "available",
  error: null,
};

const remote: ChatProviderInfo = {
  ...local,
  id: "ext-id",
  key: "work-https",
  name: "Work HTTPS",
  location: "external",
  endpoint: "https://example.test/v1",
  builtin: false,
  enabled: true,
};

function ModeHost({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState<SavedChatMode>("local");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <ConversationModeChoiceList
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Create conversation</button>
    </form>
  );
}

function ProviderHost({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState("local-openai-compatible");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <ConversationProviderChoiceList
        value={value}
        disabled={disabled}
        providers={[local, remote]}
        onChange={setValue}
      />
      <button type="submit">Save settings</button>
    </form>
  );
}

it("moves through saved conversation mode without creating a conversation", () => {
  render(<ModeHost />);
  const localMode = screen.getByLabelText("Mode local");
  expect(localMode.tabIndex).toBe(0);
  expect(screen.getByText(/Let the assistant operate AI Station/)).toBeTruthy();
  expect(
    (
      screen.getByRole("radio", {
        name: /Conversation only/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  const list = localMode.closest(
    ".conversation-mode-choice-list",
  ) as HTMLElement;
  fireEvent.keyDown(list, { key: "Home" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (
      screen.getByRole("radio", {
        name: /Platform assistant/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(screen.getByLabelText("Mode orchestrator").tabIndex).toBe(0);
});

it("does not change saved mode while the list is disabled", () => {
  render(<ModeHost disabled />);
  const list = screen
    .getByLabelText("Mode local")
    .closest(".conversation-mode-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "Home" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (
      screen.getByRole("radio", {
        name: /Conversation only/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});

it("moves through saved providers without saving", () => {
  render(<ProviderHost />);
  const builtin = screen.getByLabelText("Provider local-openai-compatible");
  expect(builtin.tabIndex).toBe(0);
  expect(screen.getByText(/Choose where this conversation runs/)).toBeTruthy();
  const list = builtin.closest(
    ".conversation-provider-choice-list",
  ) as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /Work HTTPS/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  expect(screen.getByLabelText("Provider work-https").tabIndex).toBe(0);
});

it("does not submit the form when Enter selects a focused mode", () => {
  render(<ModeHost />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /Conversation only/ }), {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("radio", {
        name: /Conversation only/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});
