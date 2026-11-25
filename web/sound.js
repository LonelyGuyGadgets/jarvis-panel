/* Panel sound: synthesised HUD effects (Web Audio, no files) + spoken alerts fetched from the NUC.
 * Failures are silent by design: no audio hardware, blocked autoplay or a missing voice must never break the panel. */
(function () {
  'use strict';
  const KEY = 'jarvis-sound';
  let enabled = true;
  try { enabled = localStorage.getItem(KEY) !== 'off'; } catch (e) { /* storage blocked: stay on */ }

  let ctx = null, master = null;
  function audio() {
    if (ctx) return ctx;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try {
      ctx = new AC();
      master = ctx.createGain(); master.gain.value = 0.7; master.connect(ctx.destination);
    } catch (e) { ctx = null; }
    return ctx;
  }
  function wake() { const c = audio(); if (c && c.state === 'suspended') c.resume().catch(() => {}); }
  window.addEventListener('pointerdown', wake, { passive: true });

  // one enveloped oscillator note
  function note(freq, start, dur, opts) {
    const c = audio(); if (!c) return;
    const o = c.createOscillator(), g = c.createGain(), f = c.createBiquadFilter();
    const t0 = c.currentTime + start, peak = (opts && opts.gain) || 0.12;
    o.type = (opts && opts.type) || 'sine';
    o.frequency.setValueAtTime(freq, t0);
    if (opts && opts.to) o.frequency.exponentialRampToValueAtTime(opts.to, t0 + dur);
    f.type = 'lowpass'; f.frequency.value = (opts && opts.cutoff) || 6000;
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(peak, t0 + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(f); f.connect(g); g.connect(master);
    o.start(t0); o.stop(t0 + dur + 0.05);
  }

  // a burst of filtered noise: glitches and static
  function noise(start, dur, opts) {
    const c = audio(); if (!c) return;
    const len = Math.max(1, Math.floor(c.sampleRate * dur)), buf = c.createBuffer(1, len, c.sampleRate), d = buf.getChannelData(0);
    const crush = (opts && opts.crush) || 1;                       // >1 holds each sample for a few: a bit-crushed rasp
    for (let i = 0; i < len; i++) d[i] = (i % crush === 0 ? Math.random() * 2 - 1 : d[i - 1]) * (1 - i / len);
    const s = c.createBufferSource(), f = c.createBiquadFilter(), g = c.createGain();
    s.buffer = buf; f.type = 'bandpass'; f.frequency.value = (opts && opts.freq) || 1800; f.Q.value = 0.8;
    g.gain.value = (opts && opts.gain) || 0.2;
    s.connect(f); f.connect(g); g.connect(master); s.start(c.currentTime + start);
  }

  // electricity: a scatter of tiny high-pitched clicks (sparks) and a fast falling zap
  function crackle(start, dur, n, gain) {
    for (let i = 0; i < n; i++) noise(start + Math.random() * dur, 0.006 + Math.random() * 0.02, { freq: 3000 + Math.random() * 5000, gain: gain * (0.4 + Math.random() * 0.6), crush: 1 });
  }
  function zap(start, gain) {
    note(3200, start, 0.16, { to: 160, gain: gain, type: 'sawtooth', cutoff: 6000 });
    noise(start, 0.12, { freq: 5000, gain: gain * 1.4, crush: 2 });
  }
  function arcBuzz(start, dur, gain) {                              // the mains-hum buzz of a live arc
    note(120, start, dur, { gain: gain, type: 'sawtooth', cutoff: 2400 });
    note(180, start, dur, { gain: gain * 0.6, type: 'square', cutoff: 1800 });
  }

  const SFX = {
    glitch: () => { crackle(0, 0.35, 14, 0.22); zap(0.02, 0.07); arcBuzz(0.05, 0.25, 0.05); },
    thump: () => { zap(0, 0.12); zap(0.12, 0.1); zap(0.3, 0.14); crackle(0, 0.9, 30, 0.25); arcBuzz(0.1, 0.8, 0.08); },
    surge: () => { arcBuzz(0, 0.9, 0.09); crackle(0, 0.9, 26, 0.24); zap(0.1, 0.1); zap(0.55, 0.12); },
    victory: () => { note(440, 0, 0.18, { gain: 0.12 }); note(660, 0.14, 0.18, { gain: 0.12 }); note(880, 0.28, 0.5, { gain: 0.13 }); note(1320, 0.4, 0.6, { gain: 0.08 }); },
    tap:   () => note(1500, 0, 0.06, { to: 900, gain: 0.07, type: 'triangle' }),
    ok:    () => { note(660, 0, 0.1, { gain: 0.09 }); note(990, 0.09, 0.16, { gain: 0.09 }); },
    err:   () => note(170, 0, 0.26, { to: 110, gain: 0.12, type: 'sawtooth', cutoff: 900 }),
    warn:  () => { note(880, 0, 0.17, { gain: 0.11, type: 'triangle' }); note(660, 0.19, 0.24, { gain: 0.11, type: 'triangle' }); },
    alarm: () => { for (let i = 0; i < 3; i++) note(520, i * 0.2, 0.14, { to: 470, gain: 0.12, type: 'square', cutoff: 1800 }); },
    boot:  () => { note(220, 0, 0.55, { to: 1100, gain: 0.08, type: 'sawtooth', cutoff: 2500 }); note(1320, 0.5, 0.3, { gain: 0.07 }); },
  };
  function play(name) {
    if (!enabled || !SFX[name]) return;
    try { wake(); SFX[name](); } catch (e) { /* ignore */ }
  }

  // spoken phrases: fetched once per key, decoded, played one at a time
  const decoded = new Map(), queue = [];
  let speaking = false;
  async function load(key) {
    if (decoded.has(key)) return decoded.get(key);
    // 'reply:12' is one of Jarvis's own off-the-cuff answers (generated server-side); anything else is a fixed phrase
    const url = key.startsWith('reply:') ? '/api/voice/reply/' + encodeURIComponent(key.split(':')[1]) : '/api/voice/' + encodeURIComponent(key);
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(resp.status);
    const buf = await audio().decodeAudioData(await resp.arrayBuffer());
    decoded.set(key, buf);
    return buf;
  }
  async function pump() {
    if (speaking) return;
    speaking = true;
    while (queue.length) {
      const key = queue.shift();
      try {
        if (!enabled || !audio()) continue;
        const buf = await load(key);   // replies are cached too, so a repeat is instant
        const vk = window.JarvisLogic.voiceOfKey(key);   // whose voice: a reply carries its speaker, a phrase is its own prefix
        await new Promise((done) => {
          const c = audio(), src = c.createBufferSource();
          src.buffer = buf; src.onended = done;
          if (vk.startsWith('u_')) {
            // Ultron: dropped in pitch, hard-clipped, with a second, lower copy underneath
            src.playbackRate.value = 0.82;
            const ws = c.createWaveShaper(), curve = new Float32Array(512);
            for (let i = 0; i < 512; i++) { const x = i / 256 - 1; curve[i] = Math.tanh(x * 4); }
            ws.curve = curve; ws.oversample = '2x';
            const lo = c.createBufferSource(), lg = c.createGain();
            lo.buffer = buf; lo.playbackRate.value = 0.6; lg.gain.value = 0.55;
            src.connect(ws); ws.connect(master); lo.connect(lg); lg.connect(ws);
            src.start(); lo.start();
          } else if (vk.startsWith('jo_')) {
            // JOCASTA: lower and edged, a cooler cousin of Ultron
            src.playbackRate.value = 0.9;
            const ws = c.createWaveShaper(), curve = new Float32Array(512);
            for (let i = 0; i < 512; i++) { const x = i / 256 - 1; curve[i] = Math.tanh(x * 2); }
            ws.curve = curve; ws.oversample = '2x';
            const lo = c.createBufferSource(), lg = c.createGain();
            lo.buffer = buf; lo.playbackRate.value = 0.72; lg.gain.value = 0.3;
            src.connect(ws); lo.connect(lg); lg.connect(ws); ws.connect(master);
            src.start(); lo.start();
          } else {
            if (vk.startsWith('e_')) src.playbackRate.value = 1.05;        // EDITH: perky
            else if (vk.startsWith('f_')) src.playbackRate.value = 0.98;   // FRIDAY: measured
            src.connect(master); src.start();
          }
          setTimeout(done, buf.duration * 1000 * 1.8 + 800);   // never hang the queue
        });
      } catch (e) { /* silent */ }
    }
    speaking = false;
  }
  let jarvisMuted = false;   // while Ultron reigns only his voice is heard
  function say(key) {
    if (!enabled || queue.includes(key)) return;
    if (jarvisMuted && !/^(u|e|f|jo)_/.test(window.JarvisLogic.voiceOfKey(key)) && !key.startsWith('jv_g_')) return;   // only Ultron, a guest AI, or Jarvis handing over
    if (queue.length >= 4) queue.shift();
    queue.push(key);
    pump();
  }

  // fetch and decode phrases ahead of time so a dramatic moment never stutters on a first-time synthesis
  async function preload(keys) {
    for (const k of keys) { try { if (audio()) await load(k); } catch (e) { /* silent */ } }
  }
  function event(sfx, key) {
    play(sfx);
    if (key) setTimeout(() => say(key), 450);
  }
  function setEnabled(on) {
    enabled = !!on;
    if (!enabled) queue.length = 0;
    try { localStorage.setItem(KEY, enabled ? 'on' : 'off'); } catch (e) { /* ignore */ }
    if (enabled) play('ok');
    return enabled;
  }

  window.Sfx = { play, say, event, preload, setEnabled, muteJarvis(on) { jarvisMuted = !!on; if (on) queue.length = 0; }, get enabled() { return enabled; } };
})();
