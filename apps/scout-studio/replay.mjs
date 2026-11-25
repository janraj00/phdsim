// SCOUT Studio — Replay parser, continuous-time interpolator, palettes & analytics.

export const AGENT_PALETTE = [
  {hex: '#38bdf8', rgb: [56, 189, 248], name: 'cyan'},
  {hex: '#fbbf24', rgb: [251, 191, 36], name: 'amber'},
  {hex: '#e879f9', rgb: [232, 121, 249], name: 'magenta'},
  {hex: '#34d399', rgb: [52, 211, 153], name: 'emerald'},
  {hex: '#fb7185', rgb: [251, 113, 133], name: 'rose'},
  {hex: '#a78bfa', rgb: [167, 139, 250], name: 'violet'},
];

export const agentStyle = index => AGENT_PALETTE[((index % AGENT_PALETTE.length) + AGENT_PALETTE.length) % AGENT_PALETTE.length];

const NAMED_CLASS_COLORS = {
  exposed_soil: [204, 142, 90],
  'exposed soil': [204, 142, 90],
  soil: [204, 142, 90],
  rock: [122, 138, 154],
  bedrock: [106, 118, 132],
  gravel: [158, 150, 138],
  regolith: [154, 142, 128],
  low_vegetation: [96, 156, 98],
  'low vegetation': [96, 156, 98],
  vegetation: [82, 148, 86],
  water: [56, 132, 196],
  sand: [224, 192, 128],
  road: [96, 102, 112],
};

const FALLBACK_CLASS_COLORS = [
  [204, 142, 90],
  [116, 142, 158],
  [96, 156, 98],
  [168, 128, 192],
  [92, 156, 206],
  [214, 126, 118],
  [198, 188, 104],
  [146, 132, 118],
];

export const ELEVATION_STOPS = [
  [30, 58, 95],
  [44, 106, 134],
  [78, 154, 138],
  [158, 188, 128],
  [226, 196, 122],
  [198, 126, 86],
  [235, 224, 214],
];

export const CONFIDENCE_STOPS = [
  [36, 32, 74],
  [49, 86, 138],
  [42, 148, 154],
  [78, 196, 144],
  [212, 232, 112],
];

export const ERROR_STOPS = [
  [52, 211, 153],
  [250, 204, 21],
  [249, 115, 22],
  [239, 68, 68],
];

export function rgbCss(rgb, alpha = 1) {
  return alpha >= 1 ? `rgb(${rgb[0]},${rgb[1]},${rgb[2]})` : `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha})`;
}

export function lerpStops(stops, t) {
  const clamped = Math.max(0, Math.min(1, t));
  const scaled = clamped * (stops.length - 1);
  const i = Math.min(Math.floor(scaled), stops.length - 2);
  const f = scaled - i;
  const a = stops[i], b = stops[i + 1];
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ];
}

export function stopsForLayer(layer) {
  const id = (layer?.id || '').toLowerCase();
  if (id.includes('confidence') || id.includes('certainty') || id.includes('prob')) return CONFIDENCE_STOPS;
  return ELEVATION_STOPS;
}

export function classColorRgb(style, value) {
  const label = (style.labels.get(value) || '').toLowerCase();
  const key = String(value).toLowerCase();
  if (NAMED_CLASS_COLORS[key]) return NAMED_CLASS_COLORS[key];
  if (NAMED_CLASS_COLORS[label]) return NAMED_CLASS_COLORS[label];
  const idx = style.codes.get(value) ?? 0;
  return FALLBACK_CLASS_COLORS[idx % FALLBACK_CLASS_COLORS.length];
}

export function cellColorRgb(style, value, darkTheme = true) {
  if (value == null) return darkTheme ? [26, 35, 46] : [214, 222, 218];
  if (style.layer.kind === 'categorical') return classColorRgb(style, value);
  const [low, high] = style.domain;
  const t = high === low ? 0.5 : (value - low) / (high - low);
  return lerpStops(stopsForLayer(style.layer), t);
}

