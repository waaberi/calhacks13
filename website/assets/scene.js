// A tiny hand-rolled 3D modeler for the marketing page.
// The model is a stack of square rings (a "loft"), which is enough to show
// extrude, inset, bevel, loop cut, move, rotate and scale on a shared object.
// It is an illustration drawn in the browser, not a capture of Coplanar.

const SQRT2 = Math.SQRT2;
const TAU = Math.PI * 2;
const MAX_RINGS = 22;
const MAX_HEIGHT = 5.2;

export const SEATS = {
  headset: { name: 'Headset', color: '#6ff2c1', ink: '#06261b' },
  desktop: { name: 'Desktop', color: '#ffa24a', ink: '#2e1500' },
};

const cube = () => [
  { y: 0, s: 1, tw: 0 },
  { y: 2, s: 1, tw: 0 },
];

const clone = (rings) => rings.map((r) => ({ ...r }));
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const fmt = (n, unit) => `${n.toFixed(2)} ${unit}`;

// Each operation returns { from, to, sel, label, detail } where from/to have
// equal length so the change can be animated by interpolation.
export const OPS = {
  extrude: {
    label: 'Extrude',
    key: 'E',
    can: (m) => m.rings.length < MAX_RINGS && top(m).y < MAX_HEIGHT - 0.3,
    run(m, amount = 0.7) {
      const t = top(m);
      const h = Math.min(amount, MAX_HEIGHT - t.y);
      return {
        from: [...clone(m.rings), { ...t }],
        to: [...clone(m.rings), { ...t, y: t.y + h }],
        sel: m.rings.length,
        detail: fmt(h, 'm'),
      };
    },
  },
  inset: {
    label: 'Inset',
    key: 'I',
    can: (m) => m.rings.length < MAX_RINGS && top(m).s > 0.3,
    run(m, factor = 0.72) {
      const t = top(m);
      const d = t.s * (1 - factor);
      return {
        from: [...clone(m.rings), { ...t }],
        to: [...clone(m.rings), { ...t, s: t.s - d }],
        sel: m.rings.length,
        detail: fmt(d, 'm'),
      };
    },
  },
  bevel: {
    label: 'Bevel',
    key: 'Ctrl B',
    can: (m) => {
      const n = m.rings.length;
      return n < MAX_RINGS && top(m).y - m.rings[n - 2].y > 0.25 && top(m).s > 0.3;
    },
    run(m, amount = 0.16) {
      const n = m.rings.length;
      const t = top(m);
      const below = m.rings[n - 2];
      const b = Math.min(amount, t.s * 0.4, (t.y - below.y) * 0.45);
      const base = clone(m.rings).slice(0, n - 1);
      return {
        from: [...base, { ...t }, { ...t }],
        to: [...base, { ...t, y: t.y - b }, { ...t, s: t.s - b }],
        sel: n,
        detail: fmt(b, 'm'),
      };
    },
  },
  loopcut: {
    label: 'Loop cut',
    key: 'Ctrl R',
    can: (m) => m.rings.length < MAX_RINGS && tallest(m).h > 0.3,
    run(m) {
      const { i } = tallest(m);
      const a = m.rings[i];
      const b = m.rings[i + 1];
      const mid = { y: (a.y + b.y) / 2, s: (a.s + b.s) / 2, tw: (a.tw + b.tw) / 2 };
      const from = clone(m.rings);
      const to = clone(m.rings);
      from.splice(i + 1, 0, { ...a });
      to.splice(i + 1, 0, mid);
      return { from, to, sel: i + 1, detail: `at ${mid.y.toFixed(2)} m` };
    },
  },
  move: {
    label: 'Move',
    key: 'G',
    can: (m) => m.sel > 0,
    run(m, amount = 0.35) {
      const i = m.sel;
      const r = m.rings[i];
      const lo = m.rings[i - 1].y;
      const hi = i < m.rings.length - 1 ? m.rings[i + 1].y : MAX_HEIGHT;
      let y = clamp(r.y + amount, lo, hi);
      if (Math.abs(y - r.y) < 0.02) y = clamp(r.y - amount, lo, hi);
      const to = clone(m.rings);
      to[i] = { ...r, y };
      return { from: clone(m.rings), to, sel: i, detail: `Z ${fmt(y - r.y, 'm')}` };
    },
  },
  rotate: {
    label: 'Rotate',
    key: 'R',
    can: () => true,
    run(m, angle = Math.PI / 8) {
      const i = m.sel;
      const to = clone(m.rings);
      to[i] = { ...to[i], tw: to[i].tw + angle };
      return { from: clone(m.rings), to, sel: i, detail: `Z ${((angle * 180) / Math.PI).toFixed(1)}°` };
    },
  },
  scale: {
    label: 'Scale',
    key: 'S',
    can: () => true,
    run(m, factor = 1.25) {
      const i = m.sel;
      const r = m.rings[i];
      let s = clamp(r.s * factor, 0.12, 2.1);
      if (Math.abs(s - r.s) < 0.01) s = clamp(r.s / factor, 0.12, 2.1);
      const to = clone(m.rings);
      to[i] = { ...r, s };
      return { from: clone(m.rings), to, sel: i, detail: `× ${(s / r.s).toFixed(2)}` };
    },
  },
};

