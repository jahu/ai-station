import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  CommitChoiceList,
  ProposalChoiceList,
} from "./AssistantGitChoiceLists";

afterEach(cleanup);

function ProposalHost({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState("");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <ProposalChoiceList
        proposals={[
          { id: "one", title: "Update app.py", detail: "local_proposal" },
          { id: "two", title: "Fix README", detail: "cursor_proposal" },
        ]}
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Send</button>
    </form>
  );
}

function CommitHost({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState("");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <CommitChoiceList
        commits={[
          { id: "c1", title: "abc1234", detail: "reviewed_commit" },
          { id: "c2", title: "def5678", detail: "reviewed_commit" },
        ]}
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Send</button>
    </form>
  );
}

it("moves through reviewed proposals without sending", () => {
  render(<ProposalHost />);
  const first = screen.getByLabelText("Proposal one");
  expect(first.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable proposal-selection Run/),
  ).toBeTruthy();
  const list = first.closest(".proposal-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /Fix README/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
});

it("does not submit the form when Enter selects a focused proposal", () => {
  render(<ProposalHost />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /Update app.py/ }), {
    key: "Enter",
  });
  expect(
    (screen.getByRole("radio", { name: /Update app.py/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
});

it("moves through reviewed commits without publishing", () => {
  render(<CommitHost />);
  const first = screen.getByLabelText("Commit c1");
  expect(first.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable commit-selection Run/),
  ).toBeTruthy();
  const list = first.closest(".commit-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /def5678/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
});

it("does not submit the form when Enter selects a focused commit", () => {
  render(<CommitHost />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /abc1234/ }), {
    key: "Enter",
  });
  expect(
    (screen.getByRole("radio", { name: /abc1234/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
});
