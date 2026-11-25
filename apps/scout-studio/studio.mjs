// SCOUT Mission Studio — Main Controller
import {drawGantt, drawMetricsChart} from './analytics.mjs';
import {Renderer2D} from './render2d.mjs';
import {Renderer3D} from './render3d.mjs';
import {
  cellColorRgb, ERROR_STOPS, readReplay, rgbCss, sampleState, stopsForLayer,
} from './replay.mjs';

const $ = id => document.getElementById(id);
const numFmt = new Intl.NumberFormat('pl', {maximumFractionDigits: 2});
const MODE_LABELS = {
  rgb: 'RGB',
  lidar: 'LiDAR',
  'rgb+lidar': 'RGB + LiDAR',
  high: 'Pułap wysoki',
  low: 'Pułap niski',
  ground: 'Pomiar naziemny',
};

const el = {
  missionSelect: $('mission-select'),
  btnOpen: $('btn-open'),
  fileInput: $('file-input'),
  mode2d: $('mode-2d'),
  mode3d: $('mode-3d'),
  btnTheme: $('btn-theme'),
  notice: $('notice'),
  viewport: $('viewport-wrap'),
  canvas2d: $('canvas-2d'),
  canvas3d: $('canvas-3d'),
  canvasHud: $('canvas-hud'),
  layerSelect: $('layer-select'),
  compareSeg: $('compare-seg'),
  optUncertainty: $('opt-uncertainty'),
  uncWrap: $('unc-wrap'),
  splitCtrl: $('split-ctrl'),
  splitRange: $('split-range'),
  controls3d: $('controls-3d'),
  controls2d: $('controls-2d'),
  reliefRange: $('relief-range'),
  zoomIn: $('zoom-in'),
  zoomOut: $('zoom-out'),
  zoomFit: $('zoom-fit'),
  cellInspector: $('cell-inspector'),
  legendBar: $('legend-bar'),
  optTrails: $('opt-trails'),
  optPlans: $('opt-plans'),
  optFootprints: $('opt-footprints'),
  optGrid: $('opt-grid'),
  optSmooth: $('opt-smooth'),
  btnFirst: $('btn-first'),
  btnPrev: $('btn-prev'),
  btnPlay: $('btn-play'),
  btnNext: $('btn-next'),
  btnLast: $('btn-last'),
  scrubber: $('time-scrubber'),
  timeReadout: $('time-readout'),
  speedSelect: $('speed-select'),
  btnToggleDock: $('btn-toggle-dock'),
  analyticsBody: $('analytics-body'),
  analyticsCanvas: $('analytics-canvas'),
  missionTitle: $('mission-title'),
  missionMeta: $('mission-meta'),
  kpiCoverage: $('kpi-coverage'),
  kpiCoverageSub: $('kpi-coverage-sub'),
  kpiQualityLabel: $('kpi-quality-label'),
  kpiQuality: $('kpi-quality'),
  kpiQualitySub: $('kpi-quality-sub'),
  kpiCaptures: $('kpi-captures'),
  kpiCapturesSub: $('kpi-captures-sub'),
  kpiTime: $('kpi-time'),
  kpiTimeSub: $('kpi-time-sub'),
  fleetCount: $('fleet-count'),
  fleetList: $('fleet-list'),
  eventsCount: $('events-count'),
  eventsList: $('events-list'),
  commStatus: $('comm-status'),
  commPayload: $('comm-payload'),
  dropOverlay: $('drop-overlay'),
};

const r2d = new Renderer2D(el.canvas2d);
const r3d = new Renderer3D(el.canvas3d, el.canvasHud);

const bundleTag = $('scout-studio-bundle');
const bundledMissions = bundleTag ? JSON.parse(bundleTag.textContent) : null;

const appState = {
  replay: null,
  viewMode: r3d.supported ? '3d' : '2d',
  darkTheme: true,
  layerId: '',
  compareMode: 'estimate',
  splitRatio: 0.5,
  verticalExag: 1.0,
  showUncertainty: false,
  showTrails: true,
  showPlans: true,
  showFootprints: true,
  showGrid: true,
  smoothMotion: true,
  time: 0,
  playing: false,
  speed: 1,
  analyticsTab: 'gantt',
  hoverCell: null,
  chartLayout: null,
  lastUiStamp: -1,
  loadVersion: 0,
};

