const test = require('node:test');
const assert = require('node:assert');
const { stateClass, coreColor, holdProgress, ageLabel, buttonsFor, isLinkLost, effectiveState, sourceLevels, announcements } = require('./logic.js');

test('stateClass maps every source state', () => {
  assert.strictEqual(stateClass('ok'), 'ok');
  assert.strictEqual(stateClass('warn'), 'warn');
  assert.strictEqual(stateClass('offline'), 'bad');
  assert.strictEqual(stateClass('stale'), 'warn');
  assert.strictEqual(stateClass('unconfigured'), 'dim');
  assert.strictEqual(stateClass('anything-else'), 'bad');
});

test('coreColor: cyan when healthy, amber when degraded or warned, red when low', () => {
  assert.strictEqual(coreColor(96, false), '#2ff3ff');
  assert.strictEqual(coreColor(75, false), '#ffb829');
  assert.strictEqual(coreColor(40, false), '#ff4d4d');
  assert.strictEqual(coreColor(96, true), '#ffb829');
  assert.strictEqual(coreColor(60, false), '#ffb829');
  assert.strictEqual(coreColor(59, false), '#ff4d4d');
});

test('holdProgress runs 0 to 1 over the hold time', () => {
  assert.strictEqual(holdProgress(0, 600), 0.5);
  assert.strictEqual(holdProgress(0, 5000), 1);
  assert.strictEqual(holdProgress(1000, 1000), 0);
  assert.strictEqual(holdProgress(1000, 500), 0);
});

test('ageLabel shows seconds, minutes, or hours since the data was taken', () => {
  assert.strictEqual(ageLabel(1000, 1012), '12s ago');
  assert.strictEqual(ageLabel(1000, 1000 + 150), '2m ago');
  assert.strictEqual(ageLabel(1000, 1000 + 7300), '2h ago');
  assert.strictEqual(ageLabel(1000, 900), '0s ago');
});

test('buttonsFor lists the fixed buttons plus one per smart-home entity from status', () => {
  const status = { sources: { smart_home: { state: 'ok', data: {
    lights: [{ name: 'desk', on: true }], speakers: [{ name: 'sonos', state: 'playing', volume: 30 }] } } } };
  const names = buttonsFor(status).map(b => b.action);
  for (const a of ['restart_plex', 'pause_pihole', 'restart_samba', 'disk_check']) {
    assert.ok(names.includes(a), a);
  }
  assert.ok(!names.includes('snapraid_sync'));     // the panel no longer offers the sync button
  assert.ok(names.includes('lights_toggle_desk'));
  assert.ok(names.includes('volume_up_sonos'));
});

test('buttonsFor marks disk_check as no-hold (read-only) and the rest as hold', () => {
  const b = Object.fromEntries(buttonsFor({ sources: {} }).map(x => [x.action, x]));
  assert.strictEqual(b.disk_check.hold, false);
  assert.strictEqual(b.restart_plex.hold, true);
});

test('buttonsFor gives low-risk smart-home buttons a shorter hold than service restarts', () => {
  const status = { sources: { smart_home: { state: 'ok', data: {
    lights: [{ name: 'desk', on: true }], speakers: [{ name: 'sonos', state: 'playing', volume: 30 }] } } } };
  const b = Object.fromEntries(buttonsFor(status).map(x => [x.action, x]));
  assert.strictEqual(b.restart_plex.holdMs, 1200);
  assert.ok(b.lights_toggle_desk.holdMs < 1200 && b.lights_toggle_desk.holdMs > 0);
  assert.ok(b.volume_up_sonos.holdMs < 1200);
});


test('isLinkLost is false until the last good reply is older than the limit', () => {
  assert.strictEqual(isLinkLost(1000, 1000 + 9000), false);
  assert.strictEqual(isLinkLost(1000, 1000 + 10001), true);
  assert.strictEqual(isLinkLost(null, 5000), true);
});

test('effectiveState forces every panel offline while the link is lost', () => {
  assert.strictEqual(effectiveState('ok', true), 'offline');
  assert.strictEqual(effectiveState('warn', true), 'offline');
  assert.strictEqual(effectiveState('ok', false), 'ok');
  assert.strictEqual(effectiveState('stale', false), 'stale');
});

