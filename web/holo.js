/* Holo-core: the centre of the panel. No text; every element is data as geometry.
 *  - particle sphere ........ breathes with NUC CPU, scan band sweeps over it
 *  - 4 gyroscope rings ...... one satellite each: NUC (octahedron), Plex (tetra),
 *                             Disks (cube), Pi-hole (icosa). Orbit speed = activity,
 *                             colour = state, trouble makes the satellite swell + pulse
 *  - outer tilted ring ...... one bead per light, amber + glowing when ON
 *  - second tilted ring ..... one diamond per speaker, pulses when playing, size = volume
 *  - flat tick dial ......... lit proportion = overall health, a scanner tick sweeps it
 *  - shockwave rings ........ amber/red pulses leaving the core when something is wrong
 *  - drag to spin the whole thing, it eases back
 */
(function () {
  'use strict';
  const host = document.getElementById('core');
  const T = window.THREE;
  const api = { ok: false, update() {}, pulse() {}, setTint() {}, setAudio() {}, setIdle() {} };
  window.Holo = api;
  if (!host || !T) return;

  let renderer;
  try {
    renderer = new T.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  } catch (e) { return; }
  renderer.setClearColor(0x000000, 0);
  const canvas = renderer.domElement;
  canvas.id = 'holo';
  host.insertBefore(canvas, host.firstChild);
  host.classList.add('gl');

  const CYAN = 0x2ff3ff, AMBER = 0xffb829, RED = 0xff4d4d;
  let DIM = 0x2a8fa8, OKC = '#2ff3ff';
  const ADD = T.AdditiveBlending;

  // ---------- helpers
  function tex(draw) {
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const g = c.getContext('2d'); draw(g); return new T.CanvasTexture(c);
  }
  const dotTex = tex((g) => {
    const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(.22, 'rgba(255,255,255,.6)');
    gr.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
  });
  const diaTex = tex((g) => {
    const gr = g.createRadialGradient(32, 32, 0, 32, 32, 30);
    gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(1, 'rgba(255,255,255,.05)');
    g.fillStyle = gr; g.beginPath(); g.moveTo(32, 2); g.lineTo(60, 32); g.lineTo(32, 62); g.lineTo(4, 32); g.closePath(); g.fill();
  });
  function spriteMat(map, color) {
    return new T.SpriteMaterial({ map, color, blending: ADD, transparent: true, depthWrite: false });
  }
  function circleLine(radius, color, opacity) {
    const pts = [];
    for (let i = 0; i <= 160; i++) { const a = i / 160 * Math.PI * 2; pts.push(new T.Vector3(Math.cos(a) * radius, Math.sin(a) * radius, 0)); }
    return new T.Line(new T.BufferGeometry().setFromPoints(pts),
      new T.LineBasicMaterial({ color, transparent: true, opacity, blending: ADD, depthWrite: false }));
  }

  // ---------- scene
  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(40, 1, 0.1, 100);
  camera.position.set(0, 0, 9.6);
  const world = new T.Group(); scene.add(world);

  // live state
  const S = {
    link: false, sev: 0, health: 0, healthShown: 0, cpu: 0,
    core: new T.Color(CYAN), coreT: new T.Color(CYAN),
    lights: [], speakers: [], yaw: 0, pitch: 0, vyaw: 0, vpitch: 0, drag: false,
  };

  // ---------- particle sphere
  const N = 1600, R0 = 1.2;
  const base = new Float32Array(N * 3), pos = new Float32Array(N * 3), col = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    const phi = Math.acos(1 - 2 * (i + .5) / N), th = Math.PI * (1 + Math.sqrt(5)) * i;
    base[i * 3] = Math.sin(phi) * Math.cos(th); base[i * 3 + 1] = Math.cos(phi); base[i * 3 + 2] = Math.sin(phi) * Math.sin(th);
  }
  const sphereGeo = new T.BufferGeometry();
  sphereGeo.setAttribute('position', new T.BufferAttribute(pos, 3));
  sphereGeo.setAttribute('color', new T.BufferAttribute(col, 3));
  const sphere = new T.Points(sphereGeo, new T.PointsMaterial({
    size: 0.11, map: dotTex, vertexColors: true, transparent: true, depthWrite: false, blending: ADD, sizeAttenuation: true }));
  world.add(sphere);

  const inner = new T.LineSegments(new T.WireframeGeometry(new T.IcosahedronGeometry(0.72, 1)),
    new T.LineBasicMaterial({ color: CYAN, transparent: true, opacity: 0.22, blending: ADD, depthWrite: false }));
  world.add(inner);

  const glow = new T.Sprite(spriteMat(dotTex, CYAN)); glow.scale.set(3.4, 3.4, 1); glow.material.opacity = 0.38; world.add(glow);
  const heart = new T.Sprite(spriteMat(dotTex, 0xffffff)); heart.scale.set(0.9, 0.9, 1); heart.material.opacity = 0.7; world.add(heart);

  // ---------- shockwaves (trouble escalates toward the viewer)
  const waves = [];
  for (let i = 0; i < 2; i++) {
    const m = new T.Mesh(new T.RingGeometry(0.97, 1, 96),
      new T.MeshBasicMaterial({ color: CYAN, transparent: true, opacity: 0, blending: ADD, depthWrite: false, side: T.DoubleSide }));
    world.add(m); waves.push(m);
  }

  // ---------- voice: expanding bright rings when the panel hears you / answers
  const bursts = [0, 1, 2].map(() => {
    const m = new T.Mesh(new T.RingGeometry(0.96, 1, 96),
      new T.MeshBasicMaterial({ color: CYAN, transparent: true, opacity: 0, blending: ADD, depthWrite: false, side: T.DoubleSide }));
    world.add(m); return m;
  });
  let burstAt = -99, burstColor = new T.Color(CYAN), clockT = 0;
  api.pulse = function () { burstAt = clockT; burstColor.set(OKC); };

  // ---------- gyroscope rings with satellites
  const SATS = [
    { key: 'nuc',    R: 1.75, tilt: [1.15, 0.2, 0.0],  prec: 0.05,  base: 0.95, geo: () => new T.OctahedronGeometry(0.12) },
    { key: 'plex',   R: 2.07, tilt: [0.35, 0.95, 0.3], prec: -0.04, base: 0.7,  geo: () => new T.TetrahedronGeometry(0.15) },
    { key: 'disks',  R: 2.39, tilt: [1.45, -0.6, 0.5], prec: 0.035, base: 0.5,  geo: () => new T.BoxGeometry(0.17, 0.17, 0.17) },
    { key: 'pihole', R: 2.71, tilt: [0.8, 0.5, 1.0],   prec: -0.03, base: 0.38, geo: () => new T.IcosahedronGeometry(0.13, 0) },
  ];
  const TRAIL = 22;
  for (const s of SATS) {
    s.sev = 0; s.act = 0; s.a = Math.random() * 6.28;
    s.col = new T.Color(CYAN); s.colT = new T.Color(CYAN);
    s.group = new T.Group(); s.group.rotation.set(s.tilt[0], s.tilt[1], s.tilt[2]);
    s.ring = circleLine(s.R, CYAN, 0.3); s.group.add(s.ring);
    s.mesh = new T.Mesh(s.geo(), new T.MeshBasicMaterial({ color: CYAN })); s.group.add(s.mesh);
    s.halo = new T.Sprite(spriteMat(dotTex, CYAN)); s.halo.scale.set(0.55, 0.55, 1); s.group.add(s.halo);
    s.tp = new Float32Array(TRAIL * 3); s.tc = new Float32Array(TRAIL * 3);
    const tg = new T.BufferGeometry();
    tg.setAttribute('position', new T.BufferAttribute(s.tp, 3)); tg.setAttribute('color', new T.BufferAttribute(s.tc, 3));
    s.trail = new T.Points(tg, new T.PointsMaterial({ size: 0.09, map: dotTex, vertexColors: true, transparent: true,
      depthWrite: false, blending: ADD, sizeAttenuation: true }));
    s.group.add(s.trail);
    world.add(s.group);
  }
  const satByKey = Object.fromEntries(SATS.map((s) => [s.key, s]));

  // ---------- lights ring (beads) and audio ring (diamonds)
  const lightsGroup = new T.Group(); lightsGroup.rotation.set(1.12, 0.1, 0); world.add(lightsGroup);
  const lightsRing = circleLine(2.98, CYAN, 0.14); lightsGroup.add(lightsRing);
  const audioGroup = new T.Group(); audioGroup.rotation.set(-1.0, 0.35, 0); world.add(audioGroup);
  const audioRing = circleLine(3.06, CYAN, 0.1); audioGroup.add(audioRing);

  function rebuild(list, group, radius, map, n) {
    for (const o of list) { group.remove(o.sprite); o.sprite.material.dispose(); }
    list.length = 0;
    for (let i = 0; i < n; i++) {
      const sprite = new T.Sprite(spriteMat(map, DIM)); group.add(sprite);
      list.push({ sprite, k: 0, kT: 0, ang: i / n * Math.PI * 2, size: 0.1, pulse: false });
    }
  }

  // ---------- health tick dial (flat to the viewer)
  const TICKS = 60;
  const tkP = new Float32Array(TICKS * 6), tkC = new Float32Array(TICKS * 6);
  for (let i = 0; i < TICKS; i++) {
    const a = i / TICKS * Math.PI * 2, r1 = i % 5 === 0 ? 3.1 : 3.2, r2 = 3.4;
    tkP.set([Math.sin(a) * r1, Math.cos(a) * r1, 0, Math.sin(a) * r2, Math.cos(a) * r2, 0], i * 6);
  }
  const tkGeo = new T.BufferGeometry();
  tkGeo.setAttribute('position', new T.BufferAttribute(tkP, 3)); tkGeo.setAttribute('color', new T.BufferAttribute(tkC, 3));
  const ticks = new T.LineSegments(tkGeo, new T.LineBasicMaterial({ vertexColors: true, transparent: true, blending: ADD, depthWrite: false }));
  scene.add(ticks);

  // ---------- data in
  const sevOf = (st) => st === 'ok' ? 0 : (st === 'warn' || st === 'stale') ? 1 : st === 'unconfigured' ? -1 : 2;
  const HEX = [OKC, AMBER, RED];
  let lastArgs = null;

  api.ok = true;
  api.update = function (status, linkLost, colorHex) {
    lastArgs = [status, linkLost, colorHex];
    S.link = !!linkLost;
    const baseHex = linkLost ? RED : (!colorHex || colorHex === '#2ff3ff') ? OKC : colorHex;
    // while music plays the core takes the album's colour, but never hides a critical (red) state
    S.coreT.set(tint && !linkLost && colorHex !== '#ff4d4d' ? tint : baseHex);
    if (linkLost) S.sev = 2;
    if (!status) return;
    const src = status.sources || {};
    S.health = linkLost ? 0 : (status.health || 0);
    let worst = 0;
    for (const s of SATS) {
      const r = src[s.key]; const sev = r ? sevOf(r.state) : 2;
      s.sev = sev;
      s.colT.set(sev < 0 ? DIM : HEX[sev]);
      worst = Math.max(worst, sev);
    }
    const nuc = (src.nuc && src.nuc.data) || {}, plex = (src.plex && src.plex.data) || {}, ph = (src.pihole && src.pihole.data) || {};
    S.cpu = Math.max(0, Math.min(1, (nuc.cpu_percent || 0) / 100));
    satByKey.nuc.act = S.cpu;
    satByKey.plex.act = Math.min(4, plex.streams || 0) / 4;
    satByKey.disks.act = 0.15;
    satByKey.pihole.act = Math.min(1, (ph.block_percent || 0) / 100);
    const sh = (src.smart_home && src.smart_home.data) || {};
    const ls = sh.lights || [], sp = sh.speakers || [];
    if (S.lights.length !== ls.length) rebuild(S.lights, lightsGroup, 2.98, dotTex, ls.length);
    if (S.speakers.length !== sp.length) rebuild(S.speakers, audioGroup, 3.06, diaTex, sp.length);
    ls.forEach((l, i) => { S.lights[i].kT = l.on ? 1 : 0; });
    sp.forEach((x, i) => {
      const o = S.speakers[i];
      o.pulse = x.state === 'playing';
      o.kT = x.state === 'playing' ? 1 : x.state === 'paused' ? 0.4 : 0;
      o.size = 0.12 + 0.16 * ((x.volume == null ? 40 : x.volume) / 100);
    });
    if (src.smart_home) worst = Math.max(worst, sevOf(src.smart_home.state));
    S.sev = linkLost ? 2 : Math.max(0, worst);
  };

  let tint = null, audio = 0, audioS = 0, lastBeat = -9;
  let idleT = 0, idleK = 0, lastIdleBurst = -9, spin = 0;
  api.setIdle = function (on) { idleT = on ? 1 : 0; };
  api.setTint = function (hex) { tint = hex || null; if (lastArgs) api.update(lastArgs[0], lastArgs[1], lastArgs[2]); };
  api.setAudio = function (v) { audio = Math.max(0, Math.min(1, v || 0)); };

  api.setTheme = function (ok, dim) {
    OKC = ok; HEX[0] = ok; DIM = dim;
    lightsRing.material.color.set(ok); audioRing.material.color.set(ok);
    if (lastArgs) api.update(lastArgs[0], lastArgs[1], lastArgs[2]);
  };

  // ---------- sizing + drag
  function resize() {
    const w = host.clientWidth || 600, h = host.clientHeight || 600;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  if (window.ResizeObserver) new ResizeObserver(resize).observe(host); else window.addEventListener('resize', resize);
  resize();

  let lx = 0, ly = 0;
  canvas.addEventListener('pointerdown', (e) => { S.drag = true; lx = e.clientX; ly = e.clientY; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointermove', (e) => {
    if (!S.drag) return;
    S.vyaw = (e.clientX - lx) * 0.006; S.vpitch = (e.clientY - ly) * 0.006;
    S.yaw += S.vyaw; S.pitch = Math.max(-0.9, Math.min(0.9, S.pitch + S.vpitch)); lx = e.clientX; ly = e.clientY;
  });
  const endDrag = () => { S.drag = false; };
  canvas.addEventListener('pointerup', endDrag); canvas.addEventListener('pointercancel', endDrag);

  // ---------- frame loop
  const tmp = new T.Color(), white = new T.Color(0xffffff);
  let last = performance.now(), t = 0;
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - last) / 1000); last = now; t += dt; clockT = t;
    const link = S.link, calm = link ? 0.2 : 1;

    S.core.lerp(S.coreT, 0.06);
    idleK += (idleT - idleK) * 0.03;
    camera.position.z = 9.6 - idleK * 0.9 + idleK * 0.35 * Math.sin(t * 0.35);   // slow dolly while idle
    if (idleK > 0.6 && t - lastIdleBurst > 3.4) { lastIdleBurst = t; burstAt = t; burstColor.copy(S.core); }
    const prevAudio = audioS;
    audioS += (audio - audioS) * (audio > audioS ? 0.55 : 0.1);     // snap up on a beat, ease down
    if (audioS - prevAudio > 0.12 && audioS > 0.45 && t - lastBeat > 0.45) { lastBeat = t; burstAt = t; burstColor.copy(S.core); }
    S.healthShown += (S.health - S.healthShown) * 0.04;

    // drag easing back to rest
    if (!S.drag) { S.yaw *= 0.96; S.pitch *= 0.96; }
    spin += dt * 0.12 * calm * (1 + idleK * 2.2);
    world.rotation.y = spin + S.yaw; world.rotation.x = S.pitch;

    // particle sphere
    const sc = R0 * (1 + 0.04 * Math.sin(t * 0.9) + S.cpu * 0.12 + audioS * 0.24), jit = (link ? 0.09 : 0.03) + audioS * 0.05;
    const scan = Math.sin(t * 0.8) * 1.0;
    for (let i = 0, k = 0; i < N; i++, k += 3) {
      const r = sc * (1 + jit * Math.sin(t * 1.7 + i * 0.73));
      pos[k] = base[k] * r; pos[k + 1] = base[k + 1] * r; pos[k + 2] = base[k + 2] * r;
      const d = base[k + 1] - scan, b = (0.7 + 1.1 * Math.exp(-d * d * 22)) * (link ? 0.5 : 1);
      col[k] = S.core.r * b; col[k + 1] = S.core.g * b; col[k + 2] = S.core.b * b;
    }
    sphereGeo.attributes.position.needsUpdate = true; sphereGeo.attributes.color.needsUpdate = true;
    sphere.rotation.y = 0;
    inner.rotation.y = -t * 0.3 * calm; inner.rotation.x = t * 0.17 * calm; inner.material.color.copy(S.core);
    const beat = 1 + 0.08 * Math.sin(t * (S.sev === 2 ? 5 : S.sev === 1 ? 3 : 1.6)) + audioS * 0.45;
    glow.material.color.copy(S.core); glow.scale.setScalar(3.4 * beat); glow.material.opacity = 0.3 + 0.1 * Math.sin(t * 1.6) + idleK * 0.16;
    heart.scale.setScalar(0.8 * beat); heart.material.color.copy(S.core).lerp(white, 0.5);

    // shockwaves
    const period = S.sev === 2 ? 2.2 : 3.6;
    waves.forEach((w, i) => {
      if (S.sev === 0) { w.material.opacity = 0; return; }
      const ph = ((t / period) + i * 0.5) % 1;
      w.scale.setScalar(1.1 + ph * 2.4);
      w.material.opacity = (1 - ph) * (S.sev === 2 ? 0.55 : 0.3);
      w.material.color.copy(S.core);
    });
    bursts.forEach((b, i) => {
      const ph = (t - burstAt - i * 0.18) / 1.3;
      if (ph < 0 || ph > 1) { b.material.opacity = 0; return; }
      b.scale.setScalar(1.0 + ph * 3.0);
      b.material.opacity = (1 - ph) * 0.8;
      b.material.color.copy(burstColor);
      b.quaternion.copy(camera.quaternion).premultiply(world.quaternion.clone().invert());
    });
    for (const w of waves) w.quaternion.copy(camera.quaternion).premultiply(world.quaternion.clone().invert());

    // satellites
    for (const s of SATS) {
      s.col.lerp(s.colT, 0.08);
      const speed = s.base * (0.55 + s.act * 1.1) * (s.sev === 2 ? 1.7 : 1) * (link ? 0.15 : 1) * (1 + idleK * 1.6);
      s.a += dt * speed;
      s.group.rotation.y += dt * s.prec * calm;
      s.mesh.position.set(Math.cos(s.a) * s.R, Math.sin(s.a) * s.R, 0);
      s.halo.position.copy(s.mesh.position);
      s.mesh.rotation.x += dt * 1.1; s.mesh.rotation.y += dt * 0.8;
      const trouble = s.sev >= 1;
      const pulse = trouble ? 1.35 + 0.35 * Math.sin(t * (s.sev === 2 ? 9 : 4.5)) : 1;
      s.mesh.scale.setScalar(pulse * (link ? 0.7 : 1));
      s.halo.scale.setScalar((trouble ? 0.9 : 0.55) * pulse);
      s.mesh.material.color.copy(s.col);
      s.halo.material.color.copy(s.col); s.halo.material.opacity = link ? 0.3 : 0.9;
      s.ring.material.color.copy(s.col); s.ring.material.opacity = trouble ? 0.5 : 0.25;
      for (let i = 0; i < TRAIL; i++) {
        const a = s.a - i * 0.075, f = Math.pow(1 - i / TRAIL, 2) * (link ? 0.4 : 1);
        s.tp[i * 3] = Math.cos(a) * s.R; s.tp[i * 3 + 1] = Math.sin(a) * s.R; s.tp[i * 3 + 2] = 0;
        s.tc[i * 3] = s.col.r * f; s.tc[i * 3 + 1] = s.col.g * f; s.tc[i * 3 + 2] = s.col.b * f;
      }
      s.trail.geometry.attributes.position.needsUpdate = true; s.trail.geometry.attributes.color.needsUpdate = true;
    }

    // lights + speakers
    lightsGroup.rotation.z += dt * 0.07 * calm; audioGroup.rotation.z -= dt * 0.05 * calm;
    S.lights.forEach((o) => {
      o.k += (o.kT - o.k) * 0.1;
      const a = o.ang;
      o.sprite.position.set(Math.cos(a) * 2.98, Math.sin(a) * 2.98, 0);
      tmp.set(DIM).lerp(new T.Color(AMBER), o.k); o.sprite.material.color.copy(tmp);
      const flick = o.k > 0.5 ? 1 + 0.06 * Math.sin(t * 3 + a * 5) : 1;
      o.sprite.scale.setScalar((0.12 + 0.3 * o.k) * flick);
      o.sprite.material.opacity = link ? 0.35 : 1;
    });
    S.speakers.forEach((o) => {
      o.k += (o.kT - o.k) * 0.1;
      const a = o.ang;
      o.sprite.position.set(Math.cos(a) * 3.06, Math.sin(a) * 3.06, 0);
      tmp.set(DIM).lerp(new T.Color(CYAN), o.k); o.sprite.material.color.copy(tmp);
      const p = o.pulse ? 1 + 0.35 * Math.sin(t * 6 + a * 3) : 1;
      o.sprite.scale.setScalar(o.size * (0.6 + 0.6 * o.k) * p * 1.6);
      o.sprite.material.opacity = link ? 0.35 : 1;
    });

    // health dial
    const lit = Math.round(S.healthShown / 100 * TICKS), sweep = Math.floor(t * 14) % TICKS;
    for (let i = 0; i < TICKS; i++) {
      const b = i < lit ? 1 : 0.1, hot = i === sweep ? 1 : 0;
      tmp.copy(S.core).multiplyScalar(b).lerp(white, hot * 0.55);
      if (hot && i >= lit) tmp.copy(S.core).multiplyScalar(0.55);
      tkC[i * 6] = tkC[i * 6 + 3] = tmp.r; tkC[i * 6 + 1] = tkC[i * 6 + 4] = tmp.g; tkC[i * 6 + 2] = tkC[i * 6 + 5] = tmp.b;
    }
    tkGeo.attributes.color.needsUpdate = true;

    renderer.render(scene, camera);
  }
  requestAnimationFrame(frame);
})();