function showNotice(msg) {
  el.notice.textContent = msg || '';
  el.notice.hidden = !msg;
}

function setViewMode(mode) {
  if (mode === '3d' && !r3d.supported) {
    showNotice('WebGL2 jest niedostępny w tej przeglądarce — używam widoku 2D.');
    mode = '2d';
  }
  appState.viewMode = mode;
  el.mode2d.classList.toggle('active', mode === '2d');
  el.mode3d.classList.toggle('active', mode === '3d');
  el.canvas2d.hidden = mode !== '2d';
  el.canvas3d.hidden = mode !== '3d';
  el.canvasHud.hidden = mode !== '3d';
  el.controls2d.hidden = mode !== '2d';
  el.controls3d.hidden = mode !== '3d';
}

function setCompareMode(cmp) {
  const hasRef = Boolean(appState.replay?.data.reference_layers?.[appState.layerId]);
  if (!hasRef && cmp !== 'estimate') cmp = 'estimate';
  appState.compareMode = cmp;
  for (const btn of el.compareSeg.querySelectorAll('.seg-btn')) {
    const c = btn.dataset.cmp;
    btn.disabled = c !== 'estimate' && !hasRef;
    btn.classList.toggle('active', c === cmp);
  }
  el.splitCtrl.hidden = cmp !== 'split';
  renderLegend();
}

function renderLegend() {
  const replay = appState.replay;
  if (!replay) return;
  el.legendBar.replaceChildren();
  const id = appState.layerId;
  const style = (appState.compareMode === 'reference' ? replay.referenceStyles : replay.styles).get(id);
  if (!style) return;

  const addSwatch = (color, label) => {
    const item = document.createElement('span');
    item.className = 'legend-item';
    const sw = document.createElement('i');
    sw.className = 'swatch';
    sw.style.background = color;
    item.append(sw, document.createTextNode(label));
    el.legendBar.append(item);
  };

  if (appState.compareMode === 'error') {
    if (style.layer.kind === 'categorical') {
      addSwatch('rgb(46,178,128)', 'Zgodne z referencją');
      addSwatch('rgb(228,82,82)', 'Błąd klasyfikacji');
      addSwatch(appState.darkTheme ? 'rgb(36,44,56)' : 'rgb(188,198,196)', 'Nieobserwowane');
    } else {
      const span = Math.max(0.5, (style.domain[1] - style.domain[0]) * 0.28);
      const grad = document.createElement('span');
      grad.className = 'grad-bar';
      grad.style.background = `linear-gradient(90deg, ${ERROR_STOPS.map(c => rgbCss(c)).join(',')})`;
      el.legendBar.append(
        document.createTextNode('0 ' + (style.layer.unit || '')),
        grad,
        document.createTextNode(`≥${numFmt.format(span)} ${style.layer.unit || ''}`),
      );
    }
    return;
  }

  if (style.layer.kind === 'scalar') {
    const [lo, hi] = style.domain;
    const stops = stopsForLayer(style.layer);
    const grad = document.createElement('span');
    grad.className = 'grad-bar';
    grad.style.background = `linear-gradient(90deg, ${stops.map(c => rgbCss(c)).join(',')})`;
    el.legendBar.append(
      document.createTextNode(numFmt.format(lo)),
      grad,
      document.createTextNode(`${numFmt.format(hi)}${style.layer.unit ? ' ' + style.layer.unit : ''}`),
    );
  } else {
    for (const [key, label] of style.labels.entries()) {
      addSwatch(rgbCss(cellColorRgb(style, key, appState.darkTheme)), label);
    }
  }
  addSwatch(rgbCss(cellColorRgb(style, null, appState.darkTheme)), 'Brak danych');
}

