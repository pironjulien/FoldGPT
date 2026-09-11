'use strict';
(() => {
  const stage = document.getElementById('fold-stage');
  const canvas = document.getElementById('fold-particles');
  const ctx = canvas.getContext('2d');
  const range = document.getElementById('fold-angle');
  const foldButton = document.getElementById('fold-toggle');
  const motionButton = document.getElementById('motion-toggle');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let open = 1, targetOpen = 1, width = 620, height = 520;
  let paused = reducedMotion.matches, visible = true, raf = 0, previousTime = 0;
  let pointer = null, energy = 0;
  const points = [];
  const clamp = (v, low, high) => Math.max(low, Math.min(high, v));
  // Particles retain anchors; input displaces them without losing the Fold.
  function segment(ax, ay, bx, by, count, group) {
    for (let i = 0; i <= count; i++) {
      const t = i / count;
      points.push({ax: ax + (bx - ax) * t, ay: ay + (by - ay) * t,
        x: 0, y: 0, vx: 0, vy: 0, group, phase: i * 1.618, ready: false});
    }
  }
  for (const side of [-1, 1]) {
    const inner = side * 7, outer = side * 199;
    segment(inner, -165, outer * .94, -165, 42, 'edge');
    segment(outer * .94, -165, outer, -150, 7, 'edge');
    segment(outer, -150, outer, 150, 72, 'edge');
    segment(outer, 150, outer * .94, 165, 7, 'edge');
    segment(outer * .94, 165, inner, 165, 42, 'edge');
    segment(inner, -165, inner, 165, 68, 'hinge');
    segment(outer + side * 5, -142, outer + side * 5, 146, 44, 'depth');
    for (let row = 0; row < 4; row++) segment(side * 26, 100 + row * 10, side * (100 + row * 18), 100 + row * 10, 12, 'trace');
  }
  function anchor(p) {
    const scale = Math.min(width / 620, height / 520);
    const x = p.ax * open;
    const y = p.ay + Math.abs(p.ax) * (1 - open) * .28;
    const angle = -Math.PI / 22.5;
    return {x: width / 2 + (x * Math.cos(angle) - y * Math.sin(angle)) * scale,
      y: height / 2 + (x * Math.sin(angle) + y * Math.cos(angle)) * scale};
  }
  function syncControls() {
    range.value = String(Math.round(targetOpen * 100));
    const folded = targetOpen < .59;
    foldButton.setAttribute('aria-pressed', String(folded));
    foldButton.textContent = folded ? 'Déplier ◫' : 'Replier ◧';
    motionButton.setAttribute('aria-pressed', String(paused));
    motionButton.textContent = paused ? 'Animer' : 'Pause';
    motionButton.setAttribute('aria-label', paused ? 'Animer les particules' : 'Mettre les particules en pause');
  }
  function render(now = 0, instant = false) {
    if (!ctx) return;
    const dt = Math.min((now - previousTime) / 16.667 || 1, 2);
    previousTime = now;
    open = instant ? targetOpen : open + (targetOpen - open) * (1 - Math.pow(.86, dt));
    stage.style.setProperty('--fold-open', open.toFixed(4));
    stage.style.setProperty('--fold-opacity', String(clamp((open - .18) / .65, 0, 1)));
    ctx.clearRect(0, 0, width, height);
    const scale = width / 620;
    energy *= Math.pow(.94, dt);
    points.forEach((p, i) => {
      const a = anchor(p);
      if (!p.ready || instant) {p.x = a.x; p.y = a.y; p.vx = 0; p.vy = 0; p.ready = true;}
      if (!instant) {
        p.vx += (a.x - p.x) * .025 * dt; p.vy += (a.y - p.y) * .025 * dt;
        if (pointer) {
          const dx = p.x - pointer.x, dy = p.y - pointer.y;
          const distance = Math.hypot(dx, dy), radius = 85 * scale;
          if (distance > .01 && distance < radius) {
            const force = (1 - distance / radius) * 1.3 * dt;
            p.vx += dx / distance * force; p.vy += dy / distance * force;
          }
        }
        if (energy > .01) {
          p.vx += Math.cos(p.phase) * energy * .025 * dt;
          p.vy += Math.sin(p.phase) * energy * .025 * dt;
        }
        p.vx *= Math.pow(.88, dt); p.vy *= Math.pow(.88, dt);
        p.x += p.vx * dt; p.y += p.vy * dt;
      }
      const shimmer = instant ? .8 : .68 + Math.sin(now * .0007 + p.phase) * .22;
      ctx.globalAlpha = p.group === 'trace' ? .15 : p.group === 'depth' ? .32 : shimmer;
      ctx.fillStyle = p.group === 'hinge' ? '#f2a65a' : i % 7 === 0 ? '#b39bef' : '#70d9df';
      ctx.beginPath(); ctx.arc(p.x, p.y, (p.group === 'hinge' ? 1.1 : 1.4) * scale, 0, Math.PI * 2); ctx.fill();
      // Neighbours only: linear work even on the inner display.
      const before = points[i - 1];
      if (before && before.group === p.group && Math.hypot(before.x - p.x, before.y - p.y) < 14 * scale) {
        ctx.globalAlpha *= .23; ctx.strokeStyle = ctx.fillStyle;
        ctx.lineWidth = .7; ctx.beginPath(); ctx.moveTo(before.x, before.y); ctx.lineTo(p.x, p.y); ctx.stroke();
      }
    });
    ctx.globalAlpha = 1;
  }
  function frame(now) {
    raf = 0;
    if (paused || !visible || document.hidden) return;
    render(now); raf = requestAnimationFrame(frame);
  }
  function start() {
    if (ctx && !raf && !paused && visible && !document.hidden) {previousTime = performance.now(); raf = requestAnimationFrame(frame);}
  }
  function stop() {if (raf) cancelAnimationFrame(raf); raf = 0;}
  function resize() {
    const bounds = stage.getBoundingClientRect();
    width = bounds.width; height = bounds.height;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    points.forEach(p => p.ready = false);
    render(performance.now(), true); start();
  }
  function setOpening(value) {
    targetOpen = clamp(value, .18, 1); syncControls();
    if (paused) render(performance.now(), true); else start();
  }
  range.addEventListener('input', () => setOpening(Number(range.value) / 100));
  foldButton.addEventListener('click', () => setOpening(targetOpen < .59 ? 1 : .18));
  motionButton.addEventListener('click', () => {paused = !paused; syncControls(); if (paused) stop(); else start();});
  canvas.addEventListener('pointermove', event => {
    const bounds = canvas.getBoundingClientRect();
    pointer = {x: event.clientX - bounds.left, y: event.clientY - bounds.top};
  });
  for (const event of ['pointerleave', 'pointerup', 'pointercancel']) canvas.addEventListener(event, () => {pointer = null;});
  canvas.addEventListener('pointerdown', event => {
    const bounds = canvas.getBoundingClientRect();
    pointer = {x: event.clientX - bounds.left, y: event.clientY - bounds.top}; energy = 16.18;
  });
  document.querySelectorAll('a, button, summary').forEach(el => el.addEventListener('pointerenter', () => {energy = 6.18;}));
  document.addEventListener('visibilitychange', () => {if (document.hidden) stop(); else start();});
  reducedMotion.addEventListener('change', () => {
    paused = reducedMotion.matches; syncControls();
    if (paused) {stop(); render(performance.now(), true);} else start();
  });
  if ('IntersectionObserver' in window) new IntersectionObserver(entries => {
    visible = entries[0].isIntersecting; if (visible) start(); else stop();
  }).observe(stage);
  if ('ResizeObserver' in window) new ResizeObserver(resize).observe(stage);
  else window.addEventListener('resize', resize);
  syncControls(); resize();
  if (!ctx) {
    motionButton.disabled = true; foldButton.disabled = true; range.disabled = true;
    motionButton.textContent = 'Statique';
  }
  const examples = {
    code: {path:'workspace / mon-projet', title:'Une idée devient du code.',
      prompt:'« Lis le projet, explique son architecture et prépare une amélioration ciblée. »',
      files:['src/', 'README.md', 'tests/'],
      detail:'Une conversation, les fichiers du projet et les outils de développement réunis sur le téléphone.'},
    docs: {path:'workspace / présentation', title:'Une idée prend forme.',
      prompt:'« À partir de ces notes, prépare une présentation et un tableau récapitulatif. »',
      files:['notes.md', 'présentation.pptx', 'synthèse.xlsx'],
      detail:'Les outils documentaires créent les fichiers dans le workspace. Leurs parcours pris en charge sont décrits dans la documentation.'},
    explore: {path:'workspace / recherche', title:'Un dossier devient plus clair.',
      prompt:'« Explore ces fichiers, relève les informations utiles et rédige une synthèse sourcée. »',
      files:['sources/', 'analyse.md', 'synthèse.pdf'],
      detail:'Les entrées et les documents produits restent des fichiers accessibles dans le projet.'}
  };
  document.querySelectorAll('[data-usecase]').forEach(button => button.addEventListener('click', () => {
    const example = examples[button.dataset.usecase];
    document.querySelectorAll('[data-usecase]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    for (const key of ['path', 'title', 'prompt', 'detail']) document.getElementById('example-' + key).textContent = example[key];
    document.getElementById('example-files').replaceChildren(...example.files.map(name => {
      const item = document.createElement('span'); item.textContent = name; return item;
    }));
    energy = 16.18;
  }));
})();