function top(m) {
  return m.rings[m.rings.length - 1];
}

function tallest(m) {
  let best = { i: 0, h: -1 };
  for (let i = 0; i < m.rings.length - 1; i++) {
    const h = m.rings[i + 1].y - m.rings[i].y;
    if (h > best.h) best = { i, h };
  }
  return best;
}

function corners(r) {
  const out = [];
  for (let k = 0; k < 4; k++) {
    const a = r.tw + (k * Math.PI) / 2 + Math.PI / 4;
    out.push([Math.cos(a) * r.s * SQRT2, r.y, Math.sin(a) * r.s * SQRT2]);
  }
  return out;
}

function newell(pts) {
  let x = 0, y = 0, z = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % pts.length];
    x += (a[1] - b[1]) * (a[2] + b[2]);
    y += (a[2] - b[2]) * (a[0] + b[0]);
    z += (a[0] - b[0]) * (a[1] + b[1]);
  }
  const len = Math.hypot(x, y, z);
  return len < 1e-6 ? null : [x / len, y / len, z / len];
}

const LIGHT = (() => {
  const v = [0.45, 0.82, 0.36];
  const l = Math.hypot(...v);
  return v.map((c) => c / l);
})();

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function createScene(canvas, opts = {}) {
  const ctx = canvas.getContext('2d');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const o = {
    avatars: true,
    autoRotate: true,
    clay: '#dcd5c6',
    yaw: -0.65,
    pitch: 0.42,
    ...opts,
  };

  const model = { rings: cube(), sel: 1 };
  const history = [];
  const future = [];
  const queue = [];
  const listeners = new Set();
  let anim = null;
  let editing = null; // { seat, ring }
  let yaw = o.yaw;
  let pitch = o.pitch;
  let yawVel = 0;
  let targetY = 1;
  let dist = 8.5;
  let lastInteract = -1e9;
  let visible = true;
  let raf = 0;
  let last = performance.now();
  let W = 0, H = 0, DPR = 1;
  let clock = 0;

  const clayRgb = hexToRgb(o.clay);
  const cursor = { x: 0, y: 0, tx: 0, ty: 0, init: false };
  const headset = { phase: 0.9 };

  function emit(type, detail) {
    for (const fn of listeners) fn({ type, ...detail });
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.max(1, rect.width);
    H = Math.max(1, rect.height);
    canvas.width = Math.round(W * DPR);
    canvas.height = Math.round(H * DPR);
    wake();
  }

  // Camera
  function camera() {
    const cy = Math.cos(yaw), sy = Math.sin(yaw);
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    const F = Math.min(W, H * 1.25) * 1.15;
    return {
      cy, sy, cp, sp, F,
      pos: [dist * cp * sy, targetY + dist * sp, dist * cp * cy],
    };
  }

  function project(cam, p) {
    const x = p[0], y = p[1] - targetY, z = p[2];
    const x1 = x * cam.cy - z * cam.sy;
    const z1 = x * cam.sy + z * cam.cy;
    const depth = dist - (y * cam.sp + z1 * cam.cp);
    const vy = y * cam.cp - z1 * cam.sp;
    const d = Math.max(depth, 0.1);
    return [W / 2 + (cam.F * x1) / d, H * 0.54 - (cam.F * vy) / d, depth];
  }

  function currentRings() {
    if (!anim) return model.rings;
    const t = ease(anim.t);
    return anim.from.map((a, i) => {
      const b = anim.to[i];
      return { y: a.y + (b.y - a.y) * t, s: a.s + (b.s - a.s) * t, tw: a.tw + (b.tw - a.tw) * t };
    });
  }

  function buildFaces(rings) {
    const faces = [];
    const cs = rings.map(corners);
    faces.push({ pts: [...cs[0]], ring: -1 });
    for (let i = 0; i < rings.length - 1; i++) {
      for (let k = 0; k < 4; k++) {
        const k2 = (k + 1) % 4;
        faces.push({ pts: [cs[i][k], cs[i + 1][k], cs[i + 1][k2], cs[i][k2]], ring: i });
      }
    }
    faces.push({ pts: [...cs[cs.length - 1]].reverse(), ring: rings.length - 1, cap: true });
    return { faces, cs };
  }

  function draw() {
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const cam = camera();
    const rings = currentRings();

    drawGrid(cam);

    // Contact shadow
    const base = rings[0];
    const sh = project(cam, [0, 0, 0]);
    const shR = (cam.F * base.s * 1.9) / sh[2];
    const g = ctx.createRadialGradient(sh[0], sh[1], 0, sh[0], sh[1], shR);
    g.addColorStop(0, 'rgba(0,0,0,0.45)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.ellipse(sh[0], sh[1], shR, shR * 0.42, 0, 0, TAU);
    ctx.fill();

    const { faces, cs } = buildFaces(rings);
    const drawn = [];
    for (const f of faces) {
      const n = newell(f.pts);
      if (!n) continue;
      let cx = 0, cyy = 0, cz = 0;
      for (const p of f.pts) { cx += p[0]; cyy += p[1]; cz += p[2]; }
      cx /= f.pts.length; cyy /= f.pts.length; cz /= f.pts.length;
      const toCam = [cam.pos[0] - cx, cam.pos[1] - cyy, cam.pos[2] - cz];
      if (n[0] * toCam[0] + n[1] * toCam[1] + n[2] * toCam[2] <= 0) continue;
      const sp = f.pts.map((p) => project(cam, p));
      const depth = sp.reduce((a, p) => a + p[2], 0) / sp.length;
      const lambert = Math.max(0, n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2]);
      const rim = Math.pow(1 - Math.abs(n[1]), 2) * 0.08;
      drawn.push({ sp, depth, shade: 0.42 + lambert * 0.58 + rim, f });
    }
    drawn.sort((a, b) => b.depth - a.depth);

    const selRing = anim ? anim.sel : model.sel;
    const seat = editing ? SEATS[editing.seat] : null;
    const selRgb = seat ? hexToRgb(seat.color) : null;

    for (const d of drawn) {
      let [r, gg, b] = clayRgb.map((c) => c * d.shade);
      const isSel = d.f.cap ? selRing === rings.length - 1 : false;
      if (seat && isSel) {
        r = r * 0.6 + selRgb[0] * 0.4 * d.shade;
        gg = gg * 0.6 + selRgb[1] * 0.4 * d.shade;
        b = b * 0.6 + selRgb[2] * 0.4 * d.shade;
      }
      ctx.fillStyle = `rgb(${r | 0},${gg | 0},${b | 0})`;
      ctx.beginPath();
      d.sp.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = 'rgba(20,18,15,0.38)';
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // Selected edge loop, outlined in the editor's colour.
    const loopRing = rings[selRing];
    if (loopRing) {
      const pts = cs[selRing].map((p) => project(cam, p));
      ctx.save();
      ctx.lineJoin = 'round';
      ctx.strokeStyle = seat ? seat.color : 'rgba(255,255,255,0.85)';
      ctx.lineWidth = seat ? 2.5 : 1.5;
      ctx.setLineDash(seat ? [] : [4, 4]);
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
      ctx.closePath();
      ctx.stroke();
      ctx.restore();
      for (const p of pts) {
        ctx.fillStyle = seat ? seat.color : '#fff';
        ctx.beginPath();
        ctx.arc(p[0], p[1], seat ? 3 : 2, 0, TAU);
        ctx.fill();
      }
    }

    if (o.avatars) drawAvatars(cam, rings, cs, selRing);
  }

  function drawGrid(cam) {
    const R = 6;
    ctx.lineWidth = 1;
    for (let i = -R; i <= R; i++) {
      const fade = 1 - Math.abs(i) / (R + 1);
      for (const axis of [0, 1]) {
        const a = axis ? [i, 0, -R] : [-R, 0, i];
        const b = axis ? [i, 0, R] : [R, 0, i];
        const pa = project(cam, a), pb = project(cam, b);
        if (pa[2] < 0.2 || pb[2] < 0.2) continue;
        if (i === 0) {
          ctx.strokeStyle = axis ? 'rgba(132,198,72,0.55)' : 'rgba(232,84,84,0.6)';
        } else {
          ctx.strokeStyle = `rgba(255,255,255,${0.07 * fade})`;
        }
        ctx.beginPath();
        ctx.moveTo(pa[0], pa[1]);
        ctx.lineTo(pb[0], pb[1]);
        ctx.stroke();
      }
    }
  }

  function loopCenter(cam, cs, i) {
    const pts = cs[i] || cs[cs.length - 1];
    const c = [0, 0, 0];
    for (const p of pts) { c[0] += p[0] / 4; c[1] += p[1] / 4; c[2] += p[2] / 4; }
    return { world: c, screen: project(cam, c), pts };
  }

  function tag(x, y, text, seat, align = 'left') {
    ctx.font = '600 11px "JetBrains Mono", ui-monospace, monospace';
    const w = ctx.measureText(text).width + 14;
    const h = 20;
    const x0 = align === 'left' ? x : x - w;
    ctx.fillStyle = seat.color;
    ctx.beginPath();
    ctx.roundRect(x0, y, w, h, 6);
    ctx.fill();
    ctx.fillStyle = seat.ink;
    ctx.fillText(text, x0 + 7, y + 14);
  }

  function drawAvatars(cam, rings, cs, selRing) {
    const target = loopCenter(cam, cs, selRing);
    const actor = editing ? editing.seat : null;

    // Headset: a floating visor with a controller ray.
    const hs = SEATS.headset;
    // Keep the headset beside the model, drifting gently, always in view.
    const az = yaw - 1.05 + Math.sin(headset.phase) * 0.18;
    const R = 2.9;
    const hp = [Math.sin(az) * R, targetY + 1.25 + Math.sin(headset.phase * 1.7) * 0.08, Math.cos(az) * R];
    const hpS = project(cam, hp);
    const scale = cam.F / hpS[2];
    const hand = project(cam, [Math.sin(az + 0.18) * R * 0.85, hp[1] - 0.95, Math.cos(az + 0.18) * R * 0.85]);
    const aimAt = actor === 'headset' ? target.screen : project(cam, [0, targetY, 0]);

    ctx.save();
    ctx.strokeStyle = hs.color;
    ctx.globalAlpha = actor === 'headset' ? 0.95 : 0.35;
    ctx.lineWidth = actor === 'headset' ? 2 : 1.25;
    ctx.setLineDash(actor === 'headset' ? [] : [3, 5]);
    ctx.beginPath();
    ctx.moveTo(hand[0], hand[1]);
    ctx.lineTo(aimAt[0], aimAt[1]);
    ctx.stroke();
    ctx.restore();
    if (actor === 'headset') {
      ctx.fillStyle = hs.color;
      ctx.beginPath();
      ctx.arc(aimAt[0], aimAt[1], 4, 0, TAU);
      ctx.fill();
    }
    // controller
    ctx.fillStyle = '#1b1d22';
    ctx.strokeStyle = hs.color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(hand[0], hand[1], Math.max(4, scale * 0.07), 0, TAU);
    ctx.fill();
    ctx.stroke();
    // visor
    const vw = clamp(scale * 0.5, 24, 64), vh = vw * 0.5;
    ctx.save();
    ctx.translate(hpS[0], hpS[1]);
    ctx.fillStyle = '#1b1d22';
    ctx.strokeStyle = hs.color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(-vw / 2, -vh / 2, vw, vh, vh * 0.45);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = hs.color;
    ctx.globalAlpha = 0.85;
    ctx.beginPath();
    ctx.roundRect(-vw / 2 + 4, -vh / 2 + 4, vw - 8, vh - 8, vh * 0.3);
    ctx.fill();
    ctx.restore();
    tag(hpS[0] + vw / 2 + 6, hpS[1] - 10, actor === 'headset' ? `${hs.name} · editing` : hs.name, hs);

    // Desktop: an arrow cursor.
    const ds = SEATS.desktop;
    const dTarget = actor === 'desktop'
      ? target.screen
      : project(cam, [Math.cos(yaw + 2.2) * 2.4, 0.6, Math.sin(yaw + 2.2) * 2.4]);
    cursor.tx = dTarget[0];
    cursor.ty = dTarget[1];
    if (!cursor.init) { cursor.x = cursor.tx; cursor.y = cursor.ty; cursor.init = true; }
    const x = cursor.x, y = cursor.y;
    ctx.save();
    ctx.translate(x, y);
    ctx.fillStyle = ds.color;
    ctx.strokeStyle = '#141414';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(0, 18);
    ctx.lineTo(4.5, 13.5);
    ctx.lineTo(8, 21);
    ctx.lineTo(11, 19.5);
    ctx.lineTo(7.6, 12.4);
    ctx.lineTo(13.5, 12.4);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();
    tag(x + 14, y + 16, actor === 'desktop' ? `${ds.name} · editing` : ds.name, ds);
  }

  // Animation loop
  function frame(now) {
    raf = 0;
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    clock += dt;
    let busy = false;

    if (anim) {
      anim.t = Math.min(1, anim.t + dt / anim.dur);
      busy = true;
      if (anim.t >= 1) finishAnim();
    } else if (queue.length) {
      startNext();
      busy = true;
    }

    // Frame the model as it grows.
    const rings = currentRings();
    const hMax = rings.reduce((a, r) => Math.max(a, r.y), 0);
    const sMax = rings.reduce((a, r) => Math.max(a, r.s), 0);
    const wantY = hMax * 0.48;
    const wantDist = 5.6 + Math.max(hMax * 0.95, sMax * 2.6);
    targetY += (wantY - targetY) * Math.min(1, dt * 3);
    dist += (wantDist - dist) * Math.min(1, dt * 3);
    if (Math.abs(wantY - targetY) > 0.002 || Math.abs(wantDist - dist) > 0.002) busy = true;

    if (Math.abs(yawVel) > 0.0005) {
      yaw += yawVel;
      yawVel *= 0.92;
      busy = true;
    } else if (o.autoRotate && !reduced && now - lastInteract > 2500) {
      yaw += dt * 0.12;
      busy = true;
    }

    if (o.avatars && !reduced) {
      headset.phase += dt * 0.18;
      busy = true;
    }
    const k = Math.min(1, dt * 7);
    cursor.x += (cursor.tx - cursor.x) * k;
    cursor.y += (cursor.ty - cursor.y) * k;
    if (Math.hypot(cursor.tx - cursor.x, cursor.ty - cursor.y) > 0.5) busy = true;

    draw();
    if (busy && visible) raf = requestAnimationFrame(frame);
  }

  function wake() {
    if (!raf && visible) {
      last = performance.now();
      raf = requestAnimationFrame(frame);
    }
  }

  function startNext() {
    const job = queue.shift();
    if (job.kind === 'undo' || job.kind === 'redo') {
      const src = job.kind === 'undo' ? history : future;
      const dst = job.kind === 'undo' ? future : history;
      const entry = src.pop();
      if (!entry) return;
      dst.push(entry);
      const target = job.kind === 'undo' ? entry.before : entry.after;
      // Pad so the change can be interpolated.
      const from = clone(model.rings);
      const to = clone(target.rings);
      while (from.length < to.length) from.push({ ...from[from.length - 1] });
      while (to.length < from.length) to.push({ ...to[to.length - 1] });
      anim = { from, to, t: 0, dur: reduced ? 0.001 : job.fast ? 0.18 : 0.38, sel: target.sel, final: target, seat: null };
      editing = null;
      emit(job.kind, { entry, history: history.length, future: future.length });
      return;
    }
    const op = OPS[job.op];
    if (!op.can(model)) {
      emit('refused', { op: job.op, seat: job.seat });
      return;
    }
    const res = op.run(model, job.arg);
    const before = { rings: clone(model.rings), sel: model.sel };
    const after = { rings: clone(res.to), sel: res.sel };
    const entry = { op: job.op, label: op.label, seat: job.seat, detail: res.detail, before, after, id: Math.random() };
    history.push(entry);
    future.length = 0;
    anim = { from: res.from, to: res.to, t: 0, dur: reduced ? 0.001 : 0.75, sel: res.sel, final: after, seat: job.seat, entry };
    editing = { seat: job.seat };
    emit('start', { entry });
  }

  function finishAnim() {
    model.rings = clone(anim.final.rings);
    model.sel = anim.final.sel;
    const entry = anim.entry;
    anim = null;
    editing = null;
    emit('change', { entry, history: history.length, future: future.length });
    if (!queue.length) emit('idle', {});
  }

  // Public API
  const api = {
    apply(op, seat = 'desktop', arg) {
      queue.push({ kind: 'op', op, seat, arg });
      wake();
    },
    undo(fast = false) {
      queue.push({ kind: 'undo', fast });
      wake();
    },
    redo() {
      queue.push({ kind: 'redo' });
      wake();
    },
    reset() {
      queue.length = 0;
      anim = null;
      editing = null;
      model.rings = cube();
      model.sel = 1;
      history.length = 0;
      future.length = 0;
      emit('change', { entry: null, history: 0, future: 0 });
      wake();
    },
    select(i) {
      if (anim) return;
      model.sel = clamp(i, 0, model.rings.length - 1);
      emit('select', { sel: model.sel });
      wake();
    },
    can: (op) => OPS[op].can(model),
    get busy() { return !!anim || queue.length > 0; },
    get pending() { return queue.length + (anim ? 1 : 0); },
    get historyLength() { return history.length; },
    get futureLength() { return future.length; },
    get selection() { return model.sel; },
    get ringCount() { return model.rings.length; },
    on(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    orbit(dYaw, dPitch) {
      yaw += dYaw;
      pitch = clamp(pitch + dPitch, 0.08, 1.2);
      lastInteract = performance.now();
      wake();
    },
    setVisible(v) {
      visible = v;
      if (v) wake();
    },
    // Pick the edge loop nearest to a point in canvas pixels.
    pick(px, py) {
      const cam = camera();
      const cs = model.rings.map(corners);
      let best = { i: -1, d: 22 };
      cs.forEach((pts, i) => {
        const sp = pts.map((p) => project(cam, p));
        for (let k = 0; k < 4; k++) {
          const a = sp[k], b = sp[(k + 1) % 4];
          const d = distToSeg(px, py, a, b);
          if (d < best.d) best = { i, d };
        }
      });
      return best.i;
    },
  };

  // Pointer orbit
  if (o.interactive !== false) {
    let drag = null;
    canvas.addEventListener('pointerdown', (e) => {
      drag = { x: e.clientX, y: e.clientY, moved: 0, id: e.pointerId };
      canvas.setPointerCapture(e.pointerId);
      lastInteract = performance.now();
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      drag.moved += Math.abs(dx) + Math.abs(dy);
      drag.x = e.clientX;
      drag.y = e.clientY;
      yawVel = 0;
      api.orbit(dx * 0.008, dy * 0.006);
      drag.vx = dx * 0.008;
    });
    const end = (e) => {
      if (!drag) return;
      if (drag.moved < 6) {
        const rect = canvas.getBoundingClientRect();
        const i = api.pick(e.clientX - rect.left, e.clientY - rect.top);
        if (i >= 0) api.select(i);
      } else if (!reduced) {
        yawVel = drag.vx || 0;
      }
      drag = null;
      wake();
    };
    canvas.addEventListener('pointerup', end);
    canvas.addEventListener('pointercancel', () => (drag = null));
    canvas.addEventListener('keydown', (e) => {
      const step = e.shiftKey ? 0.3 : 0.12;
      const map = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
      if (map[e.key]) {
        e.preventDefault();
        api.orbit(...map[e.key]);
      } else if (e.key === 'PageUp' || e.key === 'PageDown') {
        e.preventDefault();
        api.select(model.sel + (e.key === 'PageUp' ? 1 : -1));
      }
    });
  }

  new ResizeObserver(resize).observe(canvas);
  new IntersectionObserver((entries) => {
    for (const en of entries) api.setVisible(en.isIntersecting && !document.hidden);
  }, { rootMargin: '80px' }).observe(canvas);
  document.addEventListener('visibilitychange', () => api.setVisible(!document.hidden));
  resize();

  return api;
}

function distToSeg(px, py, a, b) {
  const vx = b[0] - a[0], vy = b[1] - a[1];
  const l2 = vx * vx + vy * vy || 1;
  const t = clamp(((px - a[0]) * vx + (py - a[1]) * vy) / l2, 0, 1);
  return Math.hypot(px - (a[0] + vx * t), py - (a[1] + vy * t));
}