function loadReplayData(raw) {
  const parsed = readReplay(raw);
  appState.replay = parsed;
  appState.playing = false;
  appState.time = parsed.startTick;
  appState.hoverCell = null;
  appState.lastUiStamp = -1;

  // Pick best default layer (prefer fused -> terrain -> elevation_m -> first)
  const pref = ['fused', 'terrain', 'elevation_m', 'surface'];
  const picked = pref.find(id => parsed.styles.has(id)) || parsed.data.layers[0].id;
  appState.layerId = picked;

  el.layerSelect.replaceChildren(...parsed.data.layers.map(l => new Option(l.label, l.id)));
  el.layerSelect.value = picked;
  el.uncWrap.hidden = !parsed.confidenceLayerId;
  if (!parsed.confidenceLayerId) {
    appState.showUncertainty = false;
    el.optUncertainty.checked = false;
  }

  el.missionTitle.textContent = parsed.data.title;
  const g = parsed.data.grid;
  const areaW = numFmt.format(g.width * g.cell_size_m);
  const areaH = numFmt.format(g.height * g.cell_size_m);
  el.missionMeta.textContent = `${g.width}×${g.height} (${areaW}×${areaH} m · ${numFmt.format(g.cell_size_m)} m/pole) · ${parsed.data.frames.length} klatek`;

  el.scrubber.min = parsed.startTick;
  el.scrubber.max = Math.max(parsed.startTick, parsed.endTick);
  el.scrubber.step = parsed.endTick > parsed.startTick ? 0.02 : 1;
  el.scrubber.value = parsed.startTick;
  el.scrubber.disabled = parsed.endTick <= parsed.startTick;

  const isStatic = parsed.endTick <= parsed.startTick;
  el.btnPlay.disabled = isStatic;
  el.btnFirst.disabled = el.btnPrev.disabled = el.btnNext.disabled = el.btnLast.disabled = isStatic;

  // Auto-switch default analytics tab if no tasks exist
  if (!parsed.ganttTasks.length && appState.analyticsTab === 'gantt') {
    setAnalyticsTab('coverage');
  }

  r2d.resetView();
  r3d.fitToReplay(parsed);
  setCompareMode('estimate');
  showNotice('');
  updateTelemetryUI(sampleState(parsed, appState.time, {smoothMotion: appState.smoothMotion}));
}

function setAnalyticsTab(tab) {
  appState.analyticsTab = tab;
  for (const btn of document.querySelectorAll('.tab-btn')) {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  }
}

function updateHoverInspector(state) {
  const cell = appState.hoverCell;
  const replay = appState.replay;
  if (!cell || !replay) {
    el.cellInspector.hidden = true;
    return;
  }
  const {width, cell_size_m} = replay.data.grid;
  const idx = cell.y * width + cell.x;
  const style = replay.styles.get(appState.layerId);
  const est = state.frame.layers[appState.layerId]?.[idx];
  const ref = replay.data.reference_layers?.[appState.layerId]?.[idx];
  const conf = replay.confidenceLayerId ? state.frame.layers[replay.confidenceLayerId]?.[idx] : undefined;

  const fmtVal = v => {
    if (v == null) return 'brak';
    if (style.layer.kind === 'categorical') return style.labels.get(v) ?? String(v);
    return numFmt.format(v) + (style.layer.unit ? ' ' + style.layer.unit : '');
  };

  const xm = numFmt.format((cell.x + 0.5) * cell_size_m);
  const ym = numFmt.format((cell.y + 0.5) * cell_size_m);
  const parts = [`[${cell.x}, ${cell.y}] (${xm}m, ${ym}m)`, `Est: ${fmtVal(est)}`];
  if (ref !== undefined) {
    parts.push(`Ref: ${fmtVal(ref)}`);
    if (est != null && ref != null) {
      if (style.layer.kind === 'categorical') {
        parts.push(est === ref ? '✓ zgodne' : '✕ błąd');
      } else {
        parts.push(`Δ ${numFmt.format(Math.abs(est - ref))} ${style.layer.unit || ''}`);
      }
    }
  }
  if (conf != null) parts.push(`Pewność: ${Math.round(conf * 100)}%`);
  el.cellInspector.textContent = parts.join('  ·  ');
  el.cellInspector.hidden = false;
}

