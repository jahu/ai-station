import { afterEach, expect, it, vi } from "vitest";
import { randomId } from "./random-id";

afterEach(() => vi.unstubAllGlobals());

it("uses the native UUID implementation when available", () => {
  const native = vi.fn(() => "e198f0bc-9c35-43ef-8b26-89493df3be44");
  vi.stubGlobal("crypto", { randomUUID: native });
  expect(randomId()).toBe("e198f0bc-9c35-43ef-8b26-89493df3be44");
  expect(native).toHaveBeenCalledOnce();
});

it("uses secure random bytes when private HTTP has no randomUUID", () => {
  const source = crypto;
  const random = vi.fn(source.getRandomValues.bind(source));
  vi.stubGlobal("crypto", { getRandomValues: random });
  const ids = Array.from({ length: 100 }, randomId);
  expect(new Set(ids).size).toBe(100);
  expect(
    ids.every((id) =>
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
        id,
      ),
    ),
  ).toBe(true);
  expect(random).toHaveBeenCalledTimes(100);
});