export function errorColorRgb(layerKind, est, ref, domainSpan, darkTheme = true) {
  if (ref == null) return darkTheme ? [22, 30, 40] : [210, 216, 214];
  if (est == null) return darkTheme ? [36, 44, 56] : [188, 198, 196];
  if (layerKind === 'categorical') {
    return est === ref ? [46, 178, 128] : [228, 82, 82];
  }
  const err = Math.abs(est - ref);
  const scale = Math.max(0.5, domainSpan * 0.28);
  return lerpStops(ERROR_STOPS, Math.min(1, err / scale));
}

export function inferAgentKind(agent) {
  const text = `${agent.id} ${agent.label}`.toLowerCase();
  if (text.includes('rover') || text.includes('łazik') || text.includes('lazik') || text.includes('ugv')) {
    return 'rover';
  }
  return 'drone';
}

export function schematicAltitudeForMode(kind, mode, standoff) {
  if (kind === 'rover') return 0;
  if (Number.isFinite(standoff) && standoff > 0) return standoff;
  const m = (mode || '').toLowerCase();
  if (m === 'high') return 6.0;
  if (m === 'low') return 2.4;
  if (m === 'ground') return 0;
  return 3.5;
}

// Validate scout-replay-v1 at file boundary and precompute indices, trails, tasks, and metrics.
export function readReplay(data) {
  const fail = where => { throw new Error('Nieprawidłowe dane misji: ' + where); };
  const list = (value, where) => Array.isArray(value) ? value : fail(where);
  const object = v => v !== null && typeof v === 'object' && !Array.isArray(v);
  const string = v => typeof v === 'string' && v.trim().length > 0;
  const category = v => typeof v === 'string' || Number.isFinite(v);
  const point = v => Array.isArray(v) && v.length === 2 && v.every(Number.isFinite);
  const named = (items, where) => {
    const ids = new Set();
    for (const item of list(items, where)) {
      if (!object(item) || !string(item.id) || !string(item.label) || ids.has(item.id)) fail(where);
      ids.add(item.id);
    }
    return ids;
  };

  if (data?.schema !== 'scout-replay-v1') {
    if (object(data) && string(data.type) && object(data.shares_pct) &&
        'width' in data && 'height' in data && 'seed' in data) {
      throw new Error('To konfiguracja generatora terenu. Otwórz wygenerowaną mapę np. runs/scout-map/map.json.');
    }
    fail('schema (oczekiwano scout-replay-v1)');
  }
  if (!string(data.title)) fail('title');
  const {width, height, cell_size_m} = data.grid ?? {};
  if (![width, height].every(v => Number.isSafeInteger(v) && v > 0) ||
      !Number.isFinite(cell_size_m) || cell_size_m <= 0) fail('grid');

  const agentIds = named(data.agents, 'agents');
  const agents = data.agents.map((a, index) => {
    if (!point(a.start_xy)) fail('agents.start_xy');
    const kind = inferAgentKind(a);
    return {
      ...a,
      index,
      kind,
      style: agentStyle(index),
    };
  });
  const agentMap = new Map(agents.map(a => [a.id, a]));

  named(data.layers, 'layers');
  if (!data.layers.length) fail('layers');
  const styles = new Map();
  for (const layer of data.layers) {
    if (!['scalar', 'categorical'].includes(layer.kind)) fail(layer.id + '.kind');
    if (layer.domain !== undefined && (!point(layer.domain) || layer.domain[1] < layer.domain[0])) {
      fail(layer.id + '.domain');
    }
    if (layer.unit !== undefined && typeof layer.unit !== 'string') fail(layer.id + '.unit');
    const labels = new Map();
    for (const c of list(layer.categories ?? [], 'categories')) {
      if (!object(c) || !category(c.id) || !string(c.label) || labels.has(c.id)) fail(layer.id + '.categories');
      labels.set(c.id, c.label);
    }
    styles.set(layer.id, {layer, labels, min: Infinity, max: -Infinity});
  }

  const checkGrids = (value, where, table) => {
    if (!object(value)) fail(where);
    for (const [id, cells] of Object.entries(value)) {
      const style = table.get(id);
      if (!style || !Array.isArray(cells) || cells.length !== width * height) fail(where + '.' + id);
      for (const cell of cells) {
        if (cell === null) continue;
        if (style.layer.kind === 'scalar') {
          if (!Number.isFinite(cell)) fail(where + '.' + id);
          if (cell < style.min) style.min = cell;
          if (cell > style.max) style.max = cell;
        } else {
          if (!category(cell)) fail(where + '.' + id);
          if (!style.labels.has(cell)) style.labels.set(cell, String(cell));
        }
      }
    }
  };

  if (!list(data.frames, 'frames').length) fail('frames');
  let hasRealAltitude = false;
  const agentFrames = new Map(agents.map(a => [a.id, []]));

  data.frames.forEach((frame, fIdx) => {
    const where = `frames[${fIdx}]`;
    if (!object(frame) || !Number.isFinite(frame.tick) || (fIdx && frame.tick <= data.frames[fIdx - 1].tick)) {
      fail(where + '.tick');
    }
    checkGrids(frame.layers, where + '.layers', styles);
    const seen = new Set();
    for (const report of list(frame.agents, where + '.agents')) {
      if (!object(report) || !agentIds.has(report.id) || seen.has(report.id) || !point(report.xy)) {
        fail(where + '.agents');
      }
      if (report.altitude_m !== undefined) {
        if (!Number.isFinite(report.altitude_m) || report.altitude_m < 0) fail(where + '.agents.altitude_m');
        hasRealAltitude = true;
      }
      seen.add(report.id);
      agentFrames.get(report.id).push({
        tick: frame.tick,
        frameIndex: fIdx,
        xy: report.xy,
        altitude_m: report.altitude_m,
      });
    }
    for (const key of ['scheduled', 'completed']) {
      for (const task of list(frame[key], where + '.' + key)) {
        if (!object(task) || !agentIds.has(task.agent_id) || !string(task.mode) || !point(task.xy) ||
            !Array.isArray(task.footprint) || task.footprint.length !== 4 || !task.footprint.every(Number.isFinite) ||
            task.footprint[2] <= 0 || task.footprint[3] <= 0 || !Number.isFinite(task.start_tick) ||
            !Number.isFinite(task.finish_tick) || task.finish_tick < task.start_tick) {
          fail(where + '.' + key);
        }
      }
    }
    if (frame.messages !== undefined) list(frame.messages, where + '.messages');
  });

  const referenceStyles = new Map([...styles].map(([id, style]) => [id, {...style, labels: new Map(style.labels)}]));
  if (data.reference_layers !== undefined) checkGrids(data.reference_layers, 'reference_layers', referenceStyles);

  for (const table of [styles, referenceStyles]) {
    for (const style of table.values()) {
      style.domain = style.layer.domain ?? (Number.isFinite(style.min) ? [style.min, style.max] : [0, 1]);
      style.codes = new Map([...style.labels.keys()].map((k, i) => [k, i]));
    }
  }

  const startTick = data.frames[0].tick;
  const endTick = data.frames.at(-1).tick;
  const secondsPerTick = Number.isFinite(data.seconds_per_tick) && data.seconds_per_tick > 0 ? data.seconds_per_tick : 1;

  // Detect whether frames are dense (nearly 1 tick apart) vs sparse (event-only snapshots).
  const span = endTick - startTick;
  const denseTrajectory = data.frames.length > 1 && span > 0 && (data.frames.length - 1) / span >= 0.75;

  // Identify elevation layer for 3D terrain relief if present.
  const elevationLayerId = ['elevation_m', 'surface', 'ground'].find(
    id => styles.has(id) && styles.get(id).layer.kind === 'scalar'
  ) || null;
  const confidenceLayerId = styles.has('confidence') ? 'confidence' : null;

  const ganttTasks = extractTasks(data.frames, agentMap);
  const analytics = computeAnalytics(data, styles, agents, ganttTasks);

  return {
    data,
    agents,
    agentMap,
    agentFrames,
    styles,
    referenceStyles,
    startTick,
    endTick,
    secondsPerTick,
    denseTrajectory,
    hasRealAltitude,
    elevationLayerId,
    confidenceLayerId,
    ganttTasks,
    analytics,
  };
}

