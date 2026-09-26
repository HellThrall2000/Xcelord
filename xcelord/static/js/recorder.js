// Browser-side recording: mono PCM via an AudioWorklet, energy-based
// auto-stop, then resampled to 16 kHz WAV (the format every STT provider takes).

const TARGET_RATE = 16000;
const CALIBRATE_MS = 250;
const SILENCE_MS = 1400;
const NO_SPEECH_MS = 8000;
const MAX_MS = 30000;
const IDLE_RELEASE_MS = 60000; // keep the mic warm briefly for faster follow-ups

const WORKLET = `
class Tap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(1024); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      for (let i = 0; i < ch.length; i++) {
        this.buf[this.n++] = ch[i];
        if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }
      }
    }
    return true;
  }
}
registerProcessor("xcelord-tap", Tap);
`;

export class Recorder {
  constructor({ onLevel, onAutoStop } = {}) {
    this.onLevel = onLevel || (() => {});
    this.onAutoStop = onAutoStop || (() => {});
    this.ctx = null;
    this.stream = null;
    this.node = null;
    this.source = null;
    this.recording = false;
    this.releaseTimer = null;
  }

  async _ensure() {
    clearTimeout(this.releaseTimer);
    if (this.ctx && this.stream?.active) {
      if (this.ctx.state === "suspended") await this.ctx.resume();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser can't record audio. Try Chrome, Edge or Firefox on localhost.");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    this.ctx = new AudioContext();
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await this.ctx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "xcelord-tap");
    this.node.port.onmessage = (e) => this._onChunk(e.data);
    this.source.connect(this.node);
  }

  /** mode: "auto" stops on silence; "hold" records until stop() */
  async start(mode = "auto") {
    await this._ensure();
    this.mode = mode;
    this.chunks = [];
    this.startedAt = performance.now();
    this.noise = 0;
    this.noiseSamples = 0;
    this.speechAt = 0;
    this.lastVoiceAt = 0;
    this.loud = 0;
    this.level = 0;
    this.recording = true;
  }

  _onChunk(chunk) {
    if (!this.recording) return;
    this.chunks.push(chunk);
    let sum = 0;
    for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
    const rms = Math.sqrt(sum / chunk.length);
    const now = performance.now();
    const elapsed = now - this.startedAt;

    this.level = this.level * 0.6 + Math.min(1, rms * 12) * 0.4;
    this.onLevel(this.level);

    if (elapsed < CALIBRATE_MS) {
      this.noise = (this.noise * this.noiseSamples + rms) / (this.noiseSamples + 1);
      this.noiseSamples++;
      return;
    }
    const threshold = Math.max(this.noise * 2.5, 0.012);
    if (rms > threshold) {
      this.loud++;
      this.lastVoiceAt = now;
      if (!this.speechAt && this.loud >= 3) this.speechAt = now;
    } else {
      this.loud = Math.max(0, this.loud - 1);
    }

    if (this.mode !== "auto") {
      if (elapsed > MAX_MS) this.onAutoStop("max");
      return;
    }
    if (!this.speechAt && elapsed > NO_SPEECH_MS) this.onAutoStop("no-speech");
    else if (this.speechAt && now - this.lastVoiceAt > SILENCE_MS) this.onAutoStop("silence");
    else if (elapsed > MAX_MS) this.onAutoStop("max");
  }

  get heardSpeech() {
    return Boolean(this.speechAt);
  }

  /** Stops and returns a 16 kHz WAV blob, or null if nothing useful was captured. */
  async stop() {
    if (!this.recording) return null;
    this.recording = false;
    this.onLevel(0);
    this._scheduleRelease();
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    const minSamples = this.ctx.sampleRate * 0.4;
    // Hold-to-talk trusts the user even if the energy detector missed quiet speech.
    if (total < minSamples || (!this.speechAt && this.mode === "auto")) return null;
    const pcm = new Float32Array(total);
    let offset = 0;
    for (const c of this.chunks) { pcm.set(c, offset); offset += c.length; }
    const resampled = await resample(pcm, this.ctx.sampleRate, TARGET_RATE);
    return encodeWav(trimSilence(resampled, TARGET_RATE), TARGET_RATE);
  }

  cancel() {
    this.recording = false;
    this.chunks = [];
    this.onLevel(0);
    this._scheduleRelease();
  }

  _scheduleRelease() {
    clearTimeout(this.releaseTimer);
    this.releaseTimer = setTimeout(() => this.release(), IDLE_RELEASE_MS);
  }

  release() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close();
    this.ctx = this.stream = this.node = this.source = null;
  }
}

async function resample(pcm, fromRate, toRate) {
  if (fromRate === toRate) return pcm;
  const length = Math.ceil((pcm.length * toRate) / fromRate);
  const offline = new OfflineAudioContext(1, length, toRate);
  const buffer = offline.createBuffer(1, pcm.length, fromRate);
  buffer.copyToChannel(pcm, 0);
  const src = offline.createBufferSource();
  src.buffer = buffer;
  src.connect(offline.destination);
  src.start();
  const rendered = await offline.startRendering();
  return rendered.getChannelData(0);
}

// Drop long leading/trailing silence: smaller uploads, faster transcription.
function trimSilence(pcm, rate) {
  const win = Math.floor(rate * 0.02);
  const pad = Math.floor(rate * 0.25);
  const loud = (i) => {
    let s = 0;
    for (let j = i; j < Math.min(i + win, pcm.length); j++) s += pcm[j] * pcm[j];
    return Math.sqrt(s / win) > 0.01;
  };
  let start = 0;
  while (start < pcm.length && !loud(start)) start += win;
  let end = pcm.length - win;
  while (end > start && !loud(end)) end -= win;
  if (end <= start) return pcm;
  return pcm.subarray(Math.max(0, start - pad), Math.min(pcm.length, end + win + pad));
}

function encodeWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  str(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let o = 44;
  for (let i = 0; i < samples.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}
