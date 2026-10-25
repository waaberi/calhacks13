import { createScene, OPS, SEATS } from './scene.js';

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Hero: a shared scene two collaborators take turns editing.
function hero() {
  const canvas = document.getElementById('hero-canvas');
  if (!canvas) return;
  const scene = createScene(canvas);
  const log = document.getElementById('hero-log');
  const toolButtons = [...document.querySelectorAll('#hero-tools [data-op]')];
  const seatButtons = [...document.querySelectorAll('[data-seat]')];
  const undoBtn = document.querySelector('[data-hist="undo"]');
  const redoBtn = document.querySelector('[data-hist="redo"]');
  const resetBtn = document.querySelector('[data-hist="reset"]');
  let seat = 'headset';
  let userTouched = false;
  let demoTimer = 0;

  const script = [
    ['desktop', 'inset', 0.8],
    ['headset', 'extrude', 1.0],
    ['desktop', 'scale', 1.25],
    ['headset', 'loopcut'],
    ['headset', 'scale', 1.2],
    ['desktop', 'bevel', 0.14],
    ['headset', 'inset', 0.6],
    ['desktop', 'rotate', Math.PI / 4],
    ['headset', 'extrude', 0.6],
  ];
  let step = 0;

  function renderLog(entries) {
    log.replaceChildren(
      ...entries.slice(-4).map((e) => {
        const li = document.createElement('li');
        li.className = `log__item log__item--${e.seat}`;
        li.innerHTML = `<span class="log__who">${SEATS[e.seat].name}</span><span class="log__op">${e.label}</span><span class="log__val">${e.detail}</span>`;
        return li;
      }),
    );
  }

  const entries = [];
  scene.on((ev) => {
    if (ev.type === 'start') {
      entries.push(ev.entry);
      renderLog(entries);
    } else if (ev.type === 'undo') {
      entries.pop();
      renderLog(entries);
    } else if (ev.type === 'redo') {
      entries.push(ev.entry);
      renderLog(entries);
    } else if (ev.type === 'change' && !ev.entry && ev.history === 0) {
      entries.length = 0;
      renderLog(entries);
    }
    sync();
  });

  function sync() {
    for (const b of toolButtons) b.disabled = !scene.can(b.dataset.op);
    undoBtn.disabled = scene.historyLength === 0;
    redoBtn.disabled = scene.futureLength === 0;
  }

  function takeOver() {
    if (userTouched) return;
    userTouched = true;
    clearTimeout(demoTimer);
  }

  seatButtons.forEach((b) =>
    b.addEventListener('click', () => {
      seat = b.dataset.seat;
      seatButtons.forEach((x) => x.setAttribute('aria-checked', String(x === b)));
    }),
  );
  seatButtons.forEach((b, i) =>
    b.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      const next = seatButtons[(i + 1) % seatButtons.length];
      next.focus();
      next.click();
    }),
  );

  toolButtons.forEach((b) =>
    b.addEventListener('click', () => {
      takeOver();
      if (scene.pending > 2) return;
      scene.apply(b.dataset.op, seat);
    }),
  );
  undoBtn.addEventListener('click', () => { takeOver(); scene.undo(); });
  redoBtn.addEventListener('click', () => { takeOver(); scene.redo(); });
  resetBtn.addEventListener('click', () => { takeOver(); scene.reset(); });
  canvas.addEventListener('pointerdown', takeOver);

  // Blender-style shortcuts while the canvas has focus.
  const keys = { e: 'extrude', i: 'inset', g: 'move', r: 'rotate', s: 'scale' };
  canvas.addEventListener('keydown', (e) => {
    const k = e.key.toLowerCase();
    let op = null;
    if (e.ctrlKey && k === 'b') op = 'bevel';
    else if (e.ctrlKey && k === 'r') op = 'loopcut';
    else if (e.ctrlKey && k === 'z') { e.preventDefault(); takeOver(); e.shiftKey ? scene.redo() : scene.undo(); return; }
    else if (!e.ctrlKey && !e.metaKey && !e.altKey) op = keys[k];
    if (!op) return;
    e.preventDefault();
    takeOver();
    if (scene.can(op) && scene.pending <= 2) scene.apply(op, seat);
  });

  // Self-running demo: build, pause, rewind through native history, repeat.
  function tick() {
    if (userTouched) return;
    if (scene.busy) { demoTimer = setTimeout(tick, 200); return; }
    if (step < script.length) {
      const [who, op, arg] = script[step++];
      scene.apply(op, who, arg);
      demoTimer = setTimeout(tick, 1500);
    } else {
      step = 0;
      demoTimer = setTimeout(() => {
        if (userTouched) return;
        const n = scene.historyLength;
        for (let i = 0; i < n; i++) scene.undo(true);
        demoTimer = setTimeout(tick, 1800);
      }, 3200);
    }
  }

  sync();
  if (reduced) {
    // Show a finished model without motion.
    for (const [who, op, arg] of script) scene.apply(op, who, arg);
    userTouched = true;
  } else {
    demoTimer = setTimeout(tick, 900);
  }
}

// Voice: apply a reviewed multi-step plan to a cube.
function voice() {
  const canvas = document.getElementById('voice-canvas');
  if (!canvas) return;
  const scene = createScene(canvas, { avatars: false, yaw: -0.5, pitch: 0.34, interactive: true });
  const steps = [...document.querySelectorAll('#plan-steps li')];
  const apply = document.getElementById('plan-apply');
  const reset = document.getElementById('plan-reset');
  let idx = -1;

  scene.on((ev) => {
    if (ev.type === 'start' && idx >= 0) {
      steps.forEach((s, i) => s.classList.toggle('is-running', i === idx));
    }
    if (ev.type === 'change' && ev.entry && idx >= 0) {
      steps[idx].classList.remove('is-running');
      steps[idx].classList.add('is-done');
      idx++;
      if (idx < steps.length) {
        setTimeout(runStep, reduced ? 0 : 350);
      } else {
        idx = -1;
        reset.hidden = false;
        reset.focus({ preventScroll: true });
      }
    }
  });

  function runStep() {
    const li = steps[idx];
    scene.apply(li.dataset.op, 'headset', li.dataset.arg ? Number(li.dataset.arg) : undefined);
  }

  apply.addEventListener('click', () => {
    if (idx >= 0) return;
    apply.hidden = true;
    idx = 0;
    runStep();
  });
  reset.addEventListener('click', () => {
    scene.reset();
    steps.forEach((s) => s.classList.remove('is-done', 'is-running'));
    reset.hidden = true;
    apply.hidden = false;
    apply.focus({ preventScroll: true });
  });
}

hero();
voice();