function updateTelemetryUI(state) {
  const replay = appState.replay;
  if (!replay) return;

  // Time & transport buttons
  const unit = replay.secondsPerTick === 1 && replay.data.seconds_per_tick ? ' s' : '';
  el.scrubber.value = state.time;
  el.timeReadout.textContent = `t = ${state.time.toFixed(1)} / ${replay.endTick}${unit}`;
  el.btnPlay.textContent = appState.playing ? '❚❚ Pauza' : '▶ Odtwórz';

  // KPIs
  const layerStats = replay.analytics.perLayer.get(appState.layerId);
  const pt = layerStats?.series[state.frameIndex];
  if (pt) {
    el.kpiCoverage.textContent = `${(pt.coverage * 100).toFixed(1)}%`;
    el.kpiCoverageSub.textContent = `${pt.observed} / ${replay.analytics.totalCells} pól`;
    if (layerStats.hasRef) {
      if (layerStats.layer.kind === 'categorical') {
        el.kpiQualityLabel.textContent = 'Dokładność';
        el.kpiQuality.textContent = pt.accuracyObserved != null ? `${(pt.accuracyObserved * 100).toFixed(1)}%` : '—';
        el.kpiQualitySub.textContent = pt.accuracyTotal != null
          ? `cała mapa: ${(pt.accuracyTotal * 100).toFixed(1)}%`
          : 'vs referencja offline';
      } else {
        el.kpiQualityLabel.textContent = 'Błąd RMSE';
        el.kpiQuality.textContent = pt.rmse != null ? `${pt.rmse.toFixed(3)} ${layerStats.layer.unit || ''}` : '—';
        el.kpiQualitySub.textContent = pt.within25cm != null
          ? `≤25 cm: ${(pt.within25cm * 100).toFixed(1)}% mapy`
          : 'vs referencja offline';
      }
    } else {
      el.kpiQualityLabel.textContent = 'Śr. wartość';
      el.kpiQuality.textContent = pt.meanScalar != null ? `${numFmt.format(pt.meanScalar)} ${layerStats.layer.unit || ''}` : '—';
      el.kpiQualitySub.textContent = 'brak warstwy referencyjnej';
    }
  }

  const completedSoFar = replay.ganttTasks.filter(t => t.completed && t.completed_tick <= state.time + 1e-6).length;
  el.kpiCaptures.textContent = `${completedSoFar} / ${replay.analytics.totalCompleted}`;
  el.kpiCapturesSub.textContent = `aktywne teraz: ${state.frame.scheduled.length}`;

  el.kpiTime.textContent = `${state.time.toFixed(1)}${unit}`;
  el.kpiTimeSub.textContent = `klatka ${state.frameIndex + 1} / ${replay.data.frames.length}`;

  // Fleet cards
  el.fleetCount.textContent = state.agentStates.length;
  if (!state.agentStates.length) {
    el.fleetList.innerHTML = '<p class="muted">Brak robotów w tym zapisie (statyczny podgląd terenu).</p>';
  } else {
    const cellM = replay.data.grid.cell_size_m;
    el.fleetList.replaceChildren(...state.agentStates.map(as => {
      const card = document.createElement('div');
      card.className = 'agent-card';
      card.style.setProperty('--agent-col', as.agent.style.hex);

      const head = document.createElement('div');
      head.className = 'agent-head';
      const num = document.createElement('span');
      num.className = 'agent-num mono';
      num.textContent = String(as.agent.index + 1);
      const name = document.createElement('span');
      name.className = 'agent-name';
      name.textContent = as.agent.label;
      const pill = document.createElement('span');
      pill.className = `stage-pill stage-${as.stage}`;
      pill.textContent = as.stage === 'measure' ? 'Pomiar' : as.stage === 'flight' ? 'Dolot' : 'Postój';
      head.append(num, name, pill);
      card.append(head);

      const addKv = (k, v) => {
        const row = document.createElement('div');
        row.className = 'agent-kv';
        const s1 = document.createElement('span'); s1.textContent = k;
        const s2 = document.createElement('span'); s2.className = 'mono'; s2.textContent = v;
        row.append(s1, s2);
        card.append(row);
      };

      const xm = (as.xy[0] * cellM).toFixed(1), ym = (as.xy[1] * cellM).toFixed(1);
      addKv('Pozycja (m)', `(${xm}; ${ym}) m`);
      if (as.agent.kind === 'drone') {
        const tag = as.altitudeIsReal ? '' : ' (szac.)';
        addKv('Wysokość', `${as.altitude.toFixed(2)} m${tag}`);
      }
      if (as.activeTask) {
        addKv('Zadanie', `${MODE_LABELS[as.activeTask.mode] || as.activeTask.mode} → t=${as.activeTask.finish_tick}`);
        const track = document.createElement('div');
        track.className = 'progress-track';
        const fill = document.createElement('div');
        fill.className = 'progress-fill';
        fill.style.width = `${Math.round(as.taskProgress * 100)}%`;
        track.append(fill);
        card.append(track);
      } else {
        addKv('Zadanie', 'brak aktywnego celu');
      }
      return card;
    }));
  }

  // Recent / active capture events
  const activeEvents = [
    ...state.recentCompleted.map(({task, age}) => ({kind: 'done', task, age})),
    ...state.frame.scheduled.map(task => ({kind: 'active', task, age: 0})),
  ];
  el.eventsCount.textContent = state.recentCompleted.length;
  if (!activeEvents.length) {
    el.eventsList.innerHTML = '<p class="muted">Brak aktywnych ani właśnie zakończonych pomiarów.</p>';
  } else {
    el.eventsList.replaceChildren(...activeEvents.slice(0, 8).map(item => {
      const ag = replay.agentMap.get(item.task.agent_id);
      const row = document.createElement('div');
      row.className = 'event-item';
      const dot = document.createElement('span');
      dot.className = 'agent-num mono';
      dot.style.background = ag.style.hex;
      dot.textContent = String(ag.index + 1);
      const body = document.createElement('div');
      const status = item.kind === 'done' ? '✓ Zakończono' : '◎ W toku';
      body.textContent = `${status} · ${MODE_LABELS[item.task.mode] || item.task.mode}`;
      const sub = document.createElement('small');
      sub.className = 'mono';
      const altTxt = item.task.standoff_m ? ` · ${numFmt.format(item.task.standoff_m)} m` : '';
      sub.textContent = `${ag.label} · (${numFmt.format(item.task.xy[0])}; ${numFmt.format(item.task.xy[1])})${altTxt}`;
      body.append(sub);
      row.append(dot, body);
      return row;
    }));
  }

  // Comm & metadata
  if (state.messagesNow === undefined) {
    const model = replay.agents.find(a => a.flight_model)?.flight_model;
    el.commStatus.textContent = 'Transport radiowy niemodelowany w tym zapisie.'
      + (model ? ` Model lotu: ${model}.` : '');
    el.commPayload.hidden = true;
  } else {
    el.commStatus.textContent = `Wiadomości w tej chwili: ${state.messagesNow.length}`;
    el.commPayload.hidden = !state.messagesNow.length;
    el.commPayload.textContent = state.messagesNow.length ? JSON.stringify(state.messagesNow, null, 2) : '';
  }
}

