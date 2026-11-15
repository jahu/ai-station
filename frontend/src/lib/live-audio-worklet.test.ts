import { describe, expect, it } from "vitest";
import source from "./live-audio-worklet.js?raw";

type Message = {
  type: string;
  samples?: ArrayBuffer;
  timestampUs?: number;
  rms?: number;
  sourceUs?: number;
};
type Processor = {
  process(input: Float32Array[][], output: Float32Array[][]): boolean;
  port: { onmessage(event: { data: unknown }): void };
};
function processor(mode: "capture" | "playback") {
  const messages: Message[] = [];
  let Factory: new (options: unknown) => Processor;
  class Base {
    port = {
      postMessage: (value: Message) => messages.push(value),
      onmessage: () => {},
    };
  }
  // Run the fixed bundled processor in a synthetic AudioWorklet scope. No real
  // microphone, speaker, WebSocket or GPU is opened by these ordinary tests.
  new Function(
    "AudioWorkletProcessor",
    "registerProcessor",
    "sampleRate",
    "currentFrame",
    source,
  )(
    Base,
    (_name: string, value: typeof Factory) => {
      Factory = value;
    },
    48000,
    0,
  );
  return { engine: new Factory!({ processorOptions: { mode } }), messages };
}

describe("live audio worklet", () => {
  it("resamples microphone capture into exact 200ms blocks without monitoring the original", () => {
    const { engine, messages } = processor("capture");
    for (let offset = 0; offset < 48000; offset += 128) {
      const input = new Float32Array(Math.min(128, 48000 - offset)).fill(0.25);
      const output = new Float32Array(input.length).fill(0.9);
      expect(engine.process([[input]], [[output]])).toBe(true);
      expect(Array.from(output).every((n) => n === 0)).toBe(true);
    }
    const captured = messages.filter((m) => m.type === "captured");
    expect(captured).toHaveLength(5);
    expect(captured.map((m) => m.timestampUs)).toEqual([
      0, 200000, 400000, 600000, 800000,
    ]);
    for (const message of captured) {
      const samples = new Float32Array(message.samples!);
      expect(samples).toHaveLength(4410);
      expect(samples.every((n) => Math.abs(n - 0.25) < 0.00001)).toBe(true);
    }
    expect(
      messages.filter((m) => m.type === "level").length,
    ).toBeLessThanOrEqual(20);
  });
  it("plays converted samples with a source clock and never mixes the local microphone", () => {
    const { engine, messages } = processor("playback");
    for (let i = 0; i < 2; i++)
      engine.port.onmessage({
        data: {
          type: "block",
          timestampUs: i * 200000,
          samples: new Float32Array(4410).fill(0.25).buffer,
        },
      });
    for (let i = 0; i < 20; i++) {
      const output = new Float32Array(128);
      engine.process([[new Float32Array(128).fill(0.9)]], [[output]]);
      expect(output.every((n) => Math.abs(n - 0.25) < 0.00001)).toBe(true);
    }
    expect(messages.some((m) => m.type === "clock" && m.sourceUs! > 0)).toBe(
      true,
    );
  });
  it("bounds playback buffering and rejects malformed samples with silent output", () => {
    const { engine, messages } = processor("playback");
    for (let i = 0; i < 5; i++)
      engine.port.onmessage({
        data: {
          type: "block",
          timestampUs: i * 200000,
          samples: new Float32Array(4410).buffer,
        },
      });
    expect(messages.some((m) => m.type === "error")).toBe(true);
    const output = new Float32Array(128).fill(0.9);
    expect(engine.process([], [[output]])).toBe(false);
    expect(output.every((n) => n === 0)).toBe(true);
  });
});
