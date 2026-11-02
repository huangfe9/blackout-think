"use strict";
window.BlackoutCapture = (function () {
  const WORKLET_CODE = [
    "class BlackoutProcessor extends AudioWorkletProcessor {",
    "  constructor(options) {",
    "    super();",
    "    const opts = (options && options.processorOptions) || {};",
    "    this.mode = opts.mode || 'pcm';",
    "    this.muted = false;",
    "    this.pending = [];",
    "    this.pos = 0;",
    "    this.out = [];",
    "    this.port.onmessage = (event) => {",
    "      if (event.data && event.data.type === 'muted') this.muted = Boolean(event.data.value);",
    "    };",
    "  }",
    "  process(inputs) {",
    "    const input = inputs[0];",
    "    if (!input || !input[0]) return true;",
    "    const channel = input[0];",
    "    if (this.mode === 'float') { this.port.postMessage(channel.slice(0)); return true; }",
    "    for (let i = 0; i < channel.length; i += 1) this.pending.push(this.muted ? 0 : channel[i]);",
    "    const step = sampleRate / 24000;",
    "    while (this.pos + step <= this.pending.length) {",
    "      const start = Math.floor(this.pos);",
    "      const end = Math.max(start + 1, Math.floor(this.pos + step));",
    "      let sum = 0;",
    "      for (let i = start; i < end && i < this.pending.length; i += 1) sum += this.pending[i];",
    "      this.out.push(sum / Math.max(1, end - start));",
    "      this.pos += step;",
    "    }",
    "    const drop = Math.floor(this.pos);",
    "    if (drop > 0) { this.pending.splice(0, drop); this.pos -= drop; }",
    "    while (this.out.length >= 1920) {",
    "      const frame = this.out.splice(0, 1920);",
    "      const pcm = new Int16Array(1920);",
    "      for (let i = 0; i < frame.length; i += 1) {",
    "        const s = Math.max(-1, Math.min(1, frame[i]));",
    "        pcm[i] = s < 0 ? s * 32768 : s * 32767;",
    "      }",
    "      this.port.postMessage(pcm.buffer, [pcm.buffer]);",
    "    }",
    "    return true;",
    "  }",
    "}",
    "registerProcessor('blackout-capture', BlackoutProcessor);"
  ].join("\n");
  let primedCtx = null;
  function stopTracks(stream) {
    try {
      if (stream) {
        stream.getTracks().forEach(function (track) {
          track.stop();
        });
      }
    } catch (e) {}
  }
  function audioCtor() {
    return window.AudioContext || window.webkitAudioContext;
  }
  function prime() {
    // Called synchronously from a user gesture (phones require this):
    // create and resume the shared 24 kHz context and store it for the
    // stream capture, which will own it from then on.
    try {
      const Ctor = audioCtor();
      if (!Ctor) {
        return null;
      }
      if (!primedCtx) {
        primedCtx = new Ctor({ sampleRate: 24000 });
      }
      if (primedCtx.state === "suspended") {
        const pending = primedCtx.resume();
        if (pending && pending.catch) {
          pending.catch(function () {});
        }
      }
      return primedCtx;
    } catch (e) {
      return null;
    }
  }
  async function ensurePermission() {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    });
    stopTracks(stream);
    return true;
  }
  function downsample(samples, srcRate, targetRate) {
    if (srcRate === targetRate) {
      return samples;
    }
    const step = srcRate / targetRate;
    const length = Math.floor(samples.length / step);
    const out = new Float32Array(length);
    for (let i = 0; i < length; i += 1) {
      const start = Math.floor(i * step);
      const end = Math.max(start + 1, Math.floor((i + 1) * step));
      let sum = 0;
      let count = 0;
      for (let j = start; j < end && j < samples.length; j += 1) {
        sum += samples[j];
        count += 1;
      }
      out[i] = count > 0 ? sum / count : 0;
    }
    return out;
  }
  function encodeWav(samples, rate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    function writeText(offset, text) {
      for (let i = 0; i < text.length; i += 1) {
        view.setUint8(offset + i, text.charCodeAt(i));
      }
    }
    writeText(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeText(8, "WAVE");
    writeText(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, rate, true);
    view.setUint32(28, rate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeText(36, "data");
    view.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i += 1) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(44 + i * 2, s < 0 ? s * 32768 : s * 32767, true);
    }
    return new Blob([buffer], { type: "audio/wav" });
  }
  function makeGraph(mode) {
    const graph = {
      stream: null,
      ctx: null,
      node: null,
      source: null,
      url: "",
      rate: 48000
    };
    async function closeContextOnly() {
      try {
        if (graph.node) {
          graph.node.disconnect();
        }
      } catch (e) {}
      try {
        if (graph.source) {
          graph.source.disconnect();
        }
      } catch (e) {}
      graph.node = null;
      graph.source = null;
      if (graph.url) {
        try {
          URL.revokeObjectURL(graph.url);
        } catch (e) {}
        graph.url = "";
      }
      if (graph.ctx) {
        const ctx = graph.ctx;
        graph.ctx = null;
        if (primedCtx === ctx) {
          primedCtx = null;
        }
        try {
          await ctx.close();
        } catch (e) {}
      }
    }
    graph.open = async function (generation, isCurrent, onChunk) {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      });
      if (!isCurrent(generation)) {
        stopTracks(stream);
        return false;
      }
      graph.stream = stream;
      const Ctor = audioCtor();
      let retried = false;
      while (true) {
        try {
          if (mode === "pcm" && primedCtx) {
            graph.ctx = primedCtx;
            primedCtx = null;
          } else if (mode === "pcm" && !retried) {
            graph.ctx = new Ctor({ sampleRate: 24000 });
          } else {
            graph.ctx = new Ctor();
          }
          graph.rate = graph.ctx.sampleRate;
          await graph.ctx.resume();
          const blob = new Blob([WORKLET_CODE], { type: "application/javascript" });
          graph.url = URL.createObjectURL(blob);
          await graph.ctx.audioWorklet.addModule(graph.url);
          if (!isCurrent(generation)) {
            await graph.close();
            return false;
          }
          await graph.ctx.resume();
          graph.source = graph.ctx.createMediaStreamSource(graph.stream);
          graph.node = new AudioWorkletNode(graph.ctx, "blackout-capture", {
            processorOptions: { mode: mode }
          });
          graph.node.port.onmessage = function (event) {
            if (isCurrent(generation)) {
              onChunk(event.data);
            }
          };
          graph.source.connect(graph.node);
          return true;
        } catch (e) {
          const isRateError = Boolean(e && e.name === "NotSupportedError");
          await closeContextOnly();
          if (isRateError && !retried) {
            // Some browsers refuse a stream on a context at a different
            // rate: retry once with a default-rate context. The worklet
            // already downsamples using sampleRate.
            retried = true;
            continue;
          }
          throw e;
        }
      }
    };
    graph.close = async function () {
      await closeContextOnly();
      stopTracks(graph.stream);
      graph.stream = null;
    };
    return graph;
  }
  function createStreamCapture(onFrame) {
    let generation = 0;
    let active = false;
    let muted = false;
    const graph = makeGraph("pcm");
    function isCurrent(gen) {
      return gen === generation && active;
    }
    async function start() {
      const gen = ++generation;
      active = true;
      try {
        const opened = await graph.open(gen, isCurrent, function (data) {
          onFrame(data);
        });
        if (!opened) {
          return false;
        }
        if (graph.node) {
          graph.node.port.postMessage({ type: "muted", value: muted });
        }
        return true;
      } catch (e) {
        if (gen === generation) {
          active = false;
          await graph.close();
          throw e;
        }
        return false;
      }
    }
    function setMuted(value) {
      muted = Boolean(value);
      try {
        if (graph.node) {
          graph.node.port.postMessage({ type: "muted", value: muted });
        }
      } catch (e) {}
    }
    async function stop() {
      generation += 1;
      active = false;
      await graph.close();
    }
    return {
      start: start,
      stop: stop,
      setMuted: setMuted,
      isActive: function () { return active; }
    };
  }
  function createWavRecorder() {
    let generation = 0;
    let active = false;
    let chunks = [];
    const graph = makeGraph("float");
    function isCurrent(gen) {
      return gen === generation && active;
    }
    async function start() {
      const gen = ++generation;
      active = true;
      chunks = [];
      try {
        return await graph.open(gen, isCurrent, function (data) {
          chunks.push(new Float32Array(data));
        });
      } catch (e) {
        if (gen === generation) {
          active = false;
          await graph.close();
          throw e;
        }
        return false;
      }
    }
    async function stop() {
      generation += 1;
      active = false;
      const rate = graph.rate;
      const taken = chunks;
      chunks = [];
      await graph.close();
      let total = 0;
      taken.forEach(function (chunk) {
        total += chunk.length;
      });
      const merged = new Float32Array(total);
      let offset = 0;
      taken.forEach(function (chunk) {
        merged.set(chunk, offset);
        offset += chunk.length;
      });
      return encodeWav(downsample(merged, rate, 16000), 16000);
    }
    async function cancel() {
      generation += 1;
      active = false;
      chunks = [];
      await graph.close();
    }
    return {
      start: start,
      stop: stop,
      cancel: cancel,
      isActive: function () { return active; }
    };
  }
  return { createStreamCapture: createStreamCapture, createWavRecorder: createWavRecorder, prime: prime, ensurePermission: ensurePermission };
})();
