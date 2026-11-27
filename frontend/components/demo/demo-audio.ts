/**
 * Browser side of the demo call's audio, speaking the same messages as a phone stream
 * (backend voice/demo_session.py):
 *  - microphone → 16-bit PCM, mono, 8 kHz → {"event":"media"} every 100 ms
 *  - {"event":"media"} from the agent → played back to back, in order
 *  - {"event":"mark"} → echoed once the audio before it has played
 *  - {"event":"clear"} (the visitor talked over the agent) → playback stops at once
 */

export const PHONE_RATE = 8000;
const SEND_EVERY_SAMPLES = PHONE_RATE / 10; // 100 ms

// Runs on the audio thread: hands each block of microphone samples to the page
const WORKLET = `
class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) this.port.postMessage(channel.slice(0));
    return true;
  }
}
registerProcessor("cz-capture", Capture);
`;

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

function fromBase64(text: string): Uint8Array {
  const binary = atob(text);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

/** Turns the microphone's rate (often 48 kHz) into 8 kHz by averaging, in a streaming way. */
class Downsampler {
  private readonly step: number;
  private pos = 0;
  private sum = 0;
  private count = 0;

  constructor(inputRate: number) {
    this.step = inputRate / PHONE_RATE;
  }

  push(input: Float32Array, out: number[]) {
    for (let i = 0; i < input.length; i++) {
      this.sum += input[i];
      this.count++;
      this.pos += 1;
      if (this.pos >= this.step) {
        this.pos -= this.step;
        out.push(this.sum / this.count);
        this.sum = 0;
        this.count = 0;
      }
    }
  }
}

export class DemoAudio {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private pending: number[] = [];
  private playhead = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private markTimers = new Map<number, string>();
  /** Microphone level 0..1, for the meter. */
  level = 0;

  constructor(private readonly send: (message: unknown) => void) {}

  /** Must run from a click: browsers only start audio after a user gesture. */
  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    const ctx = new AudioContext();
    this.ctx = ctx;
    await ctx.resume();
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    try {
      await ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    const source = ctx.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(ctx, "cz-capture");
    this.node = node;
    const down = new Downsampler(ctx.sampleRate);
    node.port.onmessage = (event: MessageEvent<Float32Array>) => {
      const block = event.data;
      let peak = 0;
      for (let i = 0; i < block.length; i++) peak = Math.max(peak, Math.abs(block[i]));
      this.level = this.level * 0.8 + peak * 0.2;
      down.push(block, this.pending);
      if (this.pending.length >= SEND_EVERY_SAMPLES) this.flushMic();
    };
    source.connect(node);
    // The node must reach the output to keep running; it writes nothing, so nothing is heard
    node.connect(ctx.destination);
    this.playhead = ctx.currentTime;
  }

  private flushMic() {
    const samples = this.pending;
    this.pending = [];
    const pcm = new Int16Array(samples.length);
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    this.send({ event: "media", media: { payload: toBase64(new Uint8Array(pcm.buffer)) } });
  }

  /** The agent's voice: 16-bit PCM at 8 kHz, queued right after what's already playing. */
  play(payload: string) {
    const ctx = this.ctx;
    if (!ctx) return;
    const bytes = fromBase64(payload);
    const pcm = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.length / 2));
    if (!pcm.length) return;
    const buffer = ctx.createBuffer(1, pcm.length, PHONE_RATE);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000;
    const node = ctx.createBufferSource();
    node.buffer = buffer;
    node.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.02, this.playhead);
    node.start(at);
    this.playhead = at + buffer.duration;
    this.sources.add(node);
    node.onended = () => this.sources.delete(node);
  }

  /** Echo the mark once everything queued before it has played. */
  mark(name: string) {
    const ctx = this.ctx;
    const wait = ctx ? Math.max(0, this.playhead - ctx.currentTime) : 0;
    const id = window.setTimeout(() => {
      this.markTimers.delete(id);
      this.send({ event: "mark", mark: { name } });
    }, wait * 1000);
    this.markTimers.set(id, name);
  }

  /** Barge-in: stop the agent's voice now; marks waiting on that audio are answered at once. */
  clear() {
    for (const node of this.sources) {
      try {
        node.stop();
      } catch {
        // already stopped
      }
    }
    this.sources.clear();
    if (this.ctx) this.playhead = this.ctx.currentTime;
    for (const [id, name] of this.markTimers) {
      window.clearTimeout(id);
      this.send({ event: "mark", mark: { name } });
    }
    this.markTimers.clear();
  }

  /** True while the agent's voice is still playing. */
  get speaking(): boolean {
    return !!this.ctx && this.playhead > this.ctx.currentTime + 0.05;
  }

  stop() {
    for (const id of this.markTimers.keys()) window.clearTimeout(id);
    this.markTimers.clear();
    this.node?.port.close();
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close();
    this.ctx = null;
    this.stream = null;
    this.node = null;
  }
}