// ---- Main 60fps Animation Loop ----
let lastFrameTs = performance.now();
function tickLoop(now) {
  const dt = Math.min(0.1, (now - lastFrameTs) / 1000);
  lastFrameTs = now;
  const animTime = now / 1000;

  if (appState.replay) {
    if (appState.playing) {
      const rate = appState.speed * 1.6; // ticks per second at 1x
      appState.time += dt * rate;
      if (appState.time >= appState.replay.endTick) {
        appState.time = appState.replay.endTick;
        appState.playing = false;
      }
    }

    const state = sampleState(appState.replay, appState.time, {smoothMotion: appState.smoothMotion});
    const renderOpts = {
      layerId: appState.layerId,
      compareMode: appState.compareMode,
      splitRatio: appState.splitRatio,
      showUncertainty: appState.showUncertainty,
      showTrails: appState.showTrails,
      showPlans: appState.showPlans,
      showFootprints: appState.showFootprints,
      showGrid: appState.showGrid,
      verticalExag: appState.verticalExag,
      darkTheme: appState.darkTheme,
      animTime,
    };

    if (appState.viewMode === '2d') {
      r2d.hoverCell = appState.hoverCell;
      r2d.render(appState.replay, state, renderOpts);
    } else {
      r3d.hoverCell = appState.hoverCell;
      r3d.render(appState.replay, state, renderOpts);
    }

    if (!el.analyticsBody.classList.contains('collapsed')) {
      if (appState.analyticsTab === 'gantt') {
        appState.chartLayout = drawGantt(el.analyticsCanvas, appState.replay, appState.time, {dark: appState.darkTheme});
      } else {
        appState.chartLayout = drawMetricsChart(
          el.analyticsCanvas, appState.replay, appState.layerId, appState.time, appState.analyticsTab,
          {dark: appState.darkTheme},
        );
      }
    }

    // Throttle DOM telemetry updates to ~15Hz while playing, instant when paused/changed
    if (!appState.playing || now - appState.lastUiStamp > 65) {
      appState.lastUiStamp = now;
      updateTelemetryUI(state);
      updateHoverInspector(state);
    }
  }
  requestAnimationFrame(tickLoop);
}

