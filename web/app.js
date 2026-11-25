(function () {
  const L = window.JarvisLogic;
  const $ = (id) => document.getElementById(id);
  let lastStatus = null;
  let lastOkMs = null;
  let linkLost = true;
  let polling = false;
  let prevRunning = [];
  let buttonKey = '';
  let prevLevels = null;
  let lastVoiceId = null;   // null until the first status, so a page load never replays an old exchange
  let linkAnnounced = false;
  const sfx = (n) => { if (window.Sfx) window.Sfx.play(n); };
  const sfxEvent = (n, say) => { if (window.Sfx) window.Sfx.event(n, say); };

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function row(label, value, cls) {
    const r = el('div', 'row');
    r.append(el('span', null, label), el('span', 'v ' + (cls || ''), value));
    return r;
  }
  function bar(pct) {
    const b = el('div', 'bar'); const i = el('i'); i.style.width = Math.max(0, Math.min(100, pct)) + '%';
    b.append(i); return b;
  }
  function panel(id, source, fill) {
    const p = $(id), body = p.querySelector('.body'), tag = p.querySelector('.tag');
    body.replaceChildren();
    if (!source) { p.className = 'pnl bad'; tag.textContent = 'NO DATA'; return; }
    const state = L.effectiveState(source.state, linkLost);
    p.className = 'pnl ' + L.stateClass(state);
    const now = Date.now() / 1000;
    tag.textContent = state === 'ok' ? '' :
      state === 'stale' ? 'STALE ' + L.ageLabel(source.as_of, now) :
      state === 'unconfigured' ? 'NOT SET UP' : state.toUpperCase();
    if (state === 'offline' || state === 'unconfigured') return;
    fill(body, source.data || {});
  }
  const pct = (n) => (n === null || n === undefined) ? '--' : Math.round(n) + '%';

  // Room temperatures: a quiet line under the title bar, no box.
  function renderClimate(list) {
    const host = $('climate'); host.replaceChildren();
    for (const r of L.climateRows(list)) {
      const item = el('span', 'cl');
      item.append(el('i', null, r.label), el('b', null, r.temp), el('u', null, r.hum));
      host.append(item);
    }
  }

  // On power-up Jarvis follows the greeting with a spoken rundown of every system. The server builds the text and
  // publishes it as a reply, which the next status poll plays. The tour is a demo, so it stays quiet.
  function briefMe() {
    try { if (new URLSearchParams(location.search).has('tour')) return; } catch (e) { /* ignore */ }
    fetch('/api/briefing', { method: 'POST' }).catch(() => { /* silent by design, like the rest of the audio */ });
  }

  function render(status) {
    const s = status.sources;
    panel('p-nuc', s.nuc, (b, d) => {
      b.append(row('CPU', pct(d.cpu_percent)), bar(d.cpu_percent || 0),
               row('RAM', pct(d.ram_percent)), bar(d.ram_percent || 0),
               row('TEMP', d.temp_c === null || d.temp_c === undefined ? '--' : d.temp_c + '°C',
                   d.temp_c > 85 ? 'bad' : d.temp_c > 75 ? 'warn' : ''));
    });
    panel('p-plex', s.plex, (b, d) => {
      b.append(row('SERVER', 'ONLINE'), row('STREAMS', d.streams === null || d.streams === undefined ? '--' : String(d.streams)));
    });
    panel('p-disks', s.disks, (b, d) => {
      b.append(row('POOL', d.pool, d.pool === 'OK' ? '' : 'warn'),
               row('PARITY', d.parity, d.parity === 'OK' ? '' : 'warn'),
               row('FREE', d.free_gb === null || d.free_gb === undefined ? '--' : Math.round(d.free_gb) + ' GB'));
    });
    renderClimate(s.smart_home && s.smart_home.data && s.smart_home.state === 'ok' ? s.smart_home.data.climate : null);
    panel('p-pihole', s.pihole, (b, d) => {
      b.append(row('BLOCKED TODAY', d.blocked_today.toLocaleString()), bar(d.block_percent),
               row('BLOCK RATE', Math.round(d.block_percent) + '%'),
               row('BLOCKING', d.blocking ? 'ON' : 'PAUSED', d.blocking ? '' : 'warn'));
    });
    panel('p-lights', s.smart_home, (b, d) => {
      const total = d.lights.length, on = d.lights.filter((l) => l.on).length;
      if (!total) { b.append(row('NONE CONFIGURED', '')); return; }
      b.append(row('ON', on + ' / ' + total), bar(on / total * 100));
      const lit = d.lights.filter((x) => x.on);
      if (lit.length <= 4) {
        for (const l of lit) b.append(row(l.name.toUpperCase(), 'ON'));
      } else {                                   // many lights on: every one is listed, two to a line so the box stays short
        const grid = document.createElement('div'); grid.className = 'lit2';
        for (const l of lit) { const s = document.createElement('span'); s.textContent = l.name.toUpperCase(); grid.append(s); }
        b.append(grid);
      }
      if (!on) b.append(row('ALL OFF', ''));
    });
    panel('p-audio', s.smart_home, (b, d) => {
      if (!d.speakers.length) { b.append(row('NONE CONFIGURED', '')); return; }
      const active = d.speakers.filter((x) => x.state === 'playing' || x.state === 'paused');
      b.append(row('ACTIVE', active.length + ' / ' + d.speakers.length));
      for (const sp of active.slice(0, 3)) {
        b.append(row(sp.name.toUpperCase(), sp.state.toUpperCase() + (sp.volume === null ? '' : ' \u00b7 ' + sp.volume + '%')));
      }
      if (!active.length) b.append(row('ALL QUIET', ''));
    });
    const levels = L.sourceLevels(s);
    for (const ev of L.announcements(prevLevels, levels)) {
      sfxEvent(ev.sfx, ev.say === 'online' ? L.greetingKey(new Date().getHours()) : ev.say);
      if (ev.say === 'online') briefMe();
      if ((ev.sfx === 'warn' || ev.sfx === 'alarm') && window.Fun) window.Fun.wake();   // problems wake the screen
    }
    prevLevels = levels;
    const v = status.voice;
    if (lastVoiceId !== null && v && v.id !== lastVoiceId) {
      if (window.Holo) window.Holo.pulse();
      if (window.Fun) window.Fun.wake();
      if (v.kind === 'mute') {
        setSound(!!v.on);
      } else if (v.kind === 'switch') {
        if (window.Fun) window.Fun.switchTo(v.who);    // "let me talk to EDITH": the hand-over has its own sounds and lines
      } else {
        sfx('ok');
        for (const key of v.say) if (window.Sfx) window.Sfx.say(key);
        if (v.reply_id && window.Sfx) window.Sfx.say(L.replyKey(v.reply_id, v.reply_voice));
      }
    }
    lastVoiceId = v ? v.id : 0;
    if (window.Fun) window.Fun.update(status);
    const anyBad = Object.values(s).some((x) => x.state === 'warn' || x.state === 'stale' || x.state === 'offline');
    const color = L.coreColor(status.health, anyBad);
    $('core').style.setProperty('--c', color);
    $('health').textContent = status.health + '%';
    setHealthRing(status.health);
    if (window.Holo) window.Holo.update(status, false, color);
    $('verdict').textContent = color === '#2ff3ff' ? 'SYSTEMS NOMINAL' : color === '#ffb829' ? 'ATTENTION' : 'CRITICAL';
    const running = status.running || [];
    const link = $('link');
    link.textContent = running.length ? 'ONLINE // RUNNING ' + running.join(', ').toUpperCase() : 'ONLINE';
    link.className = '';
    for (const name of prevRunning) {
      if (!running.includes(name)) {
        const last = (status.last_actions || {})[name];
        if (last) toast(name + ' finished: ' + last.status + (last.message ? ' - ' + last.message : ''), last.status !== 'done');
      }
    }
    prevRunning = running;
    renderButtons(status);
  }

  function showLinkLost() {
    const link = $('link'); link.textContent = 'LINK LOST'; link.className = 'bad';
    $('core').style.setProperty('--c', '#ff4d4d');
    $('verdict').textContent = 'NO LINK TO NUC';
    $('health').textContent = '--';
    setHealthRing(0);
    if (window.Holo) window.Holo.update(null, true, '#ff4d4d');
    if (lastStatus) {
      const s = lastStatus.sources;
      for (const [id, key] of [['p-nuc', 'nuc'], ['p-plex', 'plex'], ['p-disks', 'disks'], ['p-pihole', 'pihole'],
                               ['p-lights', 'smart_home'], ['p-audio', 'smart_home']]) {
        panel(id, s[key], () => {});
      }
    }
  }

  function toast(msg, isErr) {
    const t = $('toast'); t.textContent = msg; t.className = 'toast show' + (isErr ? ' err' : '');
    clearTimeout(toast.t); toast.t = setTimeout(() => { t.className = 'toast'; }, Math.max(3500, msg.length * 70));
  }

  async function send(btn, def) {
    btn.classList.add('busy');
    try {
      const resp = await fetch('/api/action/' + encodeURIComponent(def.action), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) });
      const body = await resp.json().catch(() => ({ message: 'bad reply' }));
      const ok = resp.ok;
      sfx(ok ? 'ok' : 'err');
      btn.classList.remove('busy'); btn.classList.add(ok ? 'ok' : 'err');
      toast(def.label + ': ' + (body.message || body.status), !ok);
      setTimeout(() => btn.classList.remove('ok', 'err'), 1800);
      poll();
    } catch (e) {
      btn.classList.remove('busy'); btn.classList.add('err');
      sfx('err');
      toast(def.label + ': no link to NUC', true);
      setTimeout(() => btn.classList.remove('err'), 1800);
    }
  }

  function attach(btn, def) {
    const fill = btn.querySelector('.fill');
    let start = 0, raf = 0;
    const stop = () => { cancelAnimationFrame(raf); start = 0; fill.style.width = '0'; };
    btn.addEventListener('pointerdown', (ev) => {
      ev.preventDefault();
      sfx('tap');
      if (!def.hold) { send(btn, def); return; }
      start = performance.now();
      const tick = () => {
        const p = L.holdProgress(start, performance.now(), def.holdMs);
        fill.style.width = (p * 100) + '%';
        if (p >= 1) { stop(); send(btn, def); } else raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    });
    ['pointerup', 'pointerleave', 'pointercancel'].forEach((n) => btn.addEventListener(n, stop));
  }

  const btnEls = {};
  const TICKS = 60, CIRC = 2 * Math.PI * 78;
  (function buildTicks() {
    const g = $('ticks'), NS = 'http://www.w3.org/2000/svg';
    for (let i = 0; i < TICKS; i++) {
      const a = (i / TICKS) * 2 * Math.PI - Math.PI / 2, major = i % 5 === 0;
      const r1 = major ? 83 : 85, r2 = 90;
      const t = document.createElementNS(NS, 'line');
      t.setAttribute('x1', 100 + r1 * Math.cos(a)); t.setAttribute('y1', 100 + r1 * Math.sin(a));
      t.setAttribute('x2', 100 + r2 * Math.cos(a)); t.setAttribute('y2', 100 + r2 * Math.sin(a));
      t.setAttribute('class', 'tick');
      t.style.transitionDelay = (i * 18) + 'ms';
      g.append(t);
    }
  })();
  function setHealthRing(pct) {
    const p = Math.max(0, Math.min(100, pct || 0));
    $('arc').style.strokeDashoffset = String(CIRC * (1 - p / 100));
    const lit = Math.round(p / 100 * TICKS);
    $('ticks').childNodes.forEach((t, i) => t.classList.toggle('on', i < lit));
  }

  function makeButton(def) {
    const b = el('button', 'btn'); b.type = 'button';
    b.append(el('div', 'fill'), el('span', null, def.label));
    attach(b, def);
    btnEls[def.action] = b;
    return b;
  }

  function renderButtons(status) {
    const defs = L.buttonsFor(status);
    const key = defs.map((d) => d.action).join('|');
    if (key !== buttonKey) {            // structure changed: rebuild once
      buttonKey = key;
      for (const k of Object.keys(btnEls)) delete btnEls[k];
      const host = $('btns'); host.replaceChildren();
      const sys = [], lights = [], clusters = {}, audio = [];
      for (const def of defs) {
        if (def.group === 'system') sys.push(makeButton(def));
        else if (def.group === 'lights') lights.push(makeButton(def));
        else {
          const name = def.group.slice('speaker:'.length);
          if (!clusters[name]) {
            clusters[name] = el('div', 'spk');
            clusters[name].append(el('div', 'spk-name', name));
            audio.push(clusters[name]);
          }
          clusters[name].append(makeButton(def));
        }
      }
      // every group is centred and split into evenly sized lines (10 lights -> 5 + 5), all buttons the same width
      const addRows = (items, max, cls, min) => {
        const sizes = L.balancedRows(items.length, max), n = Math.max(...sizes, min);
        let at = 0;
        for (const size of sizes) {
          const line = el('div', 'grp ' + cls); line.style.setProperty('--n', n);
          line.append(...items.slice(at, at + size)); at += size; host.append(line);
        }
      };
      addRows(sys, 5, 'sys', 5); addRows(lights, 8, 'lights', 1); addRows(audio, 5, 'audio', 5);
    }
    for (const def of defs) {           // state changes: update in place, never interrupts a hold
      const b = btnEls[def.action];
      if (b && def.group === 'lights') b.classList.toggle('lit', def.on);
    }
  }

  async function poll() {
    if (polling) return;
    polling = true;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 6000);
    try {
      const resp = await fetch('/api/status', { cache: 'no-store', signal: ctl.signal });
      if (!resp.ok) throw new Error(resp.status);
      lastStatus = await resp.json();
      lastOkMs = Date.now();
      const wasLost = linkLost;
      linkLost = false;
      if (wasLost && linkAnnounced) { linkAnnounced = false; sfxEvent('ok', 'link_restored'); }
      render(lastStatus);
    } catch (e) {
      /* the watchdog below decides when the link counts as lost */
    } finally {
      clearTimeout(timer);
      polling = false;
    }
  }

  function watchdog() {
    const lost = L.isLinkLost(lastOkMs, Date.now());
    if (lost && !linkLost) { linkLost = true; showLinkLost(); if (lastStatus) { linkAnnounced = true; sfxEvent('alarm', 'link_lost'); } }
    else if (lost) { showLinkLost(); }
  }

  function clock() {
    const d = new Date();
    $('clock').textContent = (d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) + ', ' + L.militaryTime(d)).toUpperCase();
  }
  const THEMES = ['mono', 'cyan', 'matrix', 'violet', 'ice', 'magenta', 'ocean', 'lime', 'ember', 'rose'];
  function applyTheme(name, persist) {
    if (!THEMES.includes(name)) name = 'cyan';
    document.documentElement.dataset.theme = name;
    try { if (persist !== false) localStorage.setItem('jarvis-theme', name); } catch (e) { /* storage blocked: theme just won't persist */ }
    const cs = getComputedStyle(document.documentElement);
    if (window.Holo && window.Holo.setTheme) window.Holo.setTheme(cs.getPropertyValue('--cyan').trim(), cs.getPropertyValue('--cyan-dim').trim());
  }
  let saved = null;
  try { saved = new URLSearchParams(location.search).get('theme') || localStorage.getItem('jarvis-theme'); } catch (e) { /* ignore */ }
  applyTheme(saved);
  $('title').addEventListener('pointerdown', () => {
    applyTheme(THEMES[(THEMES.indexOf(document.documentElement.dataset.theme) + 1) % THEMES.length]);
    toast('THEME: ' + document.documentElement.dataset.theme.toUpperCase());
  });
  const FONTS = ['chakra-petch', 'default', 'orbitron', 'rajdhani', 'share-tech-mono', 'exo-2'];
  const BTNS = ['glass', 'pill', 'box', 'chamfer', 'bracket', 'solid'];
  function cycler(attr, key, label, list, tap, stop) {
    const apply = (name) => {
      if (!list.includes(name)) name = list[0];
      document.documentElement.dataset[attr] = name;
      try { localStorage.setItem('jarvis-' + key, name); } catch (e) { /* storage blocked */ }
    };
    let v = null;
    try { v = new URLSearchParams(location.search).get(key) || localStorage.getItem('jarvis-' + key); } catch (e) { /* ignore */ }
    apply(v);
    tap.addEventListener('pointerdown', (ev) => {
      if (stop) ev.stopPropagation();
      apply(list[(list.indexOf(document.documentElement.dataset[attr]) + 1) % list.length]);
      toast(label + ': ' + document.documentElement.dataset[attr].replace(/-/g, ' ').toUpperCase());
    });
  }
  cycler('font', 'font', 'FONT', FONTS, $('clock'), false);
  cycler('btn', 'btn', 'BUTTONS', BTNS, $('link'), true);
  function showMute() { $('mute').classList.toggle('off', !(window.Sfx && window.Sfx.enabled)); }
  function setSound(on) {        // the speaker icon and "Jarvis, mute" both come here; the choice is remembered per browser
    if (window.Sfx) window.Sfx.setEnabled(on);
    showMute();
    toast(on ? 'VOICE ON' : 'VOICE MUTED');
  }
  $('mute').addEventListener('pointerdown', (ev) => { ev.stopPropagation(); setSound(!(window.Sfx && window.Sfx.enabled)); });
  showMute();
  if (window.Fun) {
    window.Fun.init({ toast, sfx, poll, themes: THEMES, setTheme: applyTheme,
                      currentTheme: () => document.documentElement.dataset.theme });
    window.Fun.start();
  }
  clock(); setInterval(clock, 15000);
  poll(); setInterval(poll, 3000); setInterval(watchdog, 1000);
})();
