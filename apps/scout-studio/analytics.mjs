// SCOUT Studio — Analytical charts (Coverage, Accuracy/RMSE, Altitude) & interactive Gantt timeline.

const MODE_SHORT = {
  rgb: 'RGB',
  lidar: 'LiDAR',
  'rgb+lidar': 'RGB+L',
  high: 'HIGH',
  low: 'LOW',
  ground: 'GND',
};

function setupCanvas(canvas) {
  const ratio = Math.min(window.devicePixelRatio || 1, 2.5);
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (!w || !h) return null;
  const pw = Math.round(w * ratio), ph = Math.round(h * ratio);
  if (canvas.width !== pw || canvas.height !== ph) {
    canvas.width = pw;
    canvas.height = ph;
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return {ctx, w, h};
}

function themeColors(dark) {
  return dark ? {
    bg: '#0f1620',
    grid: 'rgba(148,163,184,0.12)',
    axis: '#7c90a8',
    text: '#cbd5e1',
    muted: '#64748b',
    cursor: '#f8fafc',
    laneBg: 'rgba(255,255,255,0.025)',
  } : {
    bg: '#f7f9f7',
    grid: 'rgba(24,44,40,0.1)',
    axis: '#526861',
    text: '#1e2f2b',
    muted: '#697c74',
    cursor: '#0f172a',
    laneBg: 'rgba(24,44,40,0.035)',
  };
}

// Draw interactive Gantt timeline; returns layout metadata for click-to-seek.
export function drawGantt(canvas, replay, currentTime, {dark = true} = {}) {
  const setup = setupCanvas(canvas);
  if (!setup) return null;
  const {ctx, w, h} = setup;
  const c = themeColors(dark);
  ctx.clearRect(0, 0, w, h);

  const agents = replay.agents;
  const labelW = Math.min(168, Math.max(124, w * 0.22));
  const padR = 14, padT = 18, padB = 20;
  const plotW = Math.max(40, w - labelW - padR);
  const plotH = Math.max(24, h - padT - padB);
  const span = Math.max(1e-6, replay.endTick - replay.startTick);
  const xOf = tick => labelW + ((tick - replay.startTick) / span) * plotW;

  if (!agents.length || !replay.ganttTasks.length) {
    ctx.fillStyle = c.muted;
    ctx.font = '12px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('Brak zaplanowanych zadań robotów w tym zapisie (statyczna mapa).', w / 2, h / 2);
    return null;
  }

  // Vertical time gridlines
  const tickStep = niceStep(span, Math.max(4, Math.floor(plotW / 75)));
  const firstTick = Math.ceil(replay.startTick / tickStep) * tickStep;
  ctx.font = '10px "IBM Plex Mono", ui-monospace, monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let t = firstTick; t <= replay.endTick + 1e-6; t += tickStep) {
    const x = xOf(t);
    ctx.strokeStyle = c.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, padT);
    ctx.lineTo(x, h - padB);
    ctx.stroke();
    ctx.fillStyle = c.axis;
    ctx.fillText(`t=${formatTick(t)}`, x, h - padB + 4);
  }

  const rowH = plotH / agents.length;
  const barH = Math.min(22, Math.max(13, rowH - 8));

  agents.forEach((agent, idx) => {
    const y0 = padT + idx * rowH;
    const midY = y0 + rowH / 2;

    if (idx % 2 === 0) {
      ctx.fillStyle = c.laneBg;
      ctx.fillRect(labelW, y0, plotW, rowH);
    }

    // Agent color dot & label
    ctx.fillStyle = agent.style.hex;
    ctx.beginPath();
    ctx.arc(12, midY, 4.5, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = c.text;
    ctx.font = '600 11px Inter, system-ui, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    const label = agent.label.length > 20 ? agent.label.slice(0, 19) + '…' : agent.label;
    ctx.fillText(label, 22, midY);

    // Draw agent's tasks
    const tasks = replay.ganttTasks.filter(t => t.agent_id === agent.id);
    for (const task of tasks) {
      const xStart = xOf(task.start_tick);
      const xArr = xOf(Math.min(task.finish_tick, Math.max(task.start_tick, task.arrival_tick)));
      const xEnd = Math.max(xStart + 4, xOf(task.finish_tick));
      const by = midY - barH / 2;
      const col = agent.style.rgb;

      // Flight phase segment (translucent)
      if (xArr > xStart + 1) {
        ctx.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},0.24)`;
        roundRect(ctx, xStart, by, xArr - xStart, barH, 3);
        ctx.fill();
      }
      // Measurement phase segment (solid)
      const measX = Math.max(xStart, xArr);
      const measW = Math.max(2, xEnd - measX);
      ctx.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},${task.completed ? 0.84 : 0.45})`;
      roundRect(ctx, measX, by, measW, barH, 3);
      ctx.fill();

      // Outer border
      ctx.strokeStyle = `rgba(${col[0]},${col[1]},${col[2]},0.95)`;
      ctx.lineWidth = 1;
      roundRect(ctx, xStart, by, xEnd - xStart, barH, 3);
      ctx.stroke();

      // Task mode label if wide enough
      const totalW = xEnd - xStart;
      if (totalW >= 26) {
        ctx.fillStyle = dark ? '#081018' : '#0f1d1a';
        ctx.font = '700 9.5px "IBM Plex Mono", ui-monospace, monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const txt = MODE_SHORT[task.mode] || task.mode.toUpperCase();
        ctx.fillText(txt, xStart + totalW / 2, midY + 0.5);
      }
    }
  });

  // Top legend micro-key
  ctx.font = '10px Inter, system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = c.axis;
  ctx.fillText('Jasny: dolot  ·  Pełny: pomiar', w - padR, 9);

  // Live scrubbing playhead
  const cx = xOf(currentTime);
  ctx.strokeStyle = c.cursor;
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  ctx.moveTo(cx, padT - 4);
  ctx.lineTo(cx, h - padB);
  ctx.stroke();

  ctx.fillStyle = c.cursor;
  ctx.beginPath();
  ctx.moveTo(cx - 4.5, padT - 6);
  ctx.lineTo(cx + 4.5, padT - 6);
  ctx.lineTo(cx, padT);
  ctx.closePath();
  ctx.fill();

  return {labelW, plotW, startTick: replay.startTick, endTick: replay.endTick};
}