test('buttonsFor groups buttons and gives lights a short label and their on state', () => {
  const status = { sources: { smart_home: { state: 'ok', data: {
    lights: [{ name: 'Office Ceiling', on: true }, { name: 'Balcony', on: false }],
    speakers: [{ name: 'Kitchen', state: 'playing', volume: 30 }] } } } };
  const b = Object.fromEntries(buttonsFor(status).map(x => [x.action, x]));
  assert.strictEqual(b.restart_plex.group, 'system');
  assert.strictEqual(b['lights_toggle_Office Ceiling'].group, 'lights');
  assert.strictEqual(b['lights_toggle_Office Ceiling'].label, 'Office Ceiling');
  assert.strictEqual(b['lights_toggle_Office Ceiling'].on, true);
  assert.strictEqual(b['lights_toggle_Balcony'].on, false);
  assert.strictEqual(b['volume_down_Kitchen'].group, 'speaker:Kitchen');
  assert.strictEqual(b['volume_down_Kitchen'].label, '\u2212');
  assert.strictEqual(b['play_pause_Kitchen'].label, '\u25B6\u2759\u2759');
  assert.strictEqual(b['volume_up_Kitchen'].label, '+');
});

const sources = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, { state: v }]));

test('sourceLevels folds states into ok/warn/offline and skips unconfigured or unknown sources', () => {
  assert.deepStrictEqual(
    sourceLevels(sources({ nuc: 'ok', plex: 'stale', disks: 'warn', pihole: 'offline', smart_home: 'unconfigured', mystery: 'warn' })),
    { nuc: 'ok', plex: 'warn', disks: 'warn', pihole: 'offline' });
});

test('first look only greets: problems that already exist stay silent (the panel shows them)', () => {
  const lv = sourceLevels(sources({ nuc: 'ok', disks: 'warn', pihole: 'offline' }));
  assert.deepStrictEqual(announcements(null, lv), [{ sfx: 'boot', say: 'online' }]);
  assert.deepStrictEqual(announcements(lv, lv), []);
});

test('first look with everything fine just greets', () => {
  assert.deepStrictEqual(announcements(null, sourceLevels(sources({ nuc: 'ok' }))), [{ sfx: 'boot', say: 'online' }]);
});

test('only changes are announced afterwards', () => {
  const before = { nuc: 'ok', disks: 'warn', plex: 'ok', pihole: 'ok' };
  const after = { nuc: 'warn', disks: 'warn', plex: 'offline', pihole: 'ok' };
  assert.deepStrictEqual(announcements(before, after), [
    { sfx: 'warn', say: 'warn_nuc' },
    { sfx: 'alarm', say: 'offline_plex' }]);
  assert.deepStrictEqual(announcements(after, after), []);
});

test('recovery is announced, warn becoming offline is an alarm', () => {
  assert.deepStrictEqual(announcements({ disks: 'warn' }, { disks: 'ok' }), [{ sfx: 'ok', say: 'ok_disks' }]);
  assert.deepStrictEqual(announcements({ disks: 'warn' }, { disks: 'offline' }), [{ sfx: 'alarm', say: 'offline_disks' }]);
});

test('a source appearing for the first time later is treated as a change from nothing', () => {
  assert.deepStrictEqual(announcements({ nuc: 'ok' }, { nuc: 'ok', plex: 'warn' }), [{ sfx: 'warn', say: 'warn_plex' }]);
  assert.deepStrictEqual(announcements({ nuc: 'ok' }, { nuc: 'ok', plex: 'ok' }), []);
});

test('greeting follows the time of day', () => {
  const { greetingKey } = require('./logic.js');
  assert.strictEqual(greetingKey(6), 'good_morning');
  assert.strictEqual(greetingKey(11), 'good_morning');
  assert.strictEqual(greetingKey(12), 'good_afternoon');
  assert.strictEqual(greetingKey(16), 'good_afternoon');
  assert.strictEqual(greetingKey(17), 'good_evening');
  assert.strictEqual(greetingKey(23), 'good_evening');
  assert.strictEqual(greetingKey(2), 'good_evening');
});

test('tap pattern: 3 quick taps is a quip, 5 is party, slow taps are nothing', () => {
  const { makeTapCounter } = require('./logic.js');
  const fired = [];
  const tap = makeTapCounter({ windowMs: 600, patterns: { 3: 'quip', 5: 'party' }, settleMs: 500 },
    (name) => fired.push(name));
  let t = 0;
  const hit = (gap) => { t += gap; tap.tap(t); };
  hit(0); hit(200); hit(200);          // three quick
  tap.flush(t + 600);                  // let it settle
  assert.deepStrictEqual(fired, ['quip']);
  fired.length = 0;
  hit(1000); hit(150); hit(150); hit(150); hit(150);   // five quick
  tap.flush(t + 600);
  assert.deepStrictEqual(fired, ['party']);
  fired.length = 0;
  hit(1000); hit(900); hit(900);       // slow taps never chain
  tap.flush(t + 600);
  assert.deepStrictEqual(fired, []);
  hit(1000); hit(200);                 // two quick: no pattern
  tap.flush(t + 600);
  assert.deepStrictEqual(fired, []);
});