// ---- Pointer Interactions (2D Pan/Zoom/Curtain & 3D Orbit/Pan/Zoom) ----
let dragMode = null; // 'pan2d' | 'curtain2d' | 'orbit3d' | 'pan3d'
let lastPointer = null;

function pointerPos(canvas, ev) {
  const rect = canvas.getBoundingClientRect();
  return [ev.clientX - rect.left, ev.clientY - rect.top];
}

el.canvas2d.addEventListener('pointerdown', ev => {
  const [x, y] = pointerPos(el.canvas2d, ev);
  lastPointer = [x, y];
  const L = r2d._lastLayout;
  const hasRef = Boolean(appState.replay?.data.reference_layers?.[appState.layerId]);
  if (appState.compareMode === 'split' && hasRef && L) {
    const splitX = L.left + L.mapW * appState.splitRatio;
    if (Math.abs(x - splitX) < 18) {
      dragMode = 'curtain2d';
      el.canvas2d.setPointerCapture(ev.pointerId);
      return;
    }
  }
  dragMode = 'pan2d';
  el.canvas2d.setPointerCapture(ev.pointerId);
});

el.canvas2d.addEventListener('pointermove', ev => {
  const [x, y] = pointerPos(el.canvas2d, ev);
  if (dragMode === 'curtain2d' && r2d._lastLayout) {
    const L = r2d._lastLayout;
    appState.splitRatio = Math.max(0.03, Math.min(0.97, (x - L.left) / L.mapW));
    el.splitRange.value = appState.splitRatio;
    return;
  }
  if (dragMode === 'pan2d' && lastPointer) {
    r2d.panBy(x - lastPointer[0], y - lastPointer[1]);
    lastPointer = [x, y];
    return;
  }
  appState.hoverCell = r2d.screenToCell(x, y);
  // Show resize cursor near curtain handle
  const L = r2d._lastLayout;
  if (appState.compareMode === 'split' && L && Math.abs(x - (L.left + L.mapW * appState.splitRatio)) < 16) {
    el.canvas2d.style.cursor = 'ew-resize';
  } else {
    el.canvas2d.style.cursor = 'grab';
  }
});

el.canvas2d.addEventListener('pointerup', () => { dragMode = null; lastPointer = null; });
el.canvas2d.addEventListener('pointerleave', () => { if (!dragMode) appState.hoverCell = null; });
el.canvas2d.addEventListener('wheel', ev => {
  ev.preventDefault();
  const [x, y] = pointerPos(el.canvas2d, ev);
  r2d.zoomBy(ev.deltaY < 0 ? 1.15 : 1 / 1.15, x, y);
}, {passive: false});
el.canvas2d.addEventListener('dblclick', () => r2d.resetView());

// 3D pointer controls
el.canvas3d.addEventListener('contextmenu', ev => ev.preventDefault());
el.canvas3d.addEventListener('pointerdown', ev => {
  const [x, y] = pointerPos(el.canvas3d, ev);
  lastPointer = [x, y];
  dragMode = (ev.button === 2 || ev.shiftKey) ? 'pan3d' : 'orbit3d';
  el.canvas3d.setPointerCapture(ev.pointerId);
});
el.canvas3d.addEventListener('pointermove', ev => {
  const [x, y] = pointerPos(el.canvas3d, ev);
  if (dragMode === 'orbit3d' && lastPointer) {
    r3d.orbitBy(x - lastPointer[0], y - lastPointer[1]);
    lastPointer = [x, y];
    return;
  }
  if (dragMode === 'pan3d' && lastPointer) {
    r3d.panBy(x - lastPointer[0], y - lastPointer[1]);
    lastPointer = [x, y];
    return;
  }
  appState.hoverCell = r3d.screenToCell(x, y);
});
el.canvas3d.addEventListener('pointerup', () => { dragMode = null; lastPointer = null; });
el.canvas3d.addEventListener('pointerleave', () => { if (!dragMode) appState.hoverCell = null; });
el.canvas3d.addEventListener('wheel', ev => {
  ev.preventDefault();
  r3d.zoomBy(ev.deltaY < 0 ? 0.9 : 1.11);
}, {passive: false});
el.canvas3d.addEventListener('dblclick', () => appState.replay && r3d.fitToReplay(appState.replay));

