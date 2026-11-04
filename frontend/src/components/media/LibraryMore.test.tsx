import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import LibraryMore from "./LibraryMore";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("loads on scroll, stops automatic retries on errors and permits a manual retry", () => {
  let enter: IntersectionObserverCallback;
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: IntersectionObserverCallback) {
        enter = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  const fetchNextPage = vi.fn();
  const props = {
    hasNextPage: true,
    isFetchingNextPage: false,
    isFetchNextPageError: false,
    fetchNextPage,
  };
  const { rerender } = render(<LibraryMore {...props} />);
  act(() =>
    enter(
      [{ isIntersecting: true }] as IntersectionObserverEntry[],
      {} as IntersectionObserver,
    ),
  );
  expect(fetchNextPage).toHaveBeenCalledTimes(1);
  rerender(<LibraryMore {...props} isFetchNextPageError />);
  fireEvent.click(
    screen.getByRole("button", { name: "Retry loading more files" }),
  );
  expect(fetchNextPage).toHaveBeenCalledTimes(2);
  rerender(<LibraryMore {...props} hasNextPage={false} />);
  expect(screen.queryByRole("button")).toBeNull();
});