test('pickAccent finds the dominant vivid colour of album art and ignores greys', () => {
  const { pickAccent } = require('./logic.js');
  const px = [];
  for (let i = 0; i < 60; i++) px.push(200, 30, 40, 255);     // red
  for (let i = 0; i < 20; i++) px.push(120, 120, 120, 255);   // grey
  for (let i = 0; i < 10; i++) px.push(30, 40, 220, 255);     // some blue
  const hex = pickAccent(px);
  assert.match(hex, /^#[0-9a-f]{6}$/);
  const r = parseInt(hex.slice(1, 3), 16), b = parseInt(hex.slice(5, 7), 16);
  assert.ok(r > 180 && b < 120, hex);
  const grey = []; for (let i = 0; i < 50; i++) grey.push(100, 100, 100, 255);
  assert.strictEqual(pickAccent(grey), null);
  assert.strictEqual(pickAccent([]), null);
});

test('pickAccent brightens a dark colour so it glows on a dark panel', () => {
  const { pickAccent } = require('./logic.js');
  const px = []; for (let i = 0; i < 40; i++) px.push(60, 10, 12, 255);
  const hex = pickAccent(px);
  assert.ok(Math.max(parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)) >= 190, hex);
});

test('audio normaliser: steady room noise is silent, a loud burst reaches near 1, then it settles', () => {
  const { makeAudioNormalizer } = require('./logic.js');
  const n = makeAudioNormalizer();
  let v = 0;
  for (let i = 0; i < 200; i++) v = n.feed(12);            // a steady hum
  assert.ok(v < 0.1, 'noise floor ' + v);
  let peak = 0;
  for (let i = 0; i < 6; i++) peak = Math.max(peak, n.feed(80));
  assert.ok(peak > 0.7, 'burst ' + peak);
  for (let i = 0; i < 400; i++) v = n.feed(12);
  assert.ok(v < 0.1, 'settled ' + v);
});

test('idle timer: sleeps after the quiet period, wakes on touch, and tells the caller the first touch only woke it', () => {
  const { makeIdleTimer } = require('./logic.js');
  const changes = [];
  const idle = makeIdleTimer({ afterMs: 1000 }, (on) => changes.push(on));
  idle.touch(0);
  idle.tick(900); assert.deepStrictEqual(changes, []);
  idle.tick(1000); assert.deepStrictEqual(changes, [true]);
  idle.tick(5000); assert.deepStrictEqual(changes, [true]);          // fires once
  assert.strictEqual(idle.idle, true);
  assert.strictEqual(idle.touch(5100), true);                        // this touch only woke it
  assert.deepStrictEqual(changes, [true, false]);
  assert.strictEqual(idle.touch(5200), false);                       // ordinary touch afterwards
  idle.tick(5900); assert.deepStrictEqual(changes, [true, false]);
  idle.tick(6200); assert.deepStrictEqual(changes, [true, false, true]);
});

test('idle timer: poke resets the clock and wakes without swallowing anything', () => {
  const { makeIdleTimer } = require('./logic.js');
  const changes = [];
  const idle = makeIdleTimer({ afterMs: 1000 }, (on) => changes.push(on));
  idle.touch(0); idle.tick(1000);
  idle.poke(1100);
  assert.deepStrictEqual(changes, [true, false]);
  idle.tick(1900); assert.deepStrictEqual(changes, [true, false]);
});

test('ultron fight: a weak Ultron loses on his own, and taps make it quicker', () => {
  const { makeFight, fightOdds } = require('./logic.js');
  const f = makeFight(fightOdds(0.9));
  let t = 0;
  while (!f.won && !f.lost && t < 200) { f.step(0.5, 0, 0); t += 0.5; }
  assert.ok(f.won && !f.lost && t >= 20 && t <= 50, 'solo ' + t);
  const g = makeFight(fightOdds(0.9)); let t2 = 0;
  while (!g.won && !g.lost && t2 < 200) { g.step(0.5, 1, 0); t2 += 0.5; }
  assert.ok(g.won && t2 < t * 0.6, 'with taps ' + t2);
});

