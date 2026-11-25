// SCOUT Studio — High-precision interactive 2D tactical canvas renderer.
import {cellColorRgb, errorColorRgb, rgbCss} from './replay.mjs';

export class Renderer2D {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this.hoverCell = null;
    this.offEst = document.createElement('canvas');
    this.offRef = document.createElement('canvas');
    this._cacheKey = '';
    this._lastLayout = null;
  }

  resetView() {
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
  }

  zoomBy(factor, cx, cy) {
    const oldZoom = this.zoom;
    const nextZoom = Math.max(0.55, Math.min(12, oldZoom * factor));
    const ratio = nextZoom / oldZoom;
    if (cx !== undefined && cy !== undefined && this._lastLayout) {
      const {w, h} = this._lastLayout;
      const dx = cx - (w / 2 + this.panX);
      const dy = cy - (h / 2 + this.panY);
      this.panX -= dx * (ratio - 1);
      this.panY -= dy * (ratio - 1);
    }
    this.zoom = nextZoom;
  }

  panBy(dx, dy) {
    this.panX += dx;
    this.panY += dy;
  }

  screenToCell(sx, sy) {
    const L = this._lastLayout;
    if (!L) return null;
    const gx = Math.floor((sx - L.left) / L.cellPx);
    const gy = Math.floor((sy - L.top) / L.cellPx);
    if (gx < 0 || gy < 0 || gx >= L.width || gy >= L.height) return null;
    return {x: gx, y: gy};
  }

  _updateOffscreen(replay, state, layerId, compareMode, showUncertainty, darkTheme) {
    const {width, height} = replay.data.grid;
    const key = `${replay.data.title}|${state.frameIndex}|${layerId}|${compareMode}|${showUncertainty}|${darkTheme}`;
    if (key === this._cacheKey) return;
    this._cacheKey = key;

    const style = replay.styles.get(layerId);
    const refStyle = replay.referenceStyles.get(layerId);
    const estValues = state.frame.layers[layerId];
    const refValues = replay.data.reference_layers?.[layerId] || null;
    const confValues = showUncertainty && replay.confidenceLayerId
      ? state.frame.layers[replay.confidenceLayerId]
      : null;
    const domainSpan = style ? Math.max(1e-6, style.domain[1] - style.domain[0]) : 1;

    const paintCanvas = (off, mode) => {
      if (off.width !== width || off.height !== height) {
        off.width = width;
        off.height = height;
      }
      const octx = off.getContext('2d');
      const img = octx.createImageData(width, height);
      const buf = img.data;
      for (let i = 0; i < width * height; i++) {
        let rgb;
        if (mode === 'reference' && refValues) {
          rgb = cellColorRgb(refStyle || style, refValues[i], darkTheme);
        } else if (mode === 'error' && refValues) {
          rgb = errorColorRgb(style.layer.kind, estValues?.[i], refValues[i], domainSpan, darkTheme);
        } else {
          rgb = cellColorRgb(style, estValues?.[i], darkTheme);
          if (confValues && estValues?.[i] != null && confValues[i] != null) {
            // Subtle uncertainty dimming: low confidence blends toward slate shadow.
            const c = Math.max(0, Math.min(1, confValues[i]));
            const keep = 0.42 + 0.58 * c;
            const bg = darkTheme ? 22 : 215;
            rgb = [
              Math.round(bg + (rgb[0] - bg) * keep),
              Math.round(bg + (rgb[1] - bg) * keep),
              Math.round(bg + (rgb[2] - bg) * keep),
            ];
          }
        }
        const p = i * 4;
        buf[p] = rgb[0];
        buf[p + 1] = rgb[1];
        buf[p + 2] = rgb[2];
        buf[p + 3] = 255;
      }
      octx.putImageData(img, 0, 0);
    };

    if (compareMode === 'split' && refValues) {
      paintCanvas(this.offEst, 'estimate');
      paintCanvas(this.offRef, 'reference');
    } else {
      paintCanvas(this.offEst, compareMode);
    }
  }

  render(replay, state, opts) {
    const {
      layerId, compareMode = 'estimate', splitRatio = 0.5,
      showUncertainty = false, showTrails = true, showPlans = true,
      showFootprints = true, showGrid = true, darkTheme = true, animTime = 0,
    } = opts;

    const canvas = this.canvas;
    const ratio = Math.min(window.devicePixelRatio || 1, 2.5);
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return null;
    const pw = Math.round(w * ratio), ph = Math.round(h * ratio);
    if (canvas.width !== pw || canvas.height !== ph) {
      canvas.width = pw;
      canvas.height = ph;
    }

    const ctx = this.ctx;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // Subtle tactical dot-grid backdrop
    ctx.fillStyle = darkTheme ? '#0b1118' : '#e6ece8';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = darkTheme ? 'rgba(148,163,184,0.1)' : 'rgba(24,44,40,0.08)';
    const dotStep = 22;
    for (let y = dotStep / 2; y < h; y += dotStep) {
      for (let x = dotStep / 2; x < w; x += dotStep) {
        ctx.fillRect(x, y, 1.2, 1.2);
      }
    }

    const {width, height, cell_size_m} = replay.data.grid;
    const baseCell = Math.min((w - 110) / width, (h - 148) / height);
    if (baseCell <= 0) return null;
    const cellPx = baseCell * this.zoom;
    const mapW = width * cellPx;
    const mapH = height * cellPx;
    const left = (w - mapW) / 2 + this.panX;
    const top = (h - mapH) / 2 + this.panY;
    const pt = ([gx, gy]) => [left + gx * cellPx, top + gy * cellPx];
    this._lastLayout = {w, h, left, top, mapW, mapH, cellPx, width, height};

    this._updateOffscreen(replay, state, layerId, compareMode, showUncertainty, darkTheme);

    // Subtle elevation frame shadow around map
    ctx.save();
    ctx.shadowColor = darkTheme ? 'rgba(0,0,0,0.55)' : 'rgba(15,35,30,0.18)';
    ctx.shadowBlur = 24;
    ctx.shadowOffsetY = 8;
    ctx.fillStyle = darkTheme ? '#131d28' : '#ffffff';
    ctx.fillRect(left - 2, top - 2, mapW + 4, mapH + 4);
    ctx.restore();

    // Draw rasterized grid sharply (pixelated)
    const hasRef = Boolean(replay.data.reference_layers?.[layerId]);
    const isSplit = compareMode === 'split' && hasRef;
    const splitScreenX = left + mapW * splitRatio;

    ctx.save();
    ctx.imageSmoothingEnabled = false;
    if (isSplit) {
      // Left: Estimate
      ctx.save();
      ctx.beginPath();
      ctx.rect(left, top, Math.max(0, splitScreenX - left), mapH);
      ctx.clip();
      ctx.drawImage(this.offEst, left, top, mapW, mapH);
      ctx.restore();
      // Right: Reference
      ctx.save();
      ctx.beginPath();
      ctx.rect(splitScreenX, top, Math.max(0, left + mapW - splitScreenX), mapH);
      ctx.clip();
      ctx.drawImage(this.offRef, left, top, mapW, mapH);
      ctx.restore();
    } else {
      ctx.drawImage(this.offEst, left, top, mapW, mapH);
    }
    ctx.restore();

    // Optional uncertainty diagonal micro-hatching on low-confidence cells (<0.6)
    if (showUncertainty && replay.confidenceLayerId && compareMode !== 'reference' && compareMode !== 'error' && cellPx >= 10) {
      const conf = state.frame.layers[replay.confidenceLayerId];
      const est = state.frame.layers[layerId];
      if (conf && est) {
        ctx.save();
        ctx.strokeStyle = darkTheme ? 'rgba(10,16,24,0.34)' : 'rgba(20,40,36,0.22)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let gy = 0; gy < height; gy++) {
          for (let gx = 0; gx < width; gx++) {
            const idx = gy * width + gx;
            if (est[idx] != null && conf[idx] != null && conf[idx] < 0.62) {
              const cx = left + gx * cellPx, cy = top + gy * cellPx;
              ctx.moveTo(cx + 2, cy + cellPx - 2);
              ctx.lineTo(cx + cellPx - 2, cy + 2);
            }
          }
        }
        ctx.stroke();
        ctx.restore();
      }
    }

    // Crisp grid lines + outer frame + metric axis ticks
    if (showGrid && cellPx >= 7) {
      ctx.beginPath();
      for (let x = 0; x <= width; x++) {
        const px = left + x * cellPx;
        ctx.moveTo(px, top);
        ctx.lineTo(px, top + mapH);
      }
      for (let y = 0; y <= height; y++) {
        const py = top + y * cellPx;
        ctx.moveTo(left, py);
        ctx.lineTo(left + mapW, py);
      }
      ctx.strokeStyle = darkTheme ? 'rgba(12,18,26,0.35)' : 'rgba(24,44,40,0.18)';
      ctx.lineWidth = 0.8;
      ctx.stroke();
    }

    ctx.strokeStyle = darkTheme ? 'rgba(148,163,184,0.35)' : 'rgba(24,44,40,0.35)';
    ctx.lineWidth = 1.2;
    ctx.strokeRect(left, top, mapW, mapH);

    // Axis metric labels
    const tickInterval = width > 50 ? 10 : width > 28 ? 8 : 4;
    ctx.font = '10px "IBM Plex Mono", ui-monospace, monospace';
    ctx.fillStyle = darkTheme ? '#64748b' : '#526861';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let x = 0; x <= width; x += tickInterval) {
      ctx.fillText(`${+(x * cell_size_m).toFixed(1)}m`, left + x * cellPx, top + mapH + 6);
    }
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let y = 0; y <= height; y += tickInterval) {
      ctx.fillText(`${+(y * cell_size_m).toFixed(1)}m`, left - 7, top + y * cellPx);
    }

    // Sensor footprints (recent completed flash + scheduled/active scans)
    if (showFootprints) {
      // Recently completed capture flashes
      for (const {task, age} of state.recentCompleted) {
        const agent = replay.agentMap.get(task.agent_id);
        const [fx, fy, fw, fh] = task.footprint;
        const [px, py] = pt([fx, fy]);
        const alpha = Math.max(0, 1 - age / 1.2);
        const col = agent.style.rgb;
        ctx.save();
        ctx.fillStyle = rgbCss(col, 0.22 * alpha);
        ctx.fillRect(px, py, fw * cellPx, fh * cellPx);
        ctx.strokeStyle = rgbCss(col, 0.95 * alpha);
        ctx.lineWidth = 2.4;
        ctx.strokeRect(px + 1, py + 1, fw * cellPx - 2, fh * cellPx - 2);
        ctx.restore();
      }

      // Active scheduled footprints
      for (const as of state.agentStates) {
        const task = as.activeTask;
        if (!task) continue;
        const [fx, fy, fw, fh] = task.footprint;
        const [px, py] = pt([fx, fy]);
        const bw = fw * cellPx, bh = fh * cellPx;
        const col = as.agent.style.rgb;
        const measuring = as.stage === 'measure';
        ctx.save();
        ctx.fillStyle = rgbCss(col, measuring ? 0.16 : 0.06);
        ctx.fillRect(px, py, bw, bh);
        ctx.strokeStyle = rgbCss(col, measuring ? 0.95 : 0.6);
        ctx.lineWidth = measuring ? 2.2 : 1.5;
        ctx.setLineDash(measuring ? [] : [6, 4]);
        ctx.strokeRect(px + 1, py + 1, bw - 2, bh - 2);

        // Animated scan sweep line when measuring
        if (measuring) {
          ctx.setLineDash([]);
          const sweep = (Math.sin(animTime * 4.2 + as.agent.index * 1.7) * 0.5 + 0.5);
          const sy = py + sweep * bh;
          const grad = ctx.createLinearGradient(px, sy - 10, px, sy + 10);
          grad.addColorStop(0, rgbCss(col, 0));
          grad.addColorStop(0.5, rgbCss(col, 0.55));
          grad.addColorStop(1, rgbCss(col, 0));
          ctx.fillStyle = grad;
          ctx.fillRect(px, Math.max(py, sy - 10), bw, Math.min(20, py + bh - Math.max(py, sy - 10)));
        }

        // Corner brackets for crisp tactical look
        ctx.setLineDash([]);
        ctx.strokeStyle = rgbCss(col, 0.95);
        ctx.lineWidth = 2;
        const corner = Math.min(8, bw * 0.25, bh * 0.25);
        for (const [cx, cy, dx, dy] of [
          [px, py, 1, 1], [px + bw, py, -1, 1],
          [px, py + bh, 1, -1], [px + bw, py + bh, -1, -1],
        ]) {
          ctx.beginPath();
          ctx.moveTo(cx + dx * corner, cy);
          ctx.lineTo(cx, cy);
          ctx.lineTo(cx, cy + dy * corner);
          ctx.stroke();
        }
        ctx.restore();
      }
    }

    // Flight trails, planned vectors, and robot silhouettes
    for (const as of state.agentStates) {
      const col = as.agent.style.rgb;
      const hex = as.agent.style.hex;
      const [ax, ay] = pt(as.xy);

      // Trail with smooth opacity ramp
      if (showTrails && as.trail.length > 1) {
        ctx.save();
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        // Outer dark halo for readability over bright terrain
        ctx.beginPath();
        as.trail.forEach((p, idx) => {
          const [tx, ty] = pt(p.xy);
          if (idx === 0) ctx.moveTo(tx, ty);
          else ctx.lineTo(tx, ty);
        });
        ctx.strokeStyle = darkTheme ? 'rgba(8,14,20,0.68)' : 'rgba(20,34,30,0.35)';
        ctx.lineWidth = 4.6;
        ctx.stroke();
        ctx.strokeStyle = rgbCss(col, 0.85);
        ctx.lineWidth = 2.2;
        ctx.stroke();

        // Start marker
        const [sx, sy] = pt(as.trail[0].xy);
        ctx.fillStyle = darkTheme ? '#0f172a' : '#ffffff';
        ctx.strokeStyle = hex;
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.arc(sx, sy, 3.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.restore();
      }

      // Planned destination vector
      if (showPlans && as.activeTask) {
        const [tx, ty] = pt(as.activeTask.xy);
        const dist = Math.hypot(tx - ax, ty - ay);
        if (dist > 10) {
          ctx.save();
          const ang = Math.atan2(ty - ay, tx - ax);
          ctx.strokeStyle = rgbCss(col, 0.85);
          ctx.lineWidth = 1.8;
          ctx.setLineDash([5, 4]);
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(tx, ty);
          ctx.stroke();
          ctx.setLineDash([]);
          // Arrowhead
          ctx.fillStyle = hex;
          ctx.beginPath();
          ctx.moveTo(tx, ty);
          ctx.lineTo(tx - 9 * Math.cos(ang - 0.42), ty - 9 * Math.sin(ang - 0.42));
          ctx.lineTo(tx - 9 * Math.cos(ang + 0.42), ty - 9 * Math.sin(ang + 0.42));
          ctx.closePath();
          ctx.fill();
          ctx.restore();
        }
      }

      // Robot silhouette
      drawAgentIcon2D(ctx, ax, ay, as, animTime, darkTheme);
    }

    // Hover cell highlight
    if (this.hoverCell) {
      const {x, y} = this.hoverCell;
      if (x >= 0 && y >= 0 && x < width && y < height) {
        ctx.save();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.strokeRect(left + x * cellPx + 0.5, top + y * cellPx + 0.5, cellPx - 1, cellPx - 1);
        ctx.restore();
      }
    }

    // Split-screen curtain divider & floating badges
    if (isSplit) {
      const clampedX = Math.max(left, Math.min(left + mapW, splitScreenX));
      ctx.save();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.shadowColor = 'rgba(0,0,0,0.6)';
      ctx.shadowBlur = 8;
      ctx.beginPath();
      ctx.moveTo(clampedX, top - 8);
      ctx.lineTo(clampedX, top + mapH + 8);
      ctx.stroke();

      // Handle knob
      const midY = top + mapH / 2;
      ctx.fillStyle = '#0f172a';
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(clampedX, midY, 13, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#ffffff';
      ctx.font = '700 11px system-ui';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('⇄', clampedX, midY + 0.5);

      // Side tags
      drawPill(ctx, left + 8, top + 8, 'ESTYMACJA', '#0f172ad9', '#38bdf8', 'left');
      drawPill(ctx, left + mapW - 8, top + 8, 'REFERENCJA', '#0f172ad9', '#34d399', 'right');
      ctx.restore();
    }

    return this._lastLayout;
  }
}

