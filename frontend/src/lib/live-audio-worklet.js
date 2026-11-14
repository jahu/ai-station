/* global AudioWorkletProcessor, registerProcessor, sampleRate, currentFrame */
const RATE = 22050;
const BLOCK = 4410;

class StationLiveAudio extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.mode = options.processorOptions?.mode;
    if (!["capture", "playback"].includes(this.mode))
      throw new Error("Choose a live audio direction");
    this.failed = false;
    this.block = new Float32Array(BLOCK);
    this.filled = 0;
    this.sequence = 0;
    this.inputFrame = 0;
    this.nextOutput = 0;
    this.previous = 0;
    this.startFrame = null;
    this.queue = [];
    this.current = null;
    this.position = 0;
    this.primed = false;
    this.untilClock = 0;
    this.levelEnergy = 0;
    this.levelFrames = 0;
    this.port.onmessage = ({ data }) => {
      if (data?.type === "stop") {
        this.failed = true;
        return;
      }
      if (this.mode !== "playback" || data?.type !== "block") return;
      if (
        !(data.samples instanceof ArrayBuffer) ||
        data.samples.byteLength !== BLOCK * 4 ||
        !Number.isSafeInteger(data.timestampUs) ||
        data.timestampUs < 0
      ) {
        this.fail("Invalid converted audio block");
        return;
      }
      const samples = new Float32Array(data.samples);
      if (
        samples.some((value) => !Number.isFinite(value) || Math.abs(value) > 1)
      ) {
        this.fail("Invalid converted audio samples");
        return;
      }
      if (this.queue.length >= 4) {
        this.fail("Audio preview cannot keep up; restart the session");
        return;
      }
      this.queue.push({ samples, timestampUs: data.timestampUs });
    };
  }
  fail(message) {
    this.failed = true;
    this.port.postMessage({ type: "error", message });
  }
  capture(input) {
    if (!input?.length) return;
    if (this.startFrame === null) this.startFrame = currentFrame;
    let energy = 0;
    for (let i = 0; i < input.length; i++) {
      const value = input[i];
      if (!Number.isFinite(value)) {
        this.fail("Microphone returned invalid samples");
        return;
      }
      const sample = Math.max(-1, Math.min(1, value));
      energy += sample * sample;
      while (this.nextOutput <= this.inputFrame) {
        const before = this.inputFrame - this.nextOutput;
        this.block[this.filled++] =
          sample * (1 - before) + this.previous * before;
        this.nextOutput += sampleRate / RATE;
        if (this.filled === BLOCK) {
          const samples = this.block.buffer;
          this.port.postMessage(
            {
              type: "captured",
              samples,
              sequence: this.sequence,
              timestampUs: this.sequence * 200000,
              startFrame: this.startFrame,
            },
            [samples],
          );
          this.sequence++;
          this.block = new Float32Array(BLOCK);
          this.filled = 0;
        }
      }
      this.previous = sample;
      this.inputFrame++;
    }
    this.levelEnergy += energy;
    this.levelFrames += input.length;
    if (this.levelFrames >= sampleRate / 20) {
      this.port.postMessage({
        type: "level",
        rms: Math.sqrt(this.levelEnergy / this.levelFrames),
      });
      this.levelEnergy = 0;
      this.levelFrames = 0;
    }
  }
  playback(output) {
    if (!this.primed) {
      if (this.queue.length < 2) return;
      this.primed = true;
    }
    for (let i = 0; i < output.length; i++) {
      if (!this.current) {
        this.current = this.queue.shift() || null;
        if (!this.current) {
          this.primed = false;
          this.port.postMessage({ type: "buffering" });
          return;
        }
      }
      const { samples, timestampUs } = this.current;
      const index = Math.floor(this.position);
      const fraction = this.position - index;
      const next =
        index + 1 < BLOCK
          ? samples[index + 1]
          : (this.queue[0]?.samples[0] ?? samples[index]);
      output[i] = samples[index] * (1 - fraction) + next * fraction;
      this.position += RATE / sampleRate;
      if (++this.untilClock >= 2048) {
        this.untilClock = 0;
        this.port.postMessage({
          type: "clock",
          sourceUs: timestampUs + (this.position / RATE) * 1000000,
        });
      }
      if (this.position >= BLOCK) {
        this.position -= BLOCK;
        this.current = null;
      }
    }
  }
  process(inputs, outputs) {
    const output = outputs[0]?.[0];
    if (output) output.fill(0);
    if (this.failed) return false;
    if (this.mode === "capture") this.capture(inputs[0]?.[0]);
    else if (output) this.playback(output);
    return !this.failed;
  }
}
registerProcessor("station-live-audio", StationLiveAudio);
