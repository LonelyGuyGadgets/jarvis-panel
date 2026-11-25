(function (root) {
  const CYAN = '#2ff3ff', AMBER = '#ffb829', RED = '#ff4d4d';
  const HOLD_MS = 1200, SOFT_HOLD_MS = 450;

  function stateClass(state) {
    switch (state) {
      case 'ok': return 'ok';
      case 'warn': return 'warn';
      case 'stale': return 'warn';
      case 'unconfigured': return 'dim';
      default: return 'bad';
    }
  }

  function coreColor(health, anyBad) {
    if (health < 60) return RED;
    if (health < 90 || anyBad) return AMBER;
    return CYAN;
  }

  function holdProgress(startMs, nowMs, holdMs) {
    const total = holdMs || HOLD_MS;
    const p = (nowMs - startMs) / total;
    return Math.max(0, Math.min(1, p));
  }

  function ageLabel(asOfSeconds, nowSeconds) {
    const s = Math.max(0, Math.round(nowSeconds - asOfSeconds));
    if (s < 120) return s + 's ago';
    if (s < 7200) return Math.floor(s / 60) + 'm ago';
    return Math.floor(s / 3600) + 'h ago';
  }

  const LINK_MAX_AGE_MS = 10000;

  function isLinkLost(lastOkMs, nowMs, maxAgeMs) {
    if (lastOkMs === null || lastOkMs === undefined) return true;
    return nowMs - lastOkMs > (maxAgeMs || LINK_MAX_AGE_MS);
  }

  function effectiveState(state, linkLost) {
    return linkLost ? 'offline' : state;
  }

  // While Pi-hole is paused the button turns into "Enable ad blocking" (a plain tap) until the timer ends and blocking returns.
  function adBlockButton(status) {
    const d = status && status.sources && status.sources.pihole && status.sources.pihole.data;
    if (d && d.blocking === false) return { action: 'resume_pihole', label: 'Enable Pihole', group: 'system', hold: false, holdMs: 0 };
    return { action: 'pause_pihole', label: 'Pause Pihole', group: 'system', hold: true, holdMs: SOFT_HOLD_MS };
  }

  function buttonsFor(status) {
    const abc = (a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' });
    const buttons = [
      { action: 'restart_plex', label: 'Restart Plex', group: 'system', hold: true, holdMs: HOLD_MS },
      { action: 'restart_samba', label: 'Restart Samba', group: 'system', hold: true, holdMs: HOLD_MS },
      adBlockButton(status),
      { action: 'disk_check', label: 'Check disks', group: 'system', hold: false, holdMs: 0 },
    ].sort((a, b) => abc(a.label, b.label));          // every group reads in alphabetical order
    const sh = status && status.sources && status.sources.smart_home;
    if (sh && sh.data) {
      for (const l of [...(sh.data.lights || [])].sort((a, b) => abc(a.name, b.name))) {
        buttons.push({ action: 'lights_toggle_' + l.name, label: l.name, group: 'lights', on: !!l.on,
                       hold: true, holdMs: SOFT_HOLD_MS });
      }
      for (const s of [...(sh.data.speakers || [])].sort((a, b) => abc(a.name, b.name))) {
        if (s.state !== 'playing') continue;      // controls only show while that speaker is playing something
        const group = 'speaker:' + s.name;
        buttons.push({ action: 'volume_down_' + s.name, label: '\u2212', group, hold: true, holdMs: SOFT_HOLD_MS });
        buttons.push({ action: 'play_pause_' + s.name, label: '\u25B6\u2759\u2759', group, hold: true, holdMs: SOFT_HOLD_MS });
        buttons.push({ action: 'volume_up_' + s.name, label: '+', group, hold: true, holdMs: SOFT_HOLD_MS });
      }
    }
    return buttons;
  }

  // Sources the server has spoken phrases for (see jarvis/voice.py).
  const SPOKEN = ['nuc', 'plex', 'disks', 'pihole', 'smart_home'];

  function sourceLevels(sources) {
    const out = {};
    for (const name of SPOKEN) {
      const r = sources && sources[name];
      if (!r || r.state === 'unconfigured') continue;
      out[name] = r.state === 'ok' ? 'ok' : (r.state === 'warn' || r.state === 'stale') ? 'warn' : 'offline';
    }
    return out;
  }

  // What to play/say. prev === null means the first look after the page loads.
  function announcements(prev, curr) {
    const events = [];
    if (prev === null) events.push({ sfx: 'boot', say: 'online' });
    if (prev === null) return events;   // existing problems stay silent; only changes are spoken
    for (const name of Object.keys(curr)) {
      const was = prev[name] === undefined ? 'ok' : prev[name], now = curr[name];
      if (was === now) continue;
      if (now === 'ok') events.push({ sfx: 'ok', say: 'ok_' + name });
      else events.push({ sfx: now === 'warn' ? 'warn' : 'alarm', say: (now === 'warn' ? 'warn_' : 'offline_') + name });
    }
    return events;
  }

  // good morning / afternoon / evening, by local hour
  function greetingKey(hour) {
    return hour >= 5 && hour < 12 ? 'good_morning' : hour >= 12 && hour < 17 ? 'good_afternoon' : 'good_evening';
  }

  // Counts rapid taps; once they stop for settleMs the matching pattern (by tap count) fires once.
  function makeTapCounter(opts, onPattern) {
    let count = 0, last = -Infinity;
    return {
      tap(t) {
        if (t - last > opts.windowMs) count = 0;
        count++; last = t;
      },
      flush(t) {
        if (count > 0 && t - last >= opts.settleMs) {
          const name = opts.patterns[count];
          count = 0;
          if (name) onPattern(name);
        }
      },
    };
  }

  // Dominant vivid colour of an RGBA pixel array (album art): bucket by hue, weight by saturation*value, brighten.
  function pickAccent(px) {
    const B = 12, w = new Array(B).fill(0), sum = Array.from({ length: B }, () => [0, 0, 0]);
    for (let i = 0; i + 3 < px.length; i += 4) {
      const r = px[i] / 255, g = px[i + 1] / 255, b = px[i + 2] / 255;
      const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
      const sat = mx === 0 ? 0 : d / mx;
      if (sat < 0.35 || mx < 0.15) continue;                 // greys and near-black carry no colour
      const h = d === 0 ? 0 : mx === r ? ((g - b) / d + 6) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
      const k = Math.min(B - 1, Math.floor(h / 6 * B)), wt = sat * mx;
      w[k] += wt; sum[k][0] += r * wt; sum[k][1] += g * wt; sum[k][2] += b * wt;
    }
    let best = -1, bw = 0;
    for (let k = 0; k < B; k++) if (w[k] > bw) { bw = w[k]; best = k; }
    if (best < 0) return null;
    let c = sum[best].map((x) => x / bw);
    const top = Math.max(c[0], c[1], c[2]);
    c = c.map((x) => Math.min(1, x * (0.8 / top)));          // lift to a glowing brightness
    return '#' + c.map((x) => Math.round(x * 255).toString(16).padStart(2, '0')).join('');
  }

  // Turns a raw mic level into 0..1 relative to the room: adapts to the noise floor and the loudest recent sound.
  function makeAudioNormalizer() {
    let floor = null, peak = 0;
    return {
      feed(level) {
        if (floor === null) floor = level;
        floor += (level - floor) * (level < floor ? 0.2 : 0.01);     // follow quiet quickly, loud slowly
        peak = Math.max(level, peak * 0.995);
        const span = Math.max(peak - floor, 12);
        return Math.max(0, Math.min(1, (level - floor * 1.15) / span));
      },
    };
  }

  // Screensaver clock: idle after afterMs without a touch. touch() returns true when that touch only woke the screen.
  function makeIdleTimer(opts, onChange) {
    let last = 0;
    const timer = {
      idle: false,
      touch(t) {
        last = t;
        if (!timer.idle) return false;
        timer.idle = false; onChange(false);
        return true;
      },
      poke(t) { timer.touch(t); },      // an event (voice, alert) wakes the screen; nothing to swallow
      tick(t) {
        if (!timer.idle && t - last >= opts.afterMs) { timer.idle = true; onChange(true); }
      },
    };
    return timer;
  }

  // The Ultron takeover: a tug-of-war. control = Jarvis's share (0..1). Taps help him; surges hurt him.
  // Each fight rolls how strong Ultron is: a weak one loses on his own, a strong one beats an idle Jarvis (taps can still win it).
  function fightOdds(r) { return r < 0.5 ? { rate: -0.012 } : { rate: 0.028 }; }
  function makeFight(opts) {
    const o = Object.assign({ start: 0.2, rate: 0.028, tapGain: 0.025 }, opts || {});
    const fight = {
      control: o.start, won: false, lost: false,
      step(dt, taps, surge) {
        if (fight.won || fight.lost) return fight.control;
        fight.control = Math.max(0, Math.min(1, fight.control + o.rate * dt + o.tapGain * taps - surge));
        if (fight.control >= 1) fight.won = true;
        else if (fight.control <= 0) fight.lost = true;
        return fight.control;
      },
    };
    return fight;
  }

  // Rapid taps on the core, by how many: each count starts one easter egg.
  const TAP_PATTERNS = { 3: 'quip', 4: 'guest', 5: 'party', 6: 'tour', 7: 'boot', 9: 'ultron' };

  // Holding a still finger on the core for about two seconds sends whoever is in control away and brings Jarvis back.
  const LONG_PRESS_MS = 1800;
  function isLongPress(heldMs, movedPx) { return heldMs >= LONG_PRESS_MS && movedPx < 12; }

  // An AI's off-the-cuff reply is fetched by id; the key also says whose voice it is in ('reply:12:e_'), so a guest is
  // neither muted as if it were Jarvis nor played with his treatment. Fixed phrases are their own voice (u_..., e_...).
  function replyKey(id, voice) { return 'reply:' + id + (voice ? ':' + voice : ''); }
  function voiceOfKey(key) {
    if (!String(key).startsWith('reply:')) return key;
    return key.split(':')[2] || 'jv_';
  }

  // Font size that makes text measured at basePx come out exactly targetPx wide.
  function fitFontSize(basePx, naturalPx, targetPx) {
    return naturalPx > 0 && targetPx > 0 ? basePx * targetPx / naturalPx : basePx;
  }

  // 24-hour clock time, HH:MM, used for every clock on the panel.
  function militaryTime(d) {
    const two = (n) => String(n).padStart(2, '0');
    return two(d.getHours()) + ':' + two(d.getMinutes());
  }

  // Room temperatures, one entry per room.
  function climateRows(list) {
    return (list || []).map((r) => ({ label: String(r.name).toUpperCase(), temp: r.temp_f + '°', hum: r.humidity + '%' }));
  }

  // Split n buttons over as few lines as fit `max` per line, as evenly as possible (10 over 8 -> 5 + 5, never 8 + 2).
  function balancedRows(n, max) {
    if (n <= 0) return [];
    const rows = Math.ceil(n / max), base = Math.floor(n / rows), extra = n % rows;
    return Array.from({ length: rows }, (_, i) => base + (i < extra ? 1 : 0));
  }

  // A guest AI's stay is saved so it survives a page reload; it resumes only while it is still running.
  function activeGuest(raw, now) {
    try {
      const g = JSON.parse(raw);
      if (g && typeof g.id === 'string' && g.until > now) return g;
    } catch (e) { /* not ours */ }
    return null;
  }

  const api = { stateClass, coreColor, holdProgress, ageLabel, buttonsFor, isLinkLost, effectiveState, sourceLevels, announcements, greetingKey, makeTapCounter, pickAccent, makeAudioNormalizer, makeIdleTimer, makeFight, fightOdds, activeGuest, climateRows, balancedRows, militaryTime, fitFontSize, replyKey, voiceOfKey, TAP_PATTERNS, isLongPress, LONG_PRESS_MS, HOLD_MS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.JarvisLogic = api;
})(typeof window !== 'undefined' ? window : globalThis);
