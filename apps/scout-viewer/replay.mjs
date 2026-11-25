// Validate at the file boundary so a bad replay never partially replaces the current one.
export function readReplay(data) {
  const fail = (where) => { throw new Error('Nieprawidłowe dane: ' + where); };
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
      throw new Error('To konfiguracja generatora. Otwórz wygenerowaną mapę z runs/scout-map/map.json lub z lokalizacji podanej w --output.');
    }
    fail('schema (oczekiwano scout-replay-v1)');
  }
  if (!string(data.title)) fail('title');
  const {width, height, cell_size_m} = data.grid ?? {};
  if (![width, height].every(v => Number.isSafeInteger(v) && v > 0) ||
      !Number.isFinite(cell_size_m) || cell_size_m <= 0) fail('grid');
  const agentIds = named(data.agents, 'agents');
  for (const a of data.agents) if (!point(a.start_xy)) fail('agents.start_xy');
  named(data.layers, 'layers');
  if (!data.layers.length) fail('layers');
  const styles = new Map();
  for (const layer of data.layers) {
    if (!['scalar', 'categorical'].includes(layer.kind)) fail(layer.id + '.kind');
    if (layer.domain !== undefined && (!point(layer.domain) || layer.domain[1] < layer.domain[0])) fail(layer.id + '.domain');
    if (layer.unit !== undefined && typeof layer.unit !== 'string') fail(layer.id + '.unit');
    const labels = new Map();
    for (const c of list(layer.categories ?? [], 'categories')) {
      if (!object(c) || !category(c.id) || !string(c.label) || labels.has(c.id)) fail(layer.id + '.categories');
      labels.set(c.id, c.label);
    }
    styles.set(layer.id, {layer, labels, min: Infinity, max: -Infinity});
  }
  const grids = (value, where, table) => {
    if (!object(value)) fail(where);
    for (const [id, cells] of Object.entries(value)) {
      const style = table.get(id);
      if (!style || !Array.isArray(cells) || cells.length !== width * height) fail(where + '.' + id);
      for (const cell of cells) {
        if (cell === null) continue;
        if (style.layer.kind === 'scalar') {
          if (!Number.isFinite(cell)) fail(where + '.' + id);
          style.min = Math.min(style.min, cell);
          style.max = Math.max(style.max, cell);
        } else {
          if (!category(cell)) fail(where + '.' + id);
          if (!style.labels.has(cell)) style.labels.set(cell, String(cell));
        }
      }
    }
  };
  const paths = new Map(data.agents.map(agent => [agent.id, [{index: -1, xy: agent.start_xy}]]));
  if (!list(data.frames, 'frames').length) fail('frames');
  data.frames.forEach((frame, index) => {
    const where = 'frames[' + index + ']';
    if (!object(frame) || !Number.isFinite(frame.tick) || (index && frame.tick <= data.frames[index - 1].tick)) fail(where + '.tick');
    grids(frame.layers, where + '.layers', styles);
    const seen = new Set();
    for (const report of list(frame.agents, where + '.agents')) {
      if (!object(report) || !agentIds.has(report.id) || seen.has(report.id) || !point(report.xy)) fail(where + '.agents');
      if (report.altitude_m !== undefined && (!Number.isFinite(report.altitude_m) || report.altitude_m <= 0)) {
        fail(where + '.agents.altitude_m');
      }
      seen.add(report.id);
      const history = paths.get(report.id);
      const last = history.at(-1).xy;
      if (last[0] !== report.xy[0] || last[1] !== report.xy[1]) history.push({index, xy: report.xy});
    }
    for (const key of ['scheduled', 'completed']) {
      for (const task of list(frame[key], where + '.' + key)) {
        if (!object(task) || !agentIds.has(task.agent_id) || !string(task.mode) || !point(task.xy) ||
          !Array.isArray(task.footprint) || task.footprint.length !== 4 || !task.footprint.every(Number.isFinite) ||
          task.footprint[2] <= 0 || task.footprint[3] <= 0 || !Number.isFinite(task.start_tick) ||
          !Number.isFinite(task.finish_tick) || task.finish_tick < task.start_tick ||
          (task.standoff_m !== undefined && (!Number.isFinite(task.standoff_m) || task.standoff_m <= 0)) ||
          (task.arrival_tick !== undefined && (!Number.isFinite(task.arrival_tick) ||
            task.arrival_tick < task.start_tick || task.arrival_tick > task.finish_tick))) {
          fail(where + '.' + key);
        }
      }
    }
    if (frame.messages !== undefined) list(frame.messages, where + '.messages');
  });
  const referenceStyles = new Map([...styles].map(([id, style]) =>
    [id, {...style, labels: new Map(style.labels)}]));
  if (data.reference_layers !== undefined) grids(data.reference_layers, 'reference_layers', referenceStyles);
  for (const table of [styles, referenceStyles]) {
    for (const style of table.values()) {
      style.domain = style.layer.domain ?? (Number.isFinite(style.min) ? [style.min, style.max] : [0, 1]);
      style.codes = new Map([...style.labels.keys()].map((key, i) => [key, i]));
    }
  }
  return {data, paths, styles, referenceStyles, timeline: createTimeline(data.frames)};
}

export function createTimeline(frames) {
  const start = frames[0].tick;
  const span = frames.at(-1).tick - start + 1;
  // Native SCOUT replays use integer ticks. Keep fractional imported timestamps as recorded.
  const integerTicks = Number.isSafeInteger(span) && frames.every(frame => Number.isSafeInteger(frame.tick));
  const tickAt = step => integerTicks ? start + step : frames[step].tick;
  return {
    length: integerTicks ? span : frames.length,
    tickAt,
    at(step) {
      const tick = tickAt(step);
      let eventIndex = step;
      if (integerTicks) {
        // Locate the last actual snapshot without materializing a frame for every tick.
        let low = 0, high = frames.length;
        while (low < high) {
          const mid = Math.floor((low + high) / 2);
          if (frames[mid].tick <= tick) low = mid + 1;
          else high = mid;
        }
        eventIndex = low - 1;
      }
      const recorded = frames[eventIndex];
      const frame = recorded.tick === tick ? recorded : {
        ...recorded, tick, completed: [], messages: recorded.messages === undefined ? undefined : [],
      };
      return {frame, eventIndex};
    },
  };
}

export function historyAt(replay, id, index) {
  const path = replay.paths.get(id);
  const next = path.findIndex(p => p.index > index);
  return next < 0 ? path : path.slice(0, next);
}

export const scalarStops = ['#263f60', '#366f87', '#64a497', '#b8cb99', '#edce8f', '#ce8e65'];
const classes = ['#cead78', '#729490', '#769b63', '#9b83ac', '#6896b8', '#ce9288', '#babe74', '#897c6e'];
export function cellColor(style, value) {
  if (value == null) return '#283237';
  if (style.layer.kind === 'categorical') {
    const i = style.codes.get(value);
    return classes[i] ?? 'hsl(' + (i * 137.508 % 360) + ' 45% 61%)';
  }
  const [low, high] = style.domain;
  const t = high === low ? 0.5 : Math.max(0, Math.min(1, (value - low) / (high - low)));
  const s = t * (scalarStops.length - 1);
  const i = Math.min(Math.floor(s), scalarStops.length - 2);
  const channels = [1, 3, 5].map(offset => {
    const a = parseInt(scalarStops[i].slice(offset, offset + 2), 16);
    const b = parseInt(scalarStops[i + 1].slice(offset, offset + 2), 16);
    return Math.round(a + (b - a) * (s - i));
  });
  return 'rgb(' + channels.join(',') + ')';
}
