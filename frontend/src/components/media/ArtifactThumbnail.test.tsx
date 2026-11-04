import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import ArtifactThumbnail from "./ArtifactThumbnail";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("decodes a still only for visible films, without playing or downloading another portrait", () => {
  let show: IntersectionObserverCallback;
  const disconnect = vi.fn();
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: IntersectionObserverCallback) {
        show = callback;
      }
      observe() {}
      disconnect = disconnect;
    },
  );
  const { container } = render(<ArtifactThumbnail id="film" kind="video" />);
  expect(container.querySelector("video")).toBeNull();
  act(() =>
    show(
      [{ isIntersecting: true }] as IntersectionObserverEntry[],
      {} as IntersectionObserver,
    ),
  );
  const video = container.querySelector("video")!;
  expect(video.getAttribute("src")).toBe("/api/artifacts/film/file");
  expect(video.preload).toBe("metadata");
  expect(video.autoplay).toBe(false);
  expect(video.muted).toBe(true);
  expect(video.controls).toBe(false);
  Object.defineProperty(video, "duration", { value: 12 });
  fireEvent.loadedMetadata(video);
  expect(video.currentTime).toBe(1);
  fireEvent.error(video);
  expect(container.querySelector("video")).toBeNull();
  expect(container.querySelector(".artifact-video-fallback")).toBeTruthy();
});
