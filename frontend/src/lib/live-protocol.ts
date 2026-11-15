/** Closed binary media packets. Paths, model choices and commands never travel here. */
export const LIVE_RATE = 22050;
export const LIVE_SAMPLES = 4410;
export const LIVE_HEADER = 18;
export const LIVE_MAX_IMAGE = 512 * 1024;
export type LiveKind = 1 | 2 | 17 | 18;
export type LivePacket = {
  kind: LiveKind;
  sequence: number;
  timestampUs: number;
  body: ArrayBuffer;
};

function validate(packet: LivePacket) {
  const { kind, sequence, timestampUs, body } = packet;
  if (
    ![1, 2, 17, 18].includes(kind) ||
    !Number.isInteger(sequence) ||
    sequence < 0 ||
    sequence > 0xffffffff ||
    !Number.isSafeInteger(timestampUs) ||
    timestampUs < 0 ||
    timestampUs > 4 * 3600 * 1_000_000 ||
    body.byteLength === 0 ||
    body.byteLength > LIVE_MAX_IMAGE
  )
    throw new Error("Invalid live media packet");
  if (kind === 2 || kind === 18) {
    if (body.byteLength !== LIVE_SAMPLES * 4)
      throw new Error("Invalid live audio block");
    const view = new DataView(body);
    for (let offset = 0; offset < body.byteLength; offset += 4) {
      const value = view.getFloat32(offset, true);
      if (!Number.isFinite(value) || Math.abs(value) > 1)
        throw new Error("Invalid live audio samples");
    }
  } else {
    const bytes = new Uint8Array(body);
    if (
      bytes[0] !== 0xff ||
      bytes[1] !== 0xd8 ||
      bytes[2] !== 0xff ||
      bytes.at(-2) !== 0xff ||
      bytes.at(-1) !== 0xd9
    )
      throw new Error("Invalid live picture");
  }
}

export function encodeLivePacket(packet: LivePacket): ArrayBuffer {
  validate(packet);
  const buffer = new ArrayBuffer(LIVE_HEADER + packet.body.byteLength);
  const bytes = new Uint8Array(buffer);
  bytes.set([65, 73, 83, 76, 1, packet.kind]);
  const header = new DataView(buffer);
  header.setUint32(6, packet.sequence);
  header.setBigUint64(10, BigInt(packet.timestampUs));
  bytes.set(new Uint8Array(packet.body), LIVE_HEADER);
  return buffer;
}

export function decodeLivePacket(buffer: ArrayBuffer): LivePacket {
  if (
    buffer.byteLength <= LIVE_HEADER ||
    buffer.byteLength > LIVE_HEADER + LIVE_MAX_IMAGE
  )
    throw new Error("Invalid live media size");
  const bytes = new Uint8Array(buffer);
  if ([65, 73, 83, 76, 1].some((value, index) => bytes[index] !== value))
    throw new Error("Invalid live media header");
  const header = new DataView(buffer);
  const packet = {
    kind: bytes[5] as LiveKind,
    sequence: header.getUint32(6),
    timestampUs: Number(header.getBigUint64(10)),
    body: buffer.slice(LIVE_HEADER),
  };
  if (packet.kind !== 17 && packet.kind !== 18)
    throw new Error("Invalid live output direction");
  validate(packet);
  return packet;
}