// Draw live mission metrics chart (coverage + accuracy/RMSE or altitude profiles).
export function drawMetricsChart(canvas, replay, layerId, currentTime, chartMode, {dark = true} = {}) {
  const setup = setupCanvas(canvas);
  if (!setup) return null;
  const {ctx, w, h} = setup;
  const c = themeColors(dark);
  ctx.clearRect(0, 0, w, h);

  const padL = 40, padR = 14, padT = 22, padB = 22;
  const plotW = Math.max(40, w - padL - padR);
  const plotH = Math.max(30, h - padT - padB);
  const span = Math.max(1e-6, replay.endTick - replay.startTick);
  const xOf = tick => padL + ((tick - replay.startTick) / span) * plotW;

  const seriesList = [];
  let yMin = 0, yMax = 100, yUnit = '%';

  if (chartMode === 'altitude') {
    const alts = replay.analytics.altitudeSeries;
    let maxAlt = 1;
    for (const [id, pts] of alts.entries()) {
      for (const p of pts) if (p.altitude_m > maxAlt) maxAlt = p.altitude_m;
      const agent = replay.agentMap.get(id);
      seriesList.push({
        label: agent.label,
        color: agent.style.hex,
        points: pts.map(p => ({t: p.tick, v: p.altitude_m})),
      });
    }
    yMin = 0;
    yMax = Math.ceil(maxAlt * 1.15);
    yUnit = 'm';
  } else {
    const info = replay.analytics.perLayer.get(layerId);
    if (info) {
      if (chartMode === 'quality' && info.hasRef) {
        if (info.layer.kind === 'categorical') {
          seriesList.push({
            label: 'Dokładność (obserw.)',
            color: '#34d399',
            points: info.series.filter(s => s.accuracyObserved != null).map(s => ({t: s.tick, v: s.accuracyObserved * 100})),
          });
          seriesList.push({
            label: 'Dokładność (cała mapa)',
            color: '#38bdf8',
            points: info.series.filter(s => s.accuracyTotal != null).map(s => ({t: s.tick, v: s.accuracyTotal * 100})),
          });
          // Also compare fused vs rgb/lidar if available
          if (layerId === 'fused' && replay.analytics.perLayer.has('rgb')) {
            const rgbS = replay.analytics.perLayer.get('rgb').series;
            seriesList.push({
              label: 'RGB (cała mapa)',
              color: '#fbbf24',
              dashed: true,
              points: rgbS.filter(s => s.accuracyTotal != null).map(s => ({t: s.tick, v: s.accuracyTotal * 100})),
            });
          }
        } else {
          seriesList.push({
            label: 'W tolerancji ≤25 cm',
            color: '#34d399',
            points: info.series.filter(s => s.within25cm != null).map(s => ({t: s.tick, v: s.within25cm * 100})),
          });
          seriesList.push({
            label: 'Pokrycie mapy',
            color: '#38bdf8',
            dashed: true,
            points: info.series.map(s => ({t: s.tick, v: s.coverage * 100})),
          });
        }
      } else {
        // Coverage mode (plus comparison of RGB/LiDAR/Fused if semantic)
        if (replay.analytics.perLayer.has('fused') && replay.analytics.perLayer.has('rgb') && replay.analytics.perLayer.has('lidar')) {
          seriesList.push({
            label: 'Fuzja',
            color: '#38bdf8',
            points: replay.analytics.perLayer.get('fused').series.map(s => ({t: s.tick, v: s.coverage * 100})),
          });
          seriesList.push({
            label: 'RGB',
            color: '#fbbf24',
            points: replay.analytics.perLayer.get('rgb').series.map(s => ({t: s.tick, v: s.coverage * 100})),
          });
          seriesList.push({
            label: 'LiDAR',
            color: '#e879f9',
            points: replay.analytics.perLayer.get('lidar').series.map(s => ({t: s.tick, v: s.coverage * 100})),
          });
        } else {
          seriesList.push({
            label: `Pokrycie (${info.layer.label})`,
            color: '#38bdf8',
            points: info.series.map(s => ({t: s.tick, v: s.coverage * 100})),
          });
          if (replay.confidenceLayerId) {
            const cs = replay.analytics.perLayer.get(replay.confidenceLayerId).series;
            seriesList.push({
              label: 'Średnia pewność',
              color: '#34d399',
              dashed: true,
              points: cs.filter(s => s.meanScalar != null).map(s => ({t: s.tick, v: s.meanScalar * 100})),
            });
          }
        }
      }
    }
  }

  if (!seriesList.length || seriesList.every(s => s.points.length < 2)) {
    ctx.fillStyle = c.muted;
    ctx.font = '12px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const msg = chartMode === 'altitude'
      ? 'Ten zapis nie zawiera zarejestrowanego profilu wysokości (altitude_m).'
      : 'Za mało kroków czasowych do narysowania wykresu.';
    ctx.fillText(msg, w / 2, h / 2);
    return null;
  }

  const yOf = v => padT + plotH - ((v - yMin) / Math.max(1e-6, yMax - yMin)) * plotH;

  // Horizontal gridlines
  ctx.font = '10px "IBM Plex Mono", ui-monospace, monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  const ySteps = 4;
  for (let i = 0; i <= ySteps; i++) {
    const val = yMin + ((yMax - yMin) * i) / ySteps;
    const y = yOf(val);
    ctx.strokeStyle = c.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    ctx.fillStyle = c.axis;
    ctx.fillText(`${Math.round(val)}${yUnit}`, padL - 6, y);
  }

  // X ticks
  const tickStep = niceStep(span, Math.max(3, Math.floor(plotW / 80)));
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let t = Math.ceil(replay.startTick / tickStep) * tickStep; t <= replay.endTick + 1e-6; t += tickStep) {
    const x = xOf(t);
    ctx.fillStyle = c.axis;
    ctx.fillText(`t=${formatTick(t)}`, x, h - padB + 5);
  }

  // Plot series (step-hold for mission snapshots, linear for altitude)
  const stepHold = chartMode !== 'altitude';
  for (const s of seriesList) {
    if (!s.points.length) continue;
    ctx.save();
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2;
    if (s.dashed) ctx.setLineDash([4, 3]);
    ctx.beginPath();
    s.points.forEach((pt, idx) => {
      const x = xOf(pt.t), y = yOf(pt.v);
      if (idx === 0) ctx.moveTo(x, y);
      else {
        if (stepHold) ctx.lineTo(x, yOf(s.points[idx - 1].v));
        ctx.lineTo(x, y);
      }
    });
    // Extend to endTick if step-hold
    if (stepHold && s.points.at(-1).t < replay.endTick) {
      ctx.lineTo(xOf(replay.endTick), yOf(s.points.at(-1).v));
    }
    ctx.stroke();

    // Soft area fill for primary series
    if (s === seriesList[0] && !s.dashed) {
      ctx.setLineDash([]);
      ctx.lineTo(xOf(stepHold ? replay.endTick : s.points.at(-1).t), padT + plotH);
      ctx.lineTo(xOf(s.points[0].t), padT + plotH);
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
      grad.addColorStop(0, hexAlpha(s.color, 0.22));
      grad.addColorStop(1, hexAlpha(s.color, 0.01));
      ctx.fillStyle = grad;
      ctx.fill();
    }
    ctx.restore();
  }

  // Inline legend at top
  let lx = padL;
  ctx.font = '10.5px Inter, system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  for (const s of seriesList) {
    ctx.fillStyle = s.color;
    ctx.fillRect(lx, 7, 10, 3);
    lx += 14;
    ctx.fillStyle = c.text;
    ctx.fillText(s.label, lx, 9);
    lx += ctx.measureText(s.label).width + 14;
  }

  // Playhead
  const cx = xOf(currentTime);
  ctx.strokeStyle = c.cursor;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(cx, padT);
  ctx.lineTo(cx, padT + plotH);
  ctx.stroke();

  return {labelW: padL, plotW, startTick: replay.startTick, endTick: replay.endTick};
}

function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

function niceStep(span, targetTicks) {
  const raw = span / Math.max(1, targetTicks);
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / pow;
  const nice = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return nice * pow;
}

function formatTick(t) {
  return Number.isInteger(t) ? String(t) : t.toFixed(1);
}

function hexAlpha(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}
