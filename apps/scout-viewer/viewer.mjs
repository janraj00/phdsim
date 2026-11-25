import {agentColor, drawMap} from './map.mjs';
import {cellColor, historyAt, readReplay, scalarStops} from './replay.mjs';

const get = id => document.getElementById(id);
const ui = Object.fromEntries(['map', 'notice', 'workspace', 'title', 'metadata', 'source', 'open', 'file',
  'layer', 'reference', 'scale', 'tick', 'frame-number', 'seek', 'first', 'prev', 'play', 'next', 'last',
  'speed', 'fleet-count', 'fleet', 'capture-count', 'events', 'trails', 'plans', 'footprints', 'message-status',
  'messages', 'inspect'].map(id => [id, get(id)]));
const modeLabels = {high: 'Pomiar z wysoka', low: 'Pomiar z niska', ground: 'Pomiar naziemny',
  rgb: 'RGB', lidar: 'LiDAR', 'rgb+lidar': 'RGB i LiDAR'};
const number = new Intl.NumberFormat('pl', {maximumFractionDigits: 2});
let replay, index = 0, timer = null, mapState, loadVersion = 0;
const embedded = document.getElementById('scout-bundled-replays');
const bundledReplays = embedded ? JSON.parse(embedded.textContent) : null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function fact(label, text) {
  const row = element('div', 'fact');
  row.append(element('span', '', label), element('span', 'coords', text));
  return row;
}

function formatXY(xy) {
  return '(' + xy.map(v => number.format(v)).join('; ') + ')';
}

function robotBadge(index) {
  const badge = element('span', 'robot-no', index + 1);
  badge.style.setProperty('--agent', agentColor(index));
  return badge;
}

function renderLegend(style) {
  ui.scale.replaceChildren();
  if (style.layer.kind === 'scalar') {
    const [low, high] = style.domain;
    const stops = element('span', 'gradient');
    stops.style.background = 'linear-gradient(90deg,' + scalarStops.join(',') + ')';
    ui.scale.append(element('span', 'number', number.format(low)), stops,
      element('span', 'number', number.format(high) + (style.layer.unit ? ' ' + style.layer.unit : '')));
  } else {
    for (const [id, name] of style.labels) addSwatch(cellColor(style, id), name);
  }
  addSwatch(cellColor(style, null), 'Brak danych', ' null');

  function addSwatch(color, label, extra = '') {
    const item = element('span', 'scale-item' + extra);
    const swatch = element('i', 'swatch');
    swatch.style.background = color;
    item.append(swatch, document.createTextNode(label));
    ui.scale.append(item);
  }
}

function draw() {
  if (!replay) return;
  const cursor = replay.timeline.at(index);
  const id = ui.layer.value;
  const reference = ui.reference.checked;
  const layers = reference ? replay.data.reference_layers : cursor.frame.layers;
  const style = (reference ? replay.referenceStyles : replay.styles).get(id);
  mapState = drawMap(ui.map, replay, cursor, id, layers[id], style, {
    trails: ui.trails.checked, plans: ui.plans.checked, footprints: ui.footprints.checked,
  });
}

function render() {
  const {data, timeline} = replay;
  const {frame, eventIndex} = timeline.at(index);
  const id = ui.layer.value;
  ui.reference.disabled = !data.reference_layers?.[id];
  if (ui.reference.disabled) ui.reference.checked = false;
  renderLegend((ui.reference.checked ? replay.referenceStyles : replay.styles).get(id));
  ui.tick.textContent = frame.tick;
  ui['frame-number'].textContent = (index + 1) + ' / ' + timeline.length;
  ui.seek.value = index;
  ui.seek.setAttribute('aria-valuetext', 'Krok ' + frame.tick);
  ui.first.disabled = ui.prev.disabled = index === 0;
  ui.next.disabled = ui.last.disabled = index === timeline.length - 1;
  ui.play.disabled = timeline.length < 2;
  ui.play.textContent = timer === null ? 'Odtwórz' : 'Wstrzymaj';
  ui['fleet-count'].textContent = data.agents.length;
  ui.fleet.replaceChildren(...data.agents.map((agent, i) => {
    const robot = element('div', 'robot');
    const head = element('div', 'robot-head');
    head.append(robotBadge(i), document.createTextNode(agent.label));
    const position = historyAt(replay, agent.id, eventIndex).at(-1).xy;
    const altitude = frame.agents.find(report => report.id === agent.id)?.altitude_m;
    const tasks = frame.scheduled.filter(task => task.agent_id === agent.id);
    const simulatedMotion = altitude !== undefined || tasks.some(task => task.arrival_tick !== undefined);
    robot.append(head, fact(simulatedMotion ? 'Pozycja w symulacji' : 'Ostatnia potwierdzona pozycja',
      formatXY(position)));
    if (altitude !== undefined) robot.append(fact('Wysokość w symulacji', number.format(altitude) + ' m'));
    for (const task of tasks) {
      robot.append(fact('Miejsce następnego pomiaru', formatXY(task.xy)),
        fact('Planowany koniec pomiaru', 'Krok ' + task.finish_tick));
      if (task.standoff_m !== undefined) {
        robot.append(fact('Wysokość następnego pomiaru', number.format(task.standoff_m) + ' m'));
      }
      if (task.arrival_tick !== undefined) {
        const travelLabel = altitude === undefined ? 'Dojazd' : 'Dolot';
        robot.append(fact('Etap', frame.tick < task.arrival_tick ? travelLabel : 'Pomiar'));
      }
    }
    return robot;
  }));
  ui['capture-count'].textContent = frame.completed.length;
  ui.events.replaceChildren(...frame.completed.map(task => {
    const i = data.agents.findIndex(a => a.id === task.agent_id);
    const row = element('div', 'event');
    const detail = element('div', '', modeLabels[task.mode] || task.mode);
    const location = data.agents[i].label + ' · ' + formatXY(task.xy);
    const altitude = task.standoff_m === undefined ? '' : ' · ' + number.format(task.standoff_m) + ' m nad terenem';
    detail.append(element('small', '', location + altitude));
    row.append(robotBadge(i), detail);
    return row;
  }));
  if (!frame.completed.length) ui.events.append(element('p', 'muted', 'Brak zakończonego pomiaru w tym kroku.'));
  ui['message-status'].textContent = frame.messages === undefined
    ? 'Ta symulacja nie modeluje wiadomości.' : 'Wiadomości w tym kroku: ' + frame.messages.length;
  ui.messages.hidden = !frame.messages?.length;
  ui.messages.textContent = frame.messages?.length ? JSON.stringify(frame.messages, null, 2) : '';
  ui.inspect.hidden = true;
  draw();
}

