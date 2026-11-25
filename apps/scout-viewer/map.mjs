import {cellColor, historyAt} from './replay.mjs';

export const agentColor = index => ['#f7ce69', '#83e2d5', '#e5adea', '#f4ac85'][index % 4];

export function drawMap(canvas, replay, {frame, eventIndex}, layer, values, style, options) {
  const {width, height} = replay.data.grid;
  const ratio = Math.min(window.devicePixelRatio || 1, 3);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return null;
  const pixelWidth = Math.round(w * ratio), pixelHeight = Math.round(h * ratio);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const size = Math.min((w - 32) / width, (h - 32) / height);
  if (size <= 0) return null;
  const left = (w - width * size) / 2, top = (h - height * size) / 2;
  const point = ([x, y]) => [left + x * size, top + y * size];
  const indices = new Map(replay.data.agents.map((agent, index) => [agent.id, index]));

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      ctx.fillStyle = cellColor(style, values?.[y * width + x]);
      ctx.fillRect(left + x * size, top + y * size, size + 0.5, size + 0.5);
    }
  }
  if (size >= 8) {
    ctx.beginPath();
    for (let x = 0; x <= width; x++) {
      ctx.moveTo(left + x * size, top);
      ctx.lineTo(left + x * size, top + height * size);
    }
    for (let y = 0; y <= height; y++) {
      ctx.moveTo(left, top + y * size);
      ctx.lineTo(left + width * size, top + y * size);
    }
    ctx.strokeStyle = '#14292755';
    ctx.lineWidth = 0.7;
    ctx.stroke();
  }

  if (options.footprints) {
    for (const [tasks, scheduled] of [[frame.completed, false], [frame.scheduled, true]]) {
      for (const task of tasks) {
        const [x, y, bw, bh] = task.footprint;
        const [px, py] = point([x, y]);
        const color = agentColor(indices.get(task.agent_id));
        ctx.save();
        ctx.lineWidth = 2;
        ctx.strokeStyle = color;
        ctx.setLineDash(scheduled ? [5, 4] : []);
        ctx.strokeRect(px + 1, py + 1, bw * size - 2, bh * size - 2);
        if (!scheduled) {
          ctx.beginPath();
          ctx.rect(px, py, bw * size, bh * size);
          ctx.clip();
          ctx.globalAlpha = 0.35;
          ctx.lineWidth = 1;
          ctx.beginPath();
          for (let i = 0; i < (bw + bh) * size; i += 9) {
            ctx.moveTo(px + i, py);
            ctx.lineTo(px + i - bh * size, py + bh * size);
          }
          ctx.stroke();
        }
        ctx.restore();
      }
    }
  }

  replay.data.agents.forEach((agent, index) => {
    const path = historyAt(replay, agent.id, eventIndex).map(p => point(p.xy));
    const [x, y] = path.at(-1);
    const color = agentColor(index);
    if (options.trails && path.length > 1) {
      ctx.beginPath();
      path.forEach(([px, py], i) => i ? ctx.lineTo(px, py) : ctx.moveTo(px, py));
      ctx.strokeStyle = '#1b302d';
      ctx.lineWidth = 4;
      ctx.stroke();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    const tasks = frame.scheduled.filter(task => task.agent_id === agent.id);
    if (options.plans) for (const task of tasks) {
      const [tx, ty] = point(task.xy);
      const distance = Math.hypot(tx - x, ty - y);
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.4;
      ctx.beginPath();
      if (distance > 11) {
        const angle = Math.atan2(ty - y, tx - x);
        ctx.setLineDash([5, 4]);
        ctx.moveTo(x, y);
        ctx.lineTo(tx, ty);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(tx - 9 * Math.cos(angle - 0.5), ty - 9 * Math.sin(angle - 0.5));
        ctx.lineTo(tx, ty);
        ctx.lineTo(tx - 9 * Math.cos(angle + 0.5), ty - 9 * Math.sin(angle + 0.5));
      } else {
        ctx.arc(tx, ty, 13, 0, 2 * Math.PI);
      }
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(x, y, 9, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = '#20322e';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.font = 'bold 10px system-ui';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#182c28';
    ctx.fillText(index + 1, x, y);
  });

  return {left, top, size, width, height, layer, values, style};
}
