// One phone call to the gateway: microphone up, Rook's voice down.
//
// The audio worklets, resampler and ring-buffer playback are adapted from
// Boson's higgs-realtime-tutorial (Apache 2.0). The difference is that here the
// browser never talks to Boson: raw PCM16 goes to our gateway over one
// WebSocket, as binary frames, and JSON text frames carry UI events.
import captureSource from "./worklets/capture-processor.js?raw";
import playbackSource from "./worklets/playback-processor.js?raw";
import { addWorkletModule } from "./loadWorklet";
import { createResampler, floatTo16BitPCM } from "./resample";

const RATE = 24000;

export type GatewayEvent =
  | { type: "ready" }
  | { type: "audio_start"; item_id: string }
  | { type: "flush" }
  | { type: "transcript"; speaker: "rook" | "caller"; item_id: string; text: string; final: boolean }
  | { type: "tool"; name: string; args: Record<string, unknown> }
  | { type: "case"; case_id: string }
  | { type: "error"; error: unknown }
  | { type: "ended"; reason: string };

export interface CallCallbacks {
  onEvent: (ev: GatewayEvent) => void;
  onLevel?: (rms: number) => void;
  onSpeaking?: (speaking: boolean) => void;
  onClose?: () => void;
}

export class Call {
  private ws: WebSocket | null = null;
  private micCtx: AudioContext | null = null;
  private outCtx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private player: AudioWorkletNode | null = null;
  private itemId: string | null = null;

  constructor(private readonly cb: CallCallbacks) {}

  /** Must be called from a click handler, or the browser keeps audio suspended. */
  async start(): Promise<void> {
    await this.startPlayback();
    const ws = new WebSocket(`${import.meta.env.VITE_GATEWAY_URL}/ws/call`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onmessage = (e) => {
      if (typeof e.data === "string") this.onEvent(JSON.parse(e.data));
      else this.enqueue(e.data as ArrayBuffer);
    };
    ws.onclose = () => this.cb.onClose?.();
    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error("Could not reach the gateway"));
    });
    await this.startMic();
  }

  async stop(): Promise<void> {
    this.ws?.close();
    // Stopping the tracks is what turns off the browser's recording indicator.
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.micCtx?.close();
    await this.outCtx?.close();
    this.ws = this.micCtx = this.outCtx = this.stream = this.player = null;
  }

  // ---- Rook's voice ------------------------------------------------------

  private async startPlayback() {
    // Same rate as the API, so one sample received is one sample played and
    // the played-sample count converts exactly to milliseconds.
    const ctx = new AudioContext({ sampleRate: RATE });
    await addWorkletModule(ctx, playbackSource);
    const node = new AudioWorkletNode(ctx, "playback-processor", {
      numberOfInputs: 0,
      numberOfOutputs: 1,
      outputChannelCount: [1],
    });
    node.port.onmessage = (e) => {
      const d = e.data as { type: string; played?: number; dropped?: number };
      if (d.type === "flushed") {
        // Tell the gateway how much of the reply the caller really heard.
        this.send({
          type: "flushed",
          item_id: this.itemId,
          played_ms: ((d.played ?? 0) / RATE) * 1000,
          dropped: d.dropped ?? 0,
        });
      }
      if (d.type === "flushed" || d.type === "drained") this.cb.onSpeaking?.(false);
    };
    node.connect(ctx.destination);
    if (ctx.state === "suspended") await ctx.resume();
    this.outCtx = ctx;
    this.player = node;
  }

  private enqueue(buf: ArrayBuffer) {
    this.player?.port.postMessage({ type: "samples", payload: buf }, [buf]);
    this.cb.onSpeaking?.(true);
  }

  private onEvent(ev: GatewayEvent) {
    if (ev.type === "audio_start") {
      this.itemId = ev.item_id;
      this.player?.port.postMessage({ type: "reset" });
    } else if (ev.type === "flush") {
      // The caller started talking over Rook: stop within a few milliseconds.
      this.player?.port.postMessage({ type: "flush" });
    }
    this.cb.onEvent(ev);
  }

  // ---- microphone --------------------------------------------------------

  private async startMic() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: true, channelCount: 1 },
    });
    const ctx = new AudioContext();
    this.micCtx = ctx;
    await addWorkletModule(ctx, captureSource);
    const resampler = createResampler(ctx.sampleRate, RATE);
    const source = ctx.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(ctx, "capture-processor", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
    });
    node.port.onmessage = (e: MessageEvent) => {
      const frame = new Float32Array(e.data as ArrayBuffer);
      if (this.cb.onLevel) {
        let sum = 0;
        for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
        this.cb.onLevel(Math.sqrt(sum / frame.length));
      }
      const resampled = resampler.process(frame);
      if (resampled.length && this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(floatTo16BitPCM(resampled));
      }
    };
    // The worklet only runs while connected to something that pulls on it.
    source.connect(node);
    node.connect(ctx.destination);
    if (ctx.state === "suspended") await ctx.resume();
  }

  private send(msg: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }
}