function taskKey(t) {
  return `${t.agent_id}|${t.start_tick}|${t.finish_tick}|${t.xy[0]},${t.xy[1]}|${t.mode}`;
}

function extractTasks(frames, agentMap) {
  const byKey = new Map();
  for (const frame of frames) {
    for (const task of frame.scheduled) {
      const k = taskKey(task);
      if (!byKey.has(k)) {
        const agent = agentMap.get(task.agent_id);
        const arrival = Number.isFinite(task.arrival_tick)
          ? task.arrival_tick
          : task.start_tick + (task.finish_tick - task.start_tick) * 0.6;
        byKey.set(k, {
          ...task,
          arrival_tick: arrival,
          completed: false,
          completed_tick: null,
          standoff_m: task.standoff_m ?? schematicAltitudeForMode(agent.kind, task.mode, undefined),
        });
      }
    }
    for (const task of frame.completed) {
      const k = taskKey(task);
      const existing = byKey.get(k);
      const agent = agentMap.get(task.agent_id);
      if (existing) {
        existing.completed = true;
        existing.completed_tick = frame.tick;
      } else {
        const arrival = Number.isFinite(task.arrival_tick)
          ? task.arrival_tick
          : task.start_tick + (task.finish_tick - task.start_tick) * 0.6;
        byKey.set(k, {
          ...task,
          arrival_tick: arrival,
          completed: true,
          completed_tick: frame.tick,
          standoff_m: task.standoff_m ?? schematicAltitudeForMode(agent.kind, task.mode, undefined),
        });
      }
    }
  }
  return [...byKey.values()].sort((a, b) => a.start_tick - b.start_tick || a.finish_tick - b.finish_tick);
}

