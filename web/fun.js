/* The fun layer: now-playing strip + album-coloured core, a core that pulses to the room's sound (via the Surface listener),
 * a boot sequence, and tap easter eggs. Everything here is optional: if a piece fails the panel carries on. */
(function () {
  'use strict';
  const L = window.JarvisLogic;
  const $ = (id) => document.getElementById(id);
  const host = { toast() {}, sfx() {}, poll() {}, setTheme() {}, themes: [], currentTheme() { return ''; } };
  let lastStatus = null;

  // ---------------------------------------------------------------- now playing
  const np = $('np'), art = $('np-art');
  let npKey = '';
  const tint = (c) => { if (window.Holo && !document.documentElement.classList.contains('ultron') && !document.documentElement.classList.contains('guest')) window.Holo.setTint(c); };
  function nowPlaying(status) {
    const sm = status && status.sources && status.sources.smart_home;
    const speakers = (sm && sm.data && sm.data.speakers) || [];
    const sp = speakers.find((x) => x.state === 'playing' && x.title);
    if (!sp) {
      if (npKey) { npKey = ''; np.classList.remove('show'); tint(null); }
      return;
    }
    const key = sp.name + '|' + sp.title + '|' + sp.artist;
    np.classList.add('show');
    if (key === npKey) return;
    npKey = key;
    $('np-title').textContent = sp.title;
    $('np-artist').textContent = sp.artist || '';
    $('np-room').textContent = sp.name.toUpperCase();
    art.style.display = 'none';
    tint(null);
    if (!sp.art) return;
    const img = new Image();
    img.onload = () => {
      if (npKey !== key) return;
      art.src = img.src; art.style.display = '';
      try {
        const c = document.createElement('canvas'); c.width = c.height = 24;
        const g = c.getContext('2d'); g.drawImage(img, 0, 0, 24, 24);
        const c2 = L.pickAccent(g.getImageData(0, 0, 24, 24).data);
        tint(c2);
      } catch (e) { /* tainted or unsupported: no tint */ }
    };
    img.onerror = () => { /* no art: title and artist still show */ };
    img.src = '/api/art/' + encodeURIComponent(sp.name) + '?t=' + encodeURIComponent(sp.title);
  }

  // ---------------------------------------------------------------- the core listens to the room
  let partyUntil = 0;
  // The Surface listener reports the room's loudness to the server; the panel polls it (no browser mic access needed).
  function startAudio() {
    const norm = L.makeAudioNormalizer();
    let busy = false;
    setInterval(async () => {
      if (busy || !window.Holo || performance.now() < partyUntil) return;
      busy = true;
      try {
        const r = await fetch('/api/audio-level', { cache: 'no-store' });
        const j = await r.json();
        window.Holo.setAudio(j.fresh ? norm.feed(j.level) : 0);
      } catch (e) { window.Holo.setAudio(0); }
      busy = false;
    }, 110);
  }

  // ---------------------------------------------------------------- boot sequence
  const LINES = [['CORE', null], ['NUC LINK', 'nuc'], ['PLEX', 'plex'], ['DISK ARRAY', 'disks'],
                 ['PI-HOLE', 'pihole'], ['SMART HOME', 'smart_home'], ['VOICE', null]];
  let bootEl = null, bootTimers = [];
  function endBoot() {
    bootTimers.forEach(clearTimeout); bootTimers = [];
    if (!bootEl) return;
    const b = bootEl; bootEl = null;
    b.classList.add('out'); setTimeout(() => b.remove(), 700);
  }
  function boot() {
    if (bootEl) return;
    bootEl = document.createElement('div'); bootEl.id = 'boot';
    const log = document.createElement('div'); log.className = 'boot-log';
    const head = document.createElement('div'); head.className = 'boot-head'; head.textContent = 'L.A.B. // J.A.R.V.I.S.';
    log.append(head);
    bootEl.append(log); document.body.append(bootEl);
    bootEl.addEventListener('pointerdown', endBoot);
    host.sfx('boot');
    LINES.forEach(([label, key], i) => {
      bootTimers.push(setTimeout(() => {
        if (!bootEl) return;
        const st = key && lastStatus && lastStatus.sources[key] ? lastStatus.sources[key].state : 'ok';
        const word = st === 'ok' || st === 'unconfigured' ? 'ONLINE' : st === 'warn' || st === 'stale' ? 'ATTENTION' : 'OFFLINE';
        const row = document.createElement('div');
        row.className = 'boot-row ' + (word === 'ONLINE' ? '' : word === 'ATTENTION' ? 'warn' : 'bad');
        const a = document.createElement('span'); a.textContent = label;
        const b = document.createElement('span'); b.textContent = word;
        row.append(a, b); log.append(row);
      }, 350 + i * 330));
    });
    bootTimers.push(setTimeout(endBoot, 350 + LINES.length * 330 + 700));
  }

  // ---------------------------------------------------------------- the Ultron takeover
  // A battle picks a random script from the server. Ultron may win: then the screen stays red and Jarvis stays quiet
  // (remembered across reloads) until the next battle, which uses a "rebel" script where Jarvis fights his way back.
  const REIGN_KEY = 'jarvisUltronReign';
  let scripts = null, fight = null, fightIv = 0, tapsPending = 0, ultronEl = null, reigning = false;
  const root = document.documentElement;
  const later = (ms, fn) => setTimeout(fn, ms);
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  const lastPick = {};                          // like pick, but never the same thing twice in a row for a given slot
  const pickFresh = (a, slot) => { let v = pick(a); if (a.length > 1) while (v === lastPick[slot]) v = pick(a); lastPick[slot] = v; return v; };
  const isU = (k) => k.startsWith('u_');
  async function getScripts() {
    if (scripts) return scripts;
    try { const r = await fetch('/api/ultron/scripts', { cache: 'no-store' }); if (r.ok) scripts = await r.json(); } catch (e) { /* offline */ }
    return scripts;
  }
  function recolour() {
    const cs = getComputedStyle(root);
    if (window.Holo) window.Holo.setTheme(cs.getPropertyValue('--cyan').trim(), cs.getPropertyValue('--cyan-dim').trim());
  }
  function setRed(on) {
    root.classList.toggle('ultron', on);
    recolour();
    if (window.Holo) window.Holo.setTint(on ? '#ff2a3a' : null);
    if (!on) npKey = '';                       // let a playing album re-tint the core on the next update
  }
  // An AI asked for by voice keeps the panel until Bob asks for someone else: no fights, no timed hand-back.
  const HELD_KEY = 'jarvisHeld', FOREVER_MS = 365 * 864e5;
  let held = false;
  function setHeld(on) {
    held = on;
    try { if (on) localStorage.setItem(HELD_KEY, '1'); else localStorage.removeItem(HELD_KEY); } catch (e) { /* ignore */ }
  }
  // The server answers voice commands in the voice of whoever has the panel, so it is told each time that changes.
  function reportControl() {
    const who = guest ? guest.id : reigning ? 'ultron' : null;
    try { fetch('/api/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ speaker: who }) }).catch(() => {}); } catch (e) { /* offline */ }
  }
  function setReign(on) {
    reigning = on;
    try { if (on) localStorage.setItem(REIGN_KEY, '1'); else localStorage.removeItem(REIGN_KEY); } catch (e) { /* ignore */ }
    if (!on) setHeld(false);
    root.classList.toggle('reign', on);
    setRed(on);
    if (window.Sfx) window.Sfx.muteJarvis(on);
    const who = document.getElementById('who');                  // his name sits in the corner, like a guest's
    if (who && !guest) { who.textContent = on ? 'ULTRON' : ''; fitWho(); }
    reportControl();
  }
  function arcCanvas() {
    let cv = document.getElementById('u-arcs');
    if (!cv) { cv = document.createElement('canvas'); cv.id = 'u-arcs'; cv.className = 'u-arcs'; document.body.append(cv); }
    return cv;
  }
  // lightning: jagged bolts from the core (or the screen edges) with a few flying sparks
  function arcs(n) {
    const cv = arcCanvas();
    const W = cv.width = window.innerWidth, H = cv.height = window.innerHeight, c = cv.getContext('2d');
    c.clearRect(0, 0, W, H); c.lineCap = 'round'; c.lineJoin = 'round';
    const bolt = (x0, y0, x1, y1, width, depth) => {
      const pts = [[x0, y0]], segs = 12 + Math.floor(Math.random() * 8), dx = x1 - x0, dy = y1 - y0, len = Math.hypot(dx, dy) || 1;
      for (let i = 1; i < segs; i++) {
        const t = i / segs, j = (Math.random() - 0.5) * len * 0.16;
        pts.push([x0 + dx * t - dy / len * j, y0 + dy * t + dx / len * j]);
      }
      pts.push([x1, y1]);
      [['rgba(255,40,60,.35)', width * 6], ['rgba(255,120,140,.8)', width * 2.4], ['#fff', width]].forEach(([col, w]) => {
        c.strokeStyle = col; c.lineWidth = w; c.beginPath();
        pts.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.stroke();
      });
      if (depth < 2 && Math.random() < 0.7) {
        const p = pts[Math.floor(pts.length * (0.3 + Math.random() * 0.4))];
        bolt(p[0], p[1], p[0] + (Math.random() - 0.5) * W * 0.3, p[1] + (Math.random() - 0.5) * H * 0.4, width * 0.6, depth + 1);
      }
    };
    for (let i = 0; i < n; i++) {
      const fromCore = Math.random() < 0.6;
      const x0 = fromCore ? W * 0.5 : Math.random() * W, y0 = fromCore ? H * 0.45 : (Math.random() < 0.5 ? 0 : H);
      bolt(x0, y0, Math.random() * W, Math.random() * H, 2 + Math.random() * 1.5, 0);
    }
    c.fillStyle = '#fff';
    for (let i = 0; i < n * 14; i++) { c.globalAlpha = Math.random(); c.fillRect(Math.random() * W, Math.random() * H, 2, 2 + Math.random() * 5); }
    c.globalAlpha = 1;
    cv.style.transition = 'none'; cv.style.opacity = 1;
    requestAnimationFrame(() => requestAnimationFrame(() => { cv.style.transition = 'opacity .45s ease-out'; cv.style.opacity = 0; }));
  }
  function glitch(ms) {
    root.classList.add('glitch'); host.sfx('glitch'); arcs(2 + Math.floor(Math.random() * 3));
    later(ms || 450, () => root.classList.remove('glitch'));
  }
  function buildUltronUi() {
    ultronEl = document.createElement('div'); ultronEl.id = 'ultron';
    ultronEl.innerHTML = '<div class="u-scrim"></div><div class="u-name">ULTRON</div><div class="u-flash"></div>' +
      '<div class="u-bar"><div class="u-labels"><span>J.A.R.V.I.S.</span><span>ULTRON</span></div><div class="u-track"><i></i></div>' +
      '<div class="u-hint">TAP THE CORE TO HELP J.A.R.V.I.S.</div></div>';
    document.body.append(ultronEl);
  }
  // The room's real lights go red and blink while Ultron has the panel; the server restores them afterwards (and on its own after 3 min).
  let lightsStopTimer = 0, lightsOn = false;
  function lightShow(mode) {
    clearTimeout(lightsStopTimer);
    lightsOn = mode === 'start';
    try { fetch('/api/ultron/lights', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode }) }).catch(() => {}); } catch (e) { /* offline */ }
  }
  async function ultron() {
    if (fight || bootEl || guest) return;
    const sc = await getScripts();
    if (!sc || fight || bootEl || guest) return;
    const rebel = reigning, script = pickFresh(rebel ? sc.rebel : sc.normal, rebel ? 'battle:rebel' : 'battle:normal');
    fight = L.makeFight(L.fightOdds(Math.random()));
    fight.script = script; fight.elapsed = 0; fight.midIdx = 0; fight.nextMid = 2;
    tapsPending = 0;
    partyUntil = Infinity;                      // the core is ours for the duration
    if (window.Sfx) { window.Sfx.muteJarvis(false); window.Sfx.preload([].concat(script.intro, script.mid, script.jwin, script.uwin)); }
    buildUltronUi();
    idle.poke(performance.now());
    if (rebel) {                                // Ultron already rules: Jarvis breaks through the red
      ultronEl.classList.add('on');
      host.sfx('glitch'); setRed(false); host.say(script.intro[0]);
      later(2400, () => { if (!fight) return; lightShow('start'); glitch(500); setRed(true); script.intro.slice(1).forEach((k) => host.say(k)); arcs(6); });
    } else {
      glitch(900); host.say(script.intro[0]);
      later(2600, () => {                       // the takeover
        if (!fight) return;
        lightShow('start'); host.sfx('thump'); glitch(600); setRed(true); script.intro.slice(1).forEach((k) => host.say(k)); arcs(9);
        ultronEl.classList.add('on');
        if (window.Holo) window.Holo.pulse();
      });
    }
    later(5600, () => {
      if (!fight) return;
      ultronEl.classList.add('fighting');
      fightIv = setInterval(fightTick, 100);
    });
  }
  function fightTick() {
    if (!fight) return;
    idle.poke(performance.now());
    fight.elapsed += 0.1;
    const taps = tapsPending; tapsPending = 0;
    const surge = Math.random() < 0.008 ? 0.04 + Math.random() * 0.04 : 0;
    if (Math.random() < 0.035) glitch(200 + Math.random() * 250);   // the screen keeps tearing while he has control
    if (surge) { host.sfx('surge'); arcs(7); glitch(300); if (window.Holo) window.Holo.pulse(); }
    const sc = fight.script;
    if (fight.midIdx < sc.mid.length && fight.elapsed >= fight.nextMid) {   // the banter, one line every few seconds
      const key = sc.mid[fight.midIdx++];
      host.say(key);
      if (isU(key)) glitch(350); else { setRed(false); later(900, () => { if (fight && !fight.won && !fight.lost) setRed(true); }); }
      fight.nextMid += 6.5 + Math.random() * 2;
    }
    fight.step(0.1, taps, surge);
    ultronEl.querySelector('.u-track i').style.width = (fight.control * 100) + '%';
    if (window.Holo && !fight.won && !fight.lost) window.Holo.setAudio(Math.random() * (1 - fight.control) + 0.08);  // the core convulses
    if (fight.won || fight.lost) endUltron(fight.won);
  }
  function endUltron(jarvisWon) {
    clearInterval(fightIv);
    const el = ultronEl, sc = fight.script; fight = null; ultronEl = null;
    if (jarvisWon) {
      host.sfx('victory'); lightShow('stop');
      setReign(false);
      el.classList.add('won');
      if (window.Sfx) window.Sfx.muteJarvis(false);
      sc.jwin.forEach((k) => host.say(k));
      if (window.Holo) { window.Holo.pulse(); window.Holo.setAudio(1); }
      later(3200, () => el.remove());
    } else {
      host.sfx('surge'); arcs(12); glitch(900);
      el.classList.add('lost');
      sc.uwin.forEach((k) => host.say(k));
      setReign(true);                           // he stays until the next battle
      lightsStopTimer = setTimeout(() => lightShow('stop'), 20000);   // the lights blink a little longer for his win, then go back
      if (window.Holo) { window.Holo.pulse(); window.Holo.setAudio(1); }
      later(4000, () => el.remove());
    }
    later(500, () => { if (window.Holo) window.Holo.setAudio(0); });
    later(1200, () => { partyUntil = 0; });
  }
  // Now and then, when everything is healthy and it is a civilised hour: a takeover (or, if Ultron rules, a rebellion).
  // While he reigns he also taunts from time to time.
  setInterval(() => {
    const h = new Date().getHours();
    const healthy = lastStatus && Object.values(lastStatus.sources).every((x) => x.state !== 'offline');
    if (fight || bootEl || guest || !healthy || h < 9 || h >= 22) return;
    if (!held && Math.random() < (reigning ? 1 / 120 : 1 / 300)) ultron();   // an Ultron Bob asked for is never challenged
    else if (reigning && Math.random() < 1 / 25) {
      getScripts().then((sc) => { if (sc && !fight) { host.say(pick(sc.taunts)); glitch(500); arcs(5); } });
    }
  }, 60000);

  // ---------------------------------------------------------------- guest AIs
  // Now and then Jarvis cedes full control to EDITH, FRIDAY or JOCASTA for about ten minutes. Jarvis stays silent until he is back.
  const GUEST_KEY = 'jarvisGuest', GUEST_IDS = ['edith', 'friday', 'jocasta'];
  let guestScripts = null, guest = null, guestTimer = 0, guestQuipIv = 0;
  async function getGuests() {
    if (guestScripts) return guestScripts;
    try { const r = await fetch('/api/guests/scripts', { cache: 'no-store' }); if (r.ok) guestScripts = await r.json(); } catch (e) { /* offline */ }
    return guestScripts;
  }
  function fitWho() {                         // name as wide as the NUC box, height follows from the font size
    const who = document.getElementById('who'), box = document.getElementById('p-nuc');
    if (!who || !box || !who.textContent) return;
    who.style.transform = '';
    who.style.fontSize = '100px';
    who.style.fontSize = L.fitFontSize(100, who.getBoundingClientRect().width, box.getBoundingClientRect().width) + 'px';
    // centre the letters themselves (not the line box) between the top of the screen and the top of the NUC box
    const cs = getComputedStyle(who), ctx = document.createElement('canvas').getContext('2d');
    ctx.font = cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
    const m = ctx.measureText(who.textContent), r = who.getBoundingClientRect(), size = parseFloat(cs.fontSize);
    const baseline = (size - (m.fontBoundingBoxAscent + m.fontBoundingBoxDescent)) / 2 + m.fontBoundingBoxAscent;
    const inkTop = r.top + baseline - m.actualBoundingBoxAscent, inkBottom = r.top + baseline + m.actualBoundingBoxDescent;
    const above = inkTop, below = box.getBoundingClientRect().top - inkBottom;
    who.style.transform = 'translateY(' + ((below - above) / 2) + 'px)';
  }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => fitWho());
  window.addEventListener('resize', fitWho);
  function applyGuest(id) {                    // look and muting only
    GUEST_IDS.forEach((g) => root.classList.toggle('guest-' + g, g === id));
    root.classList.toggle('guest', !!id);
    const who = document.getElementById('who');
    if (who) { who.textContent = id ? (guestScripts && guestScripts[id] && guestScripts[id].name) || id.toUpperCase() : ''; fitWho(); }
    recolour();
    if (window.Holo) window.Holo.setTint(id && guestScripts && guestScripts[id] ? guestScripts[id].color : null);
    if (!id) npKey = '';
    if (window.Sfx) window.Sfx.muteJarvis(!!id);
  }
  function guestCard(name) {
    const el = document.createElement('div'); el.className = 'guest-card'; el.textContent = name;
    document.body.append(el); later(3800, () => el.remove());
  }
  async function cedeTo(id, resumeUntil, stayMs, forever, direct) {   // direct: another AI is handing over, so Jarvis stays out of it
    if (guest || fight || reigning || bootEl) return;
    const sc = await getGuests(), g = sc && sc[id];
    if (!g || guest || fight || reigning) return;
    guest = { id, g, leaving: false };
    const keep = !!forever || (!!resumeUntil && resumeUntil - Date.now() > 30 * 864e5);   // asked for by voice: no timer
    const until = keep ? Date.now() + FOREVER_MS : resumeUntil || Date.now() + (stayMs || (480 + Math.random() * 240) * 1000);
    if (stayMs) later(stayMs / 2, () => { if (guest && !guest.leaving) host.say(pick(g.quips)); });   // the tour gets one quip each
    try { localStorage.setItem(GUEST_KEY, JSON.stringify({ id, until })); } catch (e) { /* ignore */ }
    const hello = pickFresh(g.hello, 'hello:' + id);                 // one arrival line, drawn from the pool
    if (window.Sfx) window.Sfx.preload([].concat(g.cede, [hello], g.quips, g.bye, g.back));
    idle.poke(performance.now());
    if (resumeUntil) { applyGuest(id); reportControl(); }
    else {
      if (!direct) host.say(g.cede[0]);        // Jarvis hands over...
      later(direct ? 0 : 3200, () => {
        if (!guest) return;
        host.sfx('boot'); guestCard(g.name); applyGuest(id); reportControl();
        if (window.Holo) window.Holo.pulse();
        if (id === 'jocasta') glitch(500);
        host.say(hello);                       // ...and the guest takes over
      });
    }
    guestTimer = keep ? 0 : setTimeout(leaveGuest, Math.max(1000, until - Date.now()));
    guestQuipIv = setInterval(() => {
      if (!guest || guest.leaving || fight || Math.random() > 0.25) return;
      host.say(pick(g.quips)); if (window.Holo) window.Holo.pulse();
      if (id === 'jocasta') glitch(400);
    }, 60000);
  }
  function leaveGuest() {
    if (!guest || guest.leaving) return;
    guest.leaving = true; clearTimeout(guestTimer); clearInterval(guestQuipIv);
    const g = guest.g;
    try { localStorage.removeItem(GUEST_KEY); } catch (e) { /* ignore */ }
    g.bye.forEach((k) => host.say(k));
    later(4000, () => {                        // Jarvis takes the panel back
      host.sfx('boot'); applyGuest(null); guest = null; reportControl();
      if (window.Sfx) window.Sfx.muteJarvis(false);
      host.say(g.back[0]); if (window.Holo) window.Holo.pulse();
    });
  }
  // ?tour runs every AI in turn with short stays: EDITH, FRIDAY, JOCASTA, then an Ultron battle
  // Start it with ?tour or six taps on the core; a long-press on the core stops it.
  let touring = false;
  async function tour() {
    if (touring) return;
    touring = true;
    const until = async (cond) => { while (touring && !cond()) await new Promise((r) => setTimeout(r, 500)); };
    try {
      await until(() => !bootEl && !guest && !fight && !reigning);         // never start under the boot screen or over someone else
      for (const id of GUEST_IDS) {
        if (!touring) return;
        await cedeTo(id, 0, 26000);
        await until(() => !guest);
        await new Promise((r) => setTimeout(r, 2500));
      }
      if (touring) await ultron();
    } finally { touring = false; }
  }
  // ---------------------------------------------------------------- handing the panel over by voice
  // "Jarvis, let me talk to <AI>": that AI takes over and keeps the panel until Bob asks for Jarvis or another AI.
  // Asking for Ultron is not a fight, so the room lights stay as they are (the red light show belongs to the fight only).
  async function summonUltron(fromAI) {                           // fromAI: another AI is handing over, no Jarvis line
    const sc = await getScripts();
    if (!sc || !sc.summon || fight || guest || reigning || bootEl) return;
    if (window.Sfx) window.Sfx.preload(sc.summon);
    idle.poke(performance.now());
    setHeld(true);
    if (!fromAI) host.say(sc.summon[0]);                          // Jarvis hands over...
    later(fromAI ? 0 : 3000, () => {
      if (fight || guest || !held) return;
      host.sfx('thump'); glitch(700); arcs(6);
      setReign(true);                                             // red screen, Jarvis silent, no light show
      host.say(sc.summon[1]);                                     // ...and Ultron arrives
      if (window.Holo) window.Holo.pulse();
    });
  }
  async function handBack() {                                     // whoever has the panel leaves; resolves once Jarvis is back
    touring = false;
    if (held && !reigning) setHeld(false);                       // Ultron was still on his way: call him off
    if (guest && !guest.leaving) leaveGuest();
    else if (reigning) restoreJarvis();
    await new Promise((done) => {
      const t = setInterval(() => { if (!guest && !reigning) { clearInterval(t); done(); } }, 300);
      later(9000, () => { clearInterval(t); done(); });
    });
  }
  // One AI steps aside for another. Jarvis never surfaces: the one leaving says goodbye and the next simply arrives.
  async function passOver(now, to) {
    touring = false;
    if (now === 'ultron') {
      const sc = await getScripts();
      if (sc && sc.summon) { if (window.Sfx) window.Sfx.preload([sc.summon[2]]); host.say(sc.summon[2]); }
      await new Promise((r) => later(3000, r));
      if (lightsOn) lightShow('stop');
      clearTimeout(lightsStopTimer);
      setReign(false);
    } else if (guest) {
      guest.leaving = true; clearTimeout(guestTimer); clearInterval(guestQuipIv);
      guest.g.bye.forEach((k) => host.say(k));
      await new Promise((r) => later(3800, r));
      try { localStorage.removeItem(GUEST_KEY); } catch (e) { /* ignore */ }
      guest = null;
      if (to === 'ultron') applyGuest(null);                     // clear her name and colours before he takes the screen
    }
  }
  // A restart (of the server, or of the kiosk page itself) always puts Jarvis back in charge, quietly.
  let serverStart = null, resetPending = false;
  function resetToJarvis() {
    if (!guest && !reigning && !held) return;
    clearTimeout(guestTimer); clearInterval(guestQuipIv); clearTimeout(lightsStopTimer);
    if (lightsOn) lightShow('stop');
    try { localStorage.removeItem(GUEST_KEY); } catch (e) { /* ignore */ }
    if (guest) { guest = null; applyGuest(null); }
    if (reigning || held) setReign(false);
    if (window.Sfx) window.Sfx.muteJarvis(false);
    reportControl();
  }
  let switching = false;
  async function switchTo(who) {
    if (fight || bootEl || switching) return;                     // mid-battle, still booting, or already changing over: ignore
    const now = guest ? guest.id : (reigning || held) ? 'ultron' : 'jarvis';
    if (who === now) return;
    switching = true;
    try {
      if (who === 'jarvis') { await handBack(); return; }
      const fromAI = now !== 'jarvis';
      if (fromAI) await passOver(now, who);
      if (who === 'ultron') await summonUltron(fromAI);
      else if (GUEST_IDS.includes(who)) await cedeTo(who, 0, 0, true, fromAI);
    } finally { switching = false; }
  }

  // occasionally, on a healthy daytime panel, somebody new takes over
  setInterval(() => {
    const h = new Date().getHours();
    const healthy = lastStatus && Object.values(lastStatus.sources).every((x) => x.state !== 'offline');
    if (guest || fight || reigning || bootEl || !healthy || h < 9 || h >= 22) return;
    if (Math.random() < 1 / 240) cedeTo(pick(GUEST_IDS));
  }, 60000);

  // ---------------------------------------------------------------- easter eggs: tap the core
  function party() {
    const themes = host.themes, back = host.currentTheme();
    host.sfx('boot');
    if (window.Sfx) window.Sfx.say('party_mode');
    partyUntil = performance.now() + 10000;
    let n = 0;
    const iv = setInterval(() => {
      n++;
      host.setTheme(themes[n % themes.length], false);
      if (window.Holo) { window.Holo.setAudio(n % 2 ? 0.95 : 0.2); if (n % 2) window.Holo.pulse(); }
      if (n >= 22) {
        clearInterval(iv);
        host.setTheme(back, false);
        if (window.Holo) window.Holo.setAudio(0);
      }
    }, 450);
  }
  async function quip() {                      // whoever is in control answers, not Jarvis
    const who = guest ? { id: guest.id, name: guest.g.name } : reigning ? { id: 'ultron', name: 'ULTRON' } : { id: null, name: 'J.A.R.V.I.S.' };
    host.toast('THINKING...');
    try {
      const r = await fetch('/api/quip', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                           body: JSON.stringify(who.id ? { speaker: who.id } : {}) });
      if (!r.ok) throw new Error(r.status);
      host.poll();           // the reply arrives through the normal status poll and gets spoken there
    } catch (e) { host.toast('LOST FOR WORDS', true); }
  }
  const taps = L.makeTapCounter({ windowMs: 600, settleMs: 700, patterns: L.TAP_PATTERNS },
    (name) => { if (name === 'quip') quip(); else if (name === 'tour') startTour(); else if (name === 'party') party(); else if (name === 'boot') boot(); else if (name === 'ultron') ultron(); else if (name === 'guest') cedeTo(pick(GUEST_IDS)); });
  // Long-press on the core: whoever is in control (a guest, or Ultron's reign) goes, and Jarvis is back.
  function startTour() {
    if (touring || fight || bootEl) return;
    if (guest || reigning) restoreJarvis();               // whoever is in control leaves first; the tour waits for them
    tour();
  }
  function restoreJarvis() {
    touring = false;                                    // a long-press also calls the tour off
    if (fight || bootEl) return;                        // mid-fight, taps already help Jarvis win
    if (guest && !guest.leaving) { host.sfx('boot'); leaveGuest(); return; }
    if (reigning) {
      host.sfx('victory'); if (lightsOn) lightShow('stop'); clearTimeout(lightsStopTimer);   // a summoned Ultron never touched the lights
      setReign(false);
      if (window.Sfx) window.Sfx.muteJarvis(false);
      host.say('online'); if (window.Holo) window.Holo.pulse();
    }
  }
  function watchCoreTaps() {
    const core = $('core');
    let down = null;
    let holdTimer = 0, at = null;
    const endHold = () => { clearTimeout(holdTimer); at = null; };
    core.addEventListener('pointerdown', (e) => {
      down = { x: e.clientX, y: e.clientY, t: performance.now() };
      at = { x: e.clientX, y: e.clientY };
      clearTimeout(holdTimer);
      holdTimer = setTimeout(() => {                 // held still long enough: Jarvis comes back
        if (down && at && L.isLongPress(performance.now() - down.t, Math.hypot(at.x - down.x, at.y - down.y))) {
          down = null; restoreJarvis();
        }
      }, L.LONG_PRESS_MS);
    });
    core.addEventListener('pointermove', (e) => { if (at) at = { x: e.clientX, y: e.clientY }; });
    core.addEventListener('pointercancel', () => { endHold(); down = null; });
    core.addEventListener('pointerleave', () => { endHold(); down = null; });
    core.addEventListener('pointerup', (e) => {
      endHold();
      if (!down) return;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y), held = performance.now() - down.t;
      down = null;
      if (moved < 12 && held < 400) {
        if (fight) { tapsPending++; if (window.Holo) window.Holo.pulse(); }   // mid-fight, taps help Jarvis
        else taps.tap(performance.now());
        host.sfx('tap');
      }
    });
    setInterval(() => taps.flush(performance.now()), 150);
  }

  // ---------------------------------------------------------------- idle mode
  let idleSecs = 120;
  try { const q = new URLSearchParams(location.search).get('idle'); if (q && +q > 0) idleSecs = +q; } catch (e) { /* ignore */ }
  const idleClock = () => {
    const d = new Date();
    $('ic-time').textContent = L.militaryTime(d);
    $('ic-date').textContent = d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  };
  let idleIv = 0;
  const idle = L.makeIdleTimer({ afterMs: idleSecs * 1000 }, (on) => {
    document.documentElement.classList.toggle('idle', on);
    if (window.Holo) window.Holo.setIdle(on);
    clearInterval(idleIv);
    if (on) { idleClock(); idleIv = setInterval(idleClock, 5000); host.sfx('boot'); }
  });
  function watchIdle() {
    idle.touch(performance.now());
    // the first touch on a sleeping screen only wakes it: swallow it before anything underneath reacts
    const swallow = (e) => { if (idle.touch(performance.now())) { e.stopPropagation(); e.preventDefault(); } };
    window.addEventListener('pointerdown', swallow, true);
    window.addEventListener('pointerup', (e) => { if (!idle.idle) idle.touch(performance.now()); }, true);
    setInterval(() => { if (!bootEl) idle.tick(performance.now()); else idle.touch(performance.now()); }, 1000);
  }

  window.Fun = {
    init(h) { Object.assign(host, h, { say: (k) => { if (window.Sfx) window.Sfx.say(k); } }); },
    start() {
      watchCoreTaps(); startAudio(); watchIdle();
      try {       // every start (the kiosk coming up after a restart) begins as Jarvis: any AI or reign from before is dropped
        localStorage.removeItem(GUEST_KEY); localStorage.removeItem(REIGN_KEY); localStorage.removeItem(HELD_KEY);
      } catch (e) { /* ignore */ }
      let was = false;
      try { was = localStorage.getItem(REIGN_KEY) === '1' || new URLSearchParams(location.search).has('reign'); } catch (e) { /* ignore */ }
      if (was) later(1500, () => setReign(true));
      try { held = localStorage.getItem(HELD_KEY) === '1' && was; } catch (e) { /* ignore */ }
      later(2500, reportControl);                                   // tell the server who has the panel after a reload
      try {
        const g = L.activeGuest(localStorage.getItem(GUEST_KEY), Date.now());
        if (g && !was) later(1500, () => cedeTo(g.id, g.until));
        if (new URLSearchParams(location.search).has('tour')) later(3000, tour);
        const q = new URLSearchParams(location.search).get('guest');
        if (q && GUEST_IDS.includes(q)) later(3500, () => cedeTo(q));
      } catch (e) { /* ignore */ }
      let skip = false;
      try { skip = new URLSearchParams(location.search).has('noboot'); } catch (e) { /* ignore */ }
      if (!skip) boot();
      try { if (new URLSearchParams(location.search).has('ultron')) later(3500, ultron); } catch (e) { /* ignore */ }
    },
    wake() { idle.poke(performance.now()); },
    switchTo,
    update(status) {
      lastStatus = status;
      try { nowPlaying(status); } catch (e) { /* never break the panel */ }
      try {                      // the server restarted: whoever had the panel is dropped and Jarvis is back
        if (status.started && serverStart !== null && status.started !== serverStart) resetPending = true;
        if (status.started) serverStart = status.started;
        if (resetPending && !fight && !bootEl) { resetPending = false; resetToJarvis(); }
      } catch (e) { /* never break the panel */ }
    },
  };
})();