function setReplay(data) {
  const parsed = readReplay(data);
  stopPlayback();
  replay = parsed;
  index = 0;
  ui.title.textContent = data.title;
  ui.metadata.textContent = data.grid.width + ' × ' + data.grid.height + ' · '
    + number.format(data.grid.cell_size_m) + ' m / pole';
  ui.layer.replaceChildren(...data.layers.map(l => new Option(l.label, l.id)));
  if (data.layers.some(layer => layer.id === 'fused' && layer.kind === 'categorical')) ui.layer.value = 'fused';
  ui.reference.checked = false;
  ui.seek.max = replay.timeline.length - 1;
  ui.workspace.hidden = false;
  ui.notice.textContent = '';
  render();
}

async function loadSource(read) {
  const version = ++loadVersion;
  ui.notice.textContent = 'Wczytywanie misji…';
  try {
    const data = await read(version);
    if (version === loadVersion) setReplay(data);
  } catch (error) {
    if (version === loadVersion) ui.notice.textContent = error.name === 'TimeoutError'
      ? 'Serwer nie odpowiedział. Odśwież stronę i spróbuj ponownie.' : error.message;
  }
}

function loadSelected({fallbackToHeight = false} = {}) {
  const path = ui.source.value;
  if (bundledReplays) return loadSource(async () => bundledReplays[path]);
  return loadSource(async version => {
    const signal = AbortSignal.timeout(8000);
    let response = await fetch(path, {signal});
    if (fallbackToHeight && path === 'semantic.json' && response.status === 404) {
      response = await fetch('mission.json', {signal});
      if (response.ok && version === loadVersion) ui.source.value = 'mission.json';
    }
    if (!response.ok) throw new Error('Brak zapisu misji (' + path + '). Możesz otworzyć własny plik JSON.');
    return response.json();
  });
}

function jump(target) {
  if (!replay) return;
  index = Math.min(replay.timeline.length - 1, Math.max(0, target));
  render();
}

function stopPlayback() {
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

function schedulePlayback() {
  const timeline = replay.timeline;
  if (index >= timeline.length - 1) {
    stopPlayback();
    render();
    return;
  }
  const ticks = timeline.tickAt(index + 1) - timeline.tickAt(index);
  timer = setTimeout(() => {
    index += 1;
    schedulePlayback();
  }, Math.max(80, Math.min(1800, 220 * ticks * Number(ui.speed.value))));
  render();
}

for (const [key, step] of [['first', () => 0], ['prev', () => index - 1], ['next', () => index + 1],
  ['last', () => replay.timeline.length - 1], ['seek', () => Number(ui.seek.value)]]) {
  ui[key].addEventListener(key === 'seek' ? 'input' : 'click', () => { stopPlayback(); jump(step()); });
}
ui.play.addEventListener('click', () => {
  if (timer !== null) { stopPlayback(); render(); }
  else {
    if (index === replay.timeline.length - 1) index = 0;
    schedulePlayback();
  }
});
ui.speed.addEventListener('change', () => {
  if (timer !== null) { stopPlayback(); schedulePlayback(); }
});
for (const id of ['layer', 'reference', 'trails', 'plans', 'footprints']) ui[id].addEventListener('change', render);
ui.source.addEventListener('change', () => loadSelected());
ui.open.addEventListener('click', () => ui.file.click());
ui.file.addEventListener('change', () => {
  const [file] = ui.file.files;
  if (file) loadSource(async () => JSON.parse(await file.text()));
  ui.file.value = '';
});
ui.map.addEventListener('pointermove', event => {
  if (!mapState) return;
  const {left, top, size, width, height, values, style} = mapState;
  const x = Math.floor((event.offsetX - left) / size), y = Math.floor((event.offsetY - top) / size);
  ui.inspect.hidden = x < 0 || y < 0 || x >= width || y >= height;
  if (ui.inspect.hidden) return;
  const value = values?.[y * width + x];
  const label = value == null ? 'brak danych' : (style.layer.kind === 'categorical'
    ? style.labels.get(value) : number.format(value) + (style.layer.unit ? ' ' + style.layer.unit : ''));
  ui.inspect.textContent = formatXY([x, y]) + ' · ' + label;
});
ui.map.addEventListener('pointerleave', () => { ui.inspect.hidden = true; });
new ResizeObserver(draw).observe(ui.map);
document.addEventListener('keydown', event => {
  if (!replay || event.target.closest('button,input,select,textarea') || !['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
  event.preventDefault();
  stopPlayback();
  jump(index + (event.key === 'ArrowLeft' ? -1 : 1));
});
if (bundledReplays) {
  for (const option of ui.source.options) option.disabled = !Object.hasOwn(bundledReplays, option.value);
  if (ui.source.selectedOptions[0].disabled) ui.source.value = Object.keys(bundledReplays)[0];
}
loadSelected({fallbackToHeight: true});