function computeAnalytics(data, styles, agents, ganttTasks) {
  const totalCells = data.grid.width * data.grid.height;
  const refLayers = data.reference_layers || {};
  const perLayer = new Map();

  for (const layer of data.layers) {
    const id = layer.id;
    const ref = refLayers[id] || null;
    const series = [];
    for (const frame of data.frames) {
      const values = frame.layers[id];
      let observed = 0;
      let correct = 0;
      let sqErr = 0;
      let absErr = 0;
      let withinTol = 0;
      let sumVal = 0;
      if (values) {
        for (let i = 0; i < totalCells; i++) {
          const v = values[i];
          if (v === null || v === undefined) continue;
          observed++;
          if (layer.kind === 'scalar') sumVal += v;
          if (ref && ref[i] !== null && ref[i] !== undefined) {
            if (layer.kind === 'categorical') {
              if (v === ref[i]) correct++;
            } else {
              const d = Math.abs(v - ref[i]);
              absErr += d;
              sqErr += d * d;
              if (d <= 0.25) withinTol++;
            }
          }
        }
      }
      const coverage = totalCells ? observed / totalCells : 0;
      const accuracyObserved = observed && ref && layer.kind === 'categorical' ? correct / observed : null;
      const accuracyTotal = totalCells && ref && layer.kind === 'categorical' ? correct / totalCells : null;
      const rmse = observed && ref && layer.kind === 'scalar' ? Math.sqrt(sqErr / observed) : null;
      const mae = observed && ref && layer.kind === 'scalar' ? absErr / observed : null;
      const within25cm = totalCells && ref && layer.kind === 'scalar' ? withinTol / totalCells : null;
      const meanScalar = observed && layer.kind === 'scalar' ? sumVal / observed : null;
      series.push({
        tick: frame.tick,
        observed,
        coverage,
        accuracyObserved,
        accuracyTotal,
        rmse,
        mae,
        within25cm,
        meanScalar,
      });
    }
    perLayer.set(id, {layer, hasRef: Boolean(ref), series});
  }

  // Per-agent altitude series
  const altitudeSeries = new Map();
  for (const agent of agents) {
    const pts = [];
    for (const frame of data.frames) {
      const rep = frame.agents.find(a => a.id === agent.id);
      if (rep && Number.isFinite(rep.altitude_m)) {
        pts.push({tick: frame.tick, altitude_m: rep.altitude_m});
      }
    }
    if (pts.length) altitudeSeries.set(agent.id, pts);
  }

  return {
    totalCells,
    perLayer,
    altitudeSeries,
    totalCompleted: ganttTasks.filter(t => t.completed).length,
    totalScheduled: ganttTasks.length,
  };
}