// Click/drag on Analytics/Gantt canvas to scrub time
let scrubbingChart = false;
function scrubFromChart(ev) {
  const L = appState.chartLayout;
  if (!L || !appState.replay) return;
  const rect = el.analyticsCanvas.getBoundingClientRect();
  const x = ev.clientX - rect.left;
  const ratio = Math.max(0, Math.min(1, (x - L.labelW) / L.plotW));
  appState.playing = false;
  appState.time = L.startTick + ratio * (L.endTick - L.startTick);
}
el.analyticsCanvas.addEventListener('pointerdown', ev => {
  scrubbingChart = true;
  el.analyticsCanvas.setPointerCapture(ev.pointerId);
  scrubFromChart(ev);
});
el.analyticsCanvas.addEventListener('pointermove', ev => { if (scrubbingChart) scrubFromChart(ev); });
el.analyticsCanvas.addEventListener('pointerup', () => { scrubbingChart = false; });

// ---- Controls Wiring ----
el.mode2d.addEventListener('click', () => setViewMode('2d'));
el.mode3d.addEventListener('click', () => setViewMode('3d'));
el.btnTheme.addEventListener('click', () => {
  appState.darkTheme = !appState.darkTheme;
  document.documentElement.dataset.theme = appState.darkTheme ? 'dark' : 'light';
  renderLegend();
});

el.layerSelect.addEventListener('change', () => {
  appState.layerId = el.layerSelect.value;
  setCompareMode(appState.compareMode);
  appState.lastUiStamp = -1;
});

for (const btn of el.compareSeg.querySelectorAll('.seg-btn')) {
  btn.addEventListener('click', () => setCompareMode(btn.dataset.cmp));
}
el.splitRange.addEventListener('input', () => { appState.splitRatio = Number(el.splitRange.value); });
el.reliefRange.addEventListener('input', () => { appState.verticalExag = Number(el.reliefRange.value); });
for (const btn of el.controls3d.querySelectorAll('[data-cam]')) {
  btn.addEventListener('click', () => r3d.setPreset(btn.dataset.cam, appState.replay));
}
el.zoomIn.addEventListener('click', () => r2d.zoomBy(1.25));
el.zoomOut.addEventListener('click', () => r2d.zoomBy(0.8));
el.zoomFit.addEventListener('click', () => r2d.resetView());

el.optUncertainty.addEventListener('change', () => { appState.showUncertainty = el.optUncertainty.checked; });
el.optTrails.addEventListener('change', () => { appState.showTrails = el.optTrails.checked; });
el.optPlans.addEventListener('change', () => { appState.showPlans = el.optPlans.checked; });
el.optFootprints.addEventListener('change', () => { appState.showFootprints = el.optFootprints.checked; });
el.optGrid.addEventListener('change', () => { appState.showGrid = el.optGrid.checked; });
el.optSmooth.addEventListener('change', () => { appState.smoothMotion = el.optSmooth.checked; });

el.btnFirst.addEventListener('click', () => { appState.playing = false; appState.time = appState.replay.startTick; });
el.btnLast.addEventListener('click', () => { appState.playing = false; appState.time = appState.replay.endTick; });
el.btnPrev.addEventListener('click', () => {
  appState.playing = false;
  appState.time = Math.max(appState.replay.startTick, Math.floor(appState.time - 0.001));
});
el.btnNext.addEventListener('click', () => {
  appState.playing = false;
  appState.time = Math.min(appState.replay.endTick, Math.floor(appState.time + 1.001));
});
el.btnPlay.addEventListener('click', () => {
  if (!appState.replay || appState.replay.endTick <= appState.replay.startTick) return;
  if (!appState.playing && appState.time >= appState.replay.endTick - 1e-4) appState.time = appState.replay.startTick;
  appState.playing = !appState.playing;
});
el.scrubber.addEventListener('input', () => {
  appState.playing = false;
  appState.time = Number(el.scrubber.value);
});
el.speedSelect.addEventListener('change', () => { appState.speed = Number(el.speedSelect.value); });
el.btnToggleDock.addEventListener('click', () => {
  const collapsed = el.analyticsBody.classList.toggle('collapsed');
  el.btnToggleDock.textContent = collapsed ? '▴ Wykresy' : '▾ Wykresy';
});

for (const btn of document.querySelectorAll('.tab-btn')) {
  btn.addEventListener('click', () => setAnalyticsTab(btn.dataset.tab));
}

