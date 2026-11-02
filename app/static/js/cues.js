"use strict";
window.BlackoutCues = (function () {
  let sharedCtx = null;
  function ensure() {
    try {
      if (!sharedCtx) {
        const Ctor = window.AudioContext || window.webkitAudioContext;
        if (!Ctor) {
          return null;
        }
        sharedCtx = new Ctor();
      }
      if (sharedCtx.state === "suspended") {
        const pending = sharedCtx.resume();
        if (pending && pending.catch) {
          pending.catch(function () {});
        }
      }
      return sharedCtx;
    } catch (e) {
      return null;
    }
  }
  function tone(startFreq, endFreq, duration, volume, delay) {
    try {
      const ctx = ensure();
      if (!ctx) {
        return;
      }
      const startAt = ctx.currentTime + (delay || 0);
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(startFreq, startAt);
      osc.frequency.linearRampToValueAtTime(endFreq, startAt + duration);
      gain.gain.setValueAtTime(volume, startAt);
      gain.gain.linearRampToValueAtTime(0.0001, startAt + duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(startAt);
      osc.stop(startAt + duration + 0.02);
    } catch (e) {}
  }
  function tick() {
    tone(880, 880, 0.05, 0.015, 0);
  }
  function chime() {
    tone(660, 660, 0.09, 0.03, 0);
    tone(880, 880, 0.11, 0.03, 0.1);
  }
  function rise() {
    tone(620, 880, 0.12, 0.05, 0);
  }
  function fall() {
    tone(880, 520, 0.12, 0.05, 0);
  }
  return { ensure: ensure, tick: tick, chime: chime, rise: rise, fall: fall };
})();