// Binary search: index of last frame with frame.tick <= t.
export function frameIndexAt(frames, t) {
  let lo = 0, hi = frames.length - 1;
  if (t <= frames[0].tick) return 0;
  if (t >= frames[hi].tick) return hi;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (frames[mid].tick <= t) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

// Sample continuous state at arbitrary simulation time t in [startTick, endTick].
export function sampleState(replay, t, {smoothMotion = true} = {}) {
  const {data, agents, startTick, endTick} = replay;
  const time = Math.max(startTick, Math.min(endTick, t));
  const fIdx = frameIndexAt(data.frames, time);
  const frame = data.frames[fIdx];
  const nextFrame = fIdx + 1 < data.frames.length ? data.frames[fIdx + 1] : null;
  const exactFrame = Math.abs(time - frame.tick) < 1e-6;

  // Determine recently completed captures (for brief visual flash over ~1.1 ticks).
  const recentCompleted = [];
  for (let i = fIdx; i >= 0; i--) {
    const fr = data.frames[i];
    const age = time - fr.tick;
    if (age > 1.2) break;
    if (age >= -1e-6) {
      for (const task of fr.completed) {
        recentCompleted.push({task, age: Math.max(0, age)});
      }
    }
  }

  const agentStates = agents.map(agent => {
    const rep = frame.agents.find(a => a.id === agent.id);
    const nextRep = nextFrame?.agents.find(a => a.id === agent.id);
    const activeTask = frame.scheduled.find(s => s.agent_id === agent.id) || null;

    let xy = rep ? [...rep.xy] : [...agent.start_xy];
    let altitude = rep?.altitude_m;
    let altitudeIsReal = Number.isFinite(altitude);
    let heading = 0;
    let stage = 'idle'; // 'flight' | 'measure' | 'idle'
    let taskProgress = 0;

    if (activeTask) {
      const arrival = Number.isFinite(activeTask.arrival_tick)
        ? activeTask.arrival_tick
        : activeTask.start_tick + (activeTask.finish_tick - activeTask.start_tick) * 0.6;
      const totalDur = Math.max(1e-6, activeTask.finish_tick - activeTask.start_tick);
      taskProgress = Math.max(0, Math.min(1, (time - activeTask.start_tick) / totalDur));
      stage = time < arrival - 1e-6 ? 'flight' : 'measure';
    }

    if (smoothMotion) {
      if (replay.denseTrajectory && nextFrame && rep && nextRep) {
        // Direct smooth interpolation between consecutive per-second simulated poses.
        const dt = nextFrame.tick - frame.tick;
        const alpha = dt > 0 ? Math.max(0, Math.min(1, (time - frame.tick) / dt)) : 0;
        xy = [
          rep.xy[0] + (nextRep.xy[0] - rep.xy[0]) * alpha,
          rep.xy[1] + (nextRep.xy[1] - rep.xy[1]) * alpha,
        ];
        if (Number.isFinite(rep.altitude_m) && Number.isFinite(nextRep.altitude_m)) {
          altitude = rep.altitude_m + (nextRep.altitude_m - rep.altitude_m) * alpha;
          altitudeIsReal = true;
        }
        const dx = nextRep.xy[0] - rep.xy[0], dy = nextRep.xy[1] - rep.xy[1];
        if (Math.hypot(dx, dy) > 1e-4) heading = Math.atan2(dy, dx);
      } else if (activeTask && rep) {
        // Sparse event replay: smoothly animate transit from confirmed pose to task target during flight phase.
        const arrival = Number.isFinite(activeTask.arrival_tick)
          ? activeTask.arrival_tick
          : activeTask.start_tick + (activeTask.finish_tick - activeTask.start_tick) * 0.65;
        const flightDur = Math.max(1e-6, arrival - activeTask.start_tick);
        const raw = Math.max(0, Math.min(1, (time - activeTask.start_tick) / flightDur));
        // Ease in-out cubic for natural drone transit.
        const ease = raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
        xy = [
          rep.xy[0] + (activeTask.xy[0] - rep.xy[0]) * ease,
          rep.xy[1] + (activeTask.xy[1] - rep.xy[1]) * ease,
        ];
        const dx = activeTask.xy[0] - rep.xy[0], dy = activeTask.xy[1] - rep.xy[1];
        if (Math.hypot(dx, dy) > 1e-4) heading = Math.atan2(dy, dx);
      }
    }

    if (!altitudeIsReal) {
      altitude = activeTask
        ? schematicAltitudeForMode(agent.kind, activeTask.mode, activeTask.standoff_m)
        : (agent.kind === 'rover' ? 0 : (agent.start_altitude_m ?? 3.5));
    }

    // Build 3D trail up to current time
    const trail = [{xy: agent.start_xy, altitude_m: agent.kind === 'rover' ? 0 : (agent.start_altitude_m ?? altitude)}];
    const records = replay.agentFrames.get(agent.id) || [];
    for (const r of records) {
      if (r.tick > time + 1e-6) break;
      const alt = Number.isFinite(r.altitude_m)
        ? r.altitude_m
        : (agent.kind === 'rover' ? 0 : (agent.start_altitude_m ?? altitude));
      const last = trail.at(-1);
      if (Math.hypot(last.xy[0] - r.xy[0], last.xy[1] - r.xy[1]) > 1e-4 || Math.abs(last.altitude_m - alt) > 1e-4) {
        trail.push({xy: r.xy, altitude_m: alt});
      }
    }
    const lastPt = trail.at(-1);
    if (Math.hypot(lastPt.xy[0] - xy[0], lastPt.xy[1] - xy[1]) > 1e-4 || Math.abs(lastPt.altitude_m - altitude) > 1e-4) {
      trail.push({xy, altitude_m: altitude});
    }
    // Derive fallback heading from trail if stationary
    if (heading === 0 && trail.length >= 2) {
      const a = trail[trail.length - 2].xy, b = trail[trail.length - 1].xy;
      if (Math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-4) heading = Math.atan2(b[1] - a[1], b[0] - a[0]);
    }

    return {
      agent,
      xy,
      confirmedXy: rep ? rep.xy : agent.start_xy,
      altitude,
      altitudeIsReal,
      heading,
      stage,
      activeTask,
      taskProgress,
      trail,
    };
  });

  return {
    time,
    frameIndex: fIdx,
    frame,
    exactFrame,
    agentStates,
    recentCompleted,
    completedNow: exactFrame ? frame.completed : [],
    messagesNow: frame.messages === undefined ? undefined : (exactFrame ? frame.messages : []),
  };
}