function drawAgentIcon2D(ctx, x, y, as, animTime, darkTheme) {
  const {agent, stage, heading, altitude} = as;
  const col = agent.style.rgb;
  const hex = agent.style.hex;

  ctx.save();
  ctx.translate(x, y);

  // Measuring pulse ring
  if (stage === 'measure') {
    const pulse = (animTime * 1.4) % 1;
    ctx.strokeStyle = rgbCss(col, (1 - pulse) * 0.75);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(0, 0, 12 + pulse * 14, 0, Math.PI * 2);
    ctx.stroke();
  }

  ctx.rotate(heading);

  if (agent.kind === 'rover') {
    // 6-wheel rover silhouette
    ctx.fillStyle = '#0f172a';
    ctx.strokeStyle = hex;
    ctx.lineWidth = 1.8;
    // Wheels
    for (const wx of [-7, 0, 7]) {
      ctx.fillRect(wx - 2.5, -9, 5, 3);
      ctx.fillRect(wx - 2.5, 6, 5, 3);
    }
    // Chassis
    ctx.fillStyle = darkTheme ? '#1e293b' : '#f8fafc';
    ctx.beginPath();
    ctx.roundRect(-9, -6, 18, 12, 3);
    ctx.fill();
    ctx.stroke();
    // LiDAR turret dot
    ctx.fillStyle = hex;
    ctx.beginPath();
    ctx.arc(2, 0, 3.2, 0, Math.PI * 2);
    ctx.fill();
  } else {
    // Quadcopter X500 silhouette
    const arm = 9.5;
    ctx.strokeStyle = '#0b121b';
    ctx.lineWidth = 4.2;
    ctx.beginPath();
    ctx.moveTo(-arm, -arm); ctx.lineTo(arm, arm);
    ctx.moveTo(-arm, arm); ctx.lineTo(arm, -arm);
    ctx.stroke();
    ctx.strokeStyle = hex;
    ctx.lineWidth = 2;
    ctx.stroke();

    // 4 spinning rotor discs
    const spin = animTime * 16;
    for (const [rx, ry] of [[-arm, -arm], [arm, -arm], [arm, arm], [-arm, arm]]) {
      ctx.fillStyle = rgbCss(col, 0.25);
      ctx.strokeStyle = rgbCss(col, 0.85);
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.arc(rx, ry, 5.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      // Spinning blade highlight
      ctx.strokeStyle = '#ffffffcc';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(rx - 4 * Math.cos(spin), ry - 4 * Math.sin(spin));
      ctx.lineTo(rx + 4 * Math.cos(spin), ry + 4 * Math.sin(spin));
      ctx.stroke();
    }

    // Center hub + forward heading chevron
    ctx.fillStyle = '#0f172a';
    ctx.strokeStyle = hex;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.arc(0, 0, 5.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = hex;
    ctx.beginPath();
    ctx.arc(0, 0, 2.2, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  // Crisp floating label pill beneath robot
  const altTxt = agent.kind === 'drone' ? ` · ${altitude.toFixed(1)}m` : '';
  const tag = `${agent.index + 1} ${agent.label.split(' ')[0]}${altTxt}`;
  ctx.save();
  ctx.font = '600 10px "IBM Plex Mono", ui-monospace, monospace';
  const tw = ctx.measureText(tag).width + 10;
  const bx = x - tw / 2, by = y + 15;
  ctx.fillStyle = darkTheme ? 'rgba(11,17,24,0.88)' : 'rgba(255,255,255,0.92)';
  ctx.strokeStyle = rgbCss(col, 0.75);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(bx, by, tw, 16, 4);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = darkTheme ? '#e2e8f0' : '#0f172a';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(tag, x, by + 8.5);
  ctx.restore();
}

function drawPill(ctx, x, y, text, bg, fg, align) {
  ctx.save();
  ctx.font = '700 10px "IBM Plex Mono", ui-monospace, monospace';
  const w = ctx.measureText(text).width + 14;
  const rx = align === 'right' ? x - w : x;
  ctx.fillStyle = bg;
  ctx.strokeStyle = fg;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(rx, y, w, 20, 5);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = fg;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, rx + w / 2, y + 10.5);
  ctx.restore();
}