// Keyboard shortcuts
document.addEventListener('keydown', ev => {
  if (!appState.replay || ev.target.closest('input,select,textarea,button')) return;
  if (ev.code === 'Space') {
    ev.preventDefault();
    el.btnPlay.click();
  } else if (ev.key === 'ArrowLeft') {
    ev.preventDefault();
    el.btnPrev.click();
  } else if (ev.key === 'ArrowRight') {
    ev.preventDefault();
    el.btnNext.click();
  } else if (ev.key === '2') {
    setViewMode('2d');
  } else if (ev.key === '3') {
    setViewMode('3d');
  } else if (ev.key === 'r' || ev.key === 'R') {
    if (appState.viewMode === '2d') r2d.resetView();
    else r3d.fitToReplay(appState.replay);
  }
});

// File open & drag-and-drop JSON anywhere
async function loadFile(file) {
  try {
    const data = JSON.parse(await file.text());
    loadReplayData(data);
    const opt = new Option(`📁 ${file.name}`, '__custom__');
    const existing = el.missionSelect.querySelector('option[value="__custom__"]');
    if (existing) existing.remove();
    el.missionSelect.prepend(opt);
    el.missionSelect.value = '__custom__';
  } catch (err) {
    showNotice(err.message);
  }
}

el.btnOpen.addEventListener('click', () => el.fileInput.click());
el.fileInput.addEventListener('change', () => {
  const [f] = el.fileInput.files;
  if (f) loadFile(f);
  el.fileInput.value = '';
});

let dragDepth = 0;
window.addEventListener('dragenter', ev => { ev.preventDefault(); dragDepth++; el.dropOverlay.hidden = false; });
window.addEventListener('dragover', ev => ev.preventDefault());
window.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; el.dropOverlay.hidden = true; } });
window.addEventListener('drop', ev => {
  ev.preventDefault();
  dragDepth = 0;
  el.dropOverlay.hidden = true;
  const [f] = ev.dataTransfer.files;
  if (f) loadFile(f);
});

// ---- Load Missions (Server API or Offline Bundle) ----
async function fetchMissionById(id) {
  const ver = ++appState.loadVersion;
  if (bundledMissions && bundledMissions[id]) {
    try { loadReplayData(bundledMissions[id]); } catch (err) { showNotice(err.message); }
    return;
  }
  showNotice('Wczytywanie misji…');
  try {
    const resp = await fetch(`/api/mission?id=${encodeURIComponent(id)}`);
    if (!resp.ok) throw new Error(`Nie udało się wczytać misji (${resp.status}).`);
    const data = await resp.json();
    if (ver === appState.loadVersion) loadReplayData(data);
  } catch (err) {
    if (ver === appState.loadVersion) showNotice(err.message);
  }
}

el.missionSelect.addEventListener('change', () => {
  if (el.missionSelect.value && el.missionSelect.value !== '__custom__') {
    fetchMissionById(el.missionSelect.value);
  }
});

async function bootstrap() {
  setViewMode(appState.viewMode);
  if (bundledMissions) {
    const keys = Object.keys(bundledMissions);
    el.missionSelect.replaceChildren(...keys.map(k => new Option(`${bundledMissions[k].title} (${k})`, k)));
    if (keys.length) fetchMissionById(keys[0]);
    return;
  }
  try {
    const resp = await fetch('/api/missions');
    if (!resp.ok) throw new Error('Brak połączenia z lokalnym serwerem. Użyj "Otwórz JSON" lub przeciągnij plik.');
    const list = await resp.json();
    if (!list.length) {
      showNotice('Nie znaleziono plików scout-replay-v1 w katalogu runs/. Użyj "Otwórz JSON".');
      return;
    }
    el.missionSelect.replaceChildren(...list.map(m => {
      const badge = m.has_altitude ? ' [3D]' : m.agents === 0 ? ' [Mapa]' : '';
      const shortTitle = m.title.replace(/^SCOUT\s*[—·-]\s*/i, '');
      const file = m.id.split('/').pop();
      const prefix = file === 'mission.json' || file === 'map.json' ? m.group : `${m.group}/${file.replace('.json', '')}`;
      return new Option(`${prefix} · ${shortTitle}${badge}`, m.id);
    }));
    fetchMissionById(list[0].id);
  } catch (err) {
    showNotice(err.message);
  }
}

bootstrap();
requestAnimationFrame(tickLoop);