test('ultron fight: a strong Ultron beats an idle Jarvis, but tapping can still turn it around', () => {
  const { makeFight, fightOdds } = require('./logic.js');
  const f = makeFight(fightOdds(0.1));
  let t = 0;
  while (!f.won && !f.lost && t < 200) { f.step(0.5, 0, 0); t += 0.5; }
  assert.ok(f.lost && !f.won && t < 30, 'idle ' + t);
  const g = makeFight(fightOdds(0.1));
  t = 0;
  while (!g.won && !g.lost && t < 200) { g.step(0.5, 1, 0); t += 0.5; }
  assert.ok(g.won, 'tapping wins');
});

test('ultron fight: surges push Jarvis back and can lose it; a finished fight stays finished', () => {
  const { makeFight, fightOdds } = require('./logic.js');
  const h = makeFight(fightOdds(0.9));
  h.step(5, 0, 0); const before = h.control;
  h.step(0.1, 0, 0.1);
  assert.ok(h.control < before);
  for (let i = 0; i < 50; i++) h.step(0.1, 0, 1);
  assert.strictEqual(h.control, 0);
  assert.strictEqual(h.lost, true);
  assert.strictEqual(h.won, false);
  h.step(10, 5, 0);                       // nothing revives a lost fight
  assert.strictEqual(h.lost, true); assert.strictEqual(h.control, 0);
});

test('ultron fight: half of fights go to a strong Ultron', () => {
  const { fightOdds } = require('./logic.js');
  assert.ok(fightOdds(0.49).rate < 0);
  assert.ok(fightOdds(0.51).rate > 0);
});

test('guest AI: a stay saved before a reload resumes only while it is still running', () => {
  const { activeGuest } = require('./logic.js');
  const raw = JSON.stringify({ id: 'edith', until: 5000 });
  assert.deepStrictEqual(activeGuest(raw, 4000), { id: 'edith', until: 5000 });
  assert.strictEqual(activeGuest(raw, 5000), null);          // over
  assert.strictEqual(activeGuest(null, 1), null);
  assert.strictEqual(activeGuest('not json', 1), null);
  assert.strictEqual(activeGuest(JSON.stringify({ until: 9999 }), 1), null);   // no id
});

test('ad-block button: pauses while blocking, flips to enable while paused, then back', () => {
  const st = (blocking) => ({ sources: { pihole: { state: 'ok', data: { blocking } } } });
  const pick = (s) => buttonsFor(s).find((b) => b.action === 'pause_pihole' || b.action === 'resume_pihole');
  assert.deepStrictEqual([pick(st(true)).action, pick(st(true)).label], ['pause_pihole', 'Pause Pihole']);
  assert.deepStrictEqual([pick(st(false)).action, pick(st(false)).label], ['resume_pihole', 'Enable Pihole']);
  assert.strictEqual(pick({ sources: {} }).action, 'pause_pihole');          // unknown state: the normal pause button
  assert.strictEqual(pick(st(false)).hold, false);                           // enabling is safe: a plain tap
});

test('climateRows: label, temperature and humidity per room; a low battery changes nothing', () => {
  const { climateRows } = require('./logic.js');
  const rows = climateRows([{ name: 'Office', temp_f: 71, humidity: 41, battery: 59 },
                            { name: 'Living Room', temp_f: 63, humidity: 55, battery: 20 }]);
  assert.deepStrictEqual(rows[0], { label: 'OFFICE', temp: '71°', hum: '41%' });
  assert.deepStrictEqual(rows[1], { label: 'LIVING ROOM', temp: '63°', hum: '55%' });
  assert.deepStrictEqual(climateRows(undefined), []);
  assert.deepStrictEqual(climateRows([]), []);
});

test('speaker buttons appear only for speakers that are playing, and the audio row vanishes when none are', () => {
  const st = (speakers) => ({ sources: { smart_home: { state: 'ok', data: { lights: [], speakers } } } });
  const audio = (s) => buttonsFor(s).filter((b) => b.group.startsWith('speaker:')).map((b) => b.action);
  assert.deepStrictEqual(audio(st([{ name: 'Office', state: 'playing' }, { name: 'Kitchen', state: 'idle' },
                                   { name: 'Soundbar', state: 'off' }, { name: 'Bedroom', state: 'paused' }])),
                         ['volume_down_Office', 'play_pause_Office', 'volume_up_Office']);
  assert.deepStrictEqual(audio(st([{ name: 'Kitchen', state: 'idle' }])), []);
});

