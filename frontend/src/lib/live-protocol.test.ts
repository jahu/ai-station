import { describe, expect, it } from "vitest";
import {
  decodeLivePacket,
  encodeLivePacket,
  LIVE_HEADER,
  LIVE_SAMPLES,
} from "./live-protocol";

describe("live binary transport", () => {
  it("matches the Python network-order header and little-endian mono PCM", () => {
    const body = new ArrayBuffer(LIVE_SAMPLES * 4);
    const packet = encodeLivePacket({
      kind: 2,
      sequence: 7,
      timestampUs: 1_400_000,
      body,
    });
    const hex = Array.from(new Uint8Array(packet, 0, LIVE_HEADER), (n) =>
      n.toString(16).padStart(2, "0"),
    ).join("");
    expect(hex).toBe("4149534c0102000000070000000000155cc0");
    expect(() => decodeLivePacket(packet)).toThrow("direction");
    new DataView(packet).setUint8(5, 18);
    const parsed = decodeLivePacket(packet);
    expect(parsed.kind).toBe(18);
    expect(parsed.sequence).toBe(7);
    expect(parsed.timestampUs).toBe(1_400_000);
    expect(parsed.body.byteLength).toBe(LIVE_SAMPLES * 4);
  });
  it("rejects malformed, nonfinite, oversized and ambiguous server output", () => {
    const body = new ArrayBuffer(LIVE_SAMPLES * 4);
    new DataView(body).setFloat32(0, NaN, true);
    expect(() =>
      encodeLivePacket({ kind: 2, sequence: 0, timestampUs: 0, body }),
    ).toThrow("samples");
    expect(() => decodeLivePacket(new ArrayBuffer(4))).toThrow("size");
    expect(() => decodeLivePacket(new ArrayBuffer(1024 * 1024))).toThrow(
      "size",
    );
    expect(() =>
      encodeLivePacket({
        kind: 1,
        sequence: 0,
        timestampUs: 0,
        body: new ArrayBuffer(10),
      }),
    ).toThrow("picture");
    expect(() =>
      encodeLivePacket({ kind: 18, sequence: -1, timestampUs: 0, body }),
    ).toThrow("packet");
  });
});