test('balancedRows: a crowded row of buttons is split into evenly sized lines, never 8 + 2', () => {
  const { balancedRows } = require('./logic.js');
  assert.deepStrictEqual(balancedRows(10, 8), [5, 5]);
  assert.deepStrictEqual(balancedRows(7, 8), [7]);
  assert.deepStrictEqual(balancedRows(8, 8), [8]);
  assert.deepStrictEqual(balancedRows(9, 8), [5, 4]);
  assert.deepStrictEqual(balancedRows(11, 8), [6, 5]);
  assert.deepStrictEqual(balancedRows(17, 8), [6, 6, 5]);
  assert.deepStrictEqual(balancedRows(0, 8), []);
  assert.deepStrictEqual(balancedRows(4, 5), [4]);
});

test('militaryTime: 24-hour HH:MM everywhere, never AM/PM', () => {
  const { militaryTime } = require('./logic.js');
  assert.strictEqual(militaryTime(new Date(2026, 10, 19, 6, 5)), '06:05');
  assert.strictEqual(militaryTime(new Date(2026, 10, 19, 18, 6)), '18:06');
  assert.strictEqual(militaryTime(new Date(2026, 10, 19, 0, 7)), '00:07');
  assert.strictEqual(militaryTime(new Date(2026, 10, 19, 23, 59)), '23:59');
});

test('fitFontSize: scales a font so text measured at basePx ends up exactly as wide as the target', () => {
  const { fitFontSize } = require('./logic.js');
  assert.strictEqual(fitFontSize(100, 400, 200), 50);
  assert.strictEqual(fitFontSize(100, 200, 300), 150);
  assert.strictEqual(fitFontSize(100, 0, 300), 100);
  assert.strictEqual(fitFontSize(100, 200, 0), 100);
});

test('spoken replies carry who is speaking, so a guest is neither muted nor given the Jarvis treatment', () => {
  const { replyKey, voiceOfKey } = require('./logic.js');
  assert.strictEqual(replyKey(12, ''), 'reply:12');
  assert.strictEqual(replyKey(12, 'e_'), 'reply:12:e_');
  assert.strictEqual(voiceOfKey('reply:12'), 'jv_');
  assert.strictEqual(voiceOfKey('reply:12:jo_'), 'jo_');
  assert.strictEqual(voiceOfKey('u_intro1'), 'u_intro1');
  assert.strictEqual(voiceOfKey('good_evening'), 'good_evening');
});

test('isLongPress: a still finger held on the core for about two seconds, nothing shorter or wandering', () => {
  const { isLongPress, LONG_PRESS_MS } = require('./logic.js');
  assert.strictEqual(LONG_PRESS_MS, 1800);
  assert.strictEqual(isLongPress(1800, 0), true);
  assert.strictEqual(isLongPress(2500, 5), true);
  assert.strictEqual(isLongPress(1799, 0), false);
  assert.strictEqual(isLongPress(400, 0), false);               // an ordinary tap
  assert.strictEqual(isLongPress(3000, 40), false);             // dragged, not held
});

test('the core tap table: six taps start the tour, and no tap count is claimed twice', () => {
  const { TAP_PATTERNS } = require('./logic.js');
  assert.deepStrictEqual(TAP_PATTERNS, { 3: 'quip', 4: 'guest', 5: 'party', 6: 'tour', 7: 'boot', 9: 'ultron' });
});

test('buttonsFor: the bottom buttons are in alphabetical order within each row group', () => {
  const status = { sources: { pihole: { state: 'ok', data: { blocking: true } }, smart_home: { state: 'ok', data: {
    lights: [{ name: 'TV Lights', on: false }, { name: 'balcony', on: true }, { name: 'Office Panels', on: false }, { name: 'Bedroom Lamp', on: false }],
    speakers: [{ name: 'Office', state: 'playing' }, { name: 'Kitchen', state: 'playing' }] } } } };
  const b = buttonsFor(status);
  const labels = (g) => b.filter((x) => x.group === g).map((x) => x.label);
  assert.deepStrictEqual(labels('system'), ['Check disks', 'Pause Pihole', 'Restart Plex', 'Restart Samba']);
  assert.deepStrictEqual(labels('lights'), ['balcony', 'Bedroom Lamp', 'Office Panels', 'TV Lights']);
  const speakers = [...new Set(b.filter((x) => x.group.startsWith('speaker:')).map((x) => x.group))];
  assert.deepStrictEqual(speakers, ['speaker:Kitchen', 'speaker:Office']);
  assert.deepStrictEqual(labels('speaker:Kitchen'), ['\u2212', '\u25B6\u2759\u2759', '+']);   // a speaker's own controls keep their order
});
