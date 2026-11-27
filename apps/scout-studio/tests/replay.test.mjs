import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync, existsSync} from 'node:fs';
import {readReplay, sampleState} from '../replay.mjs';

test('rejects invalid schema and points generator config users to generated maps', () => {
  const generatorCfg = {type: 'semantic', shares_pct: {rock: 50, gravel: 50}, width: 24, height: 18, seed: 1};
  assert.throws(() => readReplay(generatorCfg), /runs\/scout-map\/map\.json/);
  assert.throws(() => readReplay({schema: 'unknown'}), /scout-replay-v1/);
});

test('interpolates dense x500 trajectory smoothly and extracts Gantt tasks & analytics', () => {
  const path = new URL('../../../runs/scout-semantic-x500/mission.json', import.meta.url);
  if (!existsSync(path)) return;
  const replay = readReplay(JSON.parse(readFileSync(path, 'utf8')));
  assert.equal(replay.denseTrajectory, true);
  assert.equal(replay.hasRealAltitude, true);
  assert.ok(replay.ganttTasks.length > 0);
  assert.ok(replay.analytics.perLayer.get('fused').hasRef);

  const mid = sampleState(replay, 2.5, {smoothMotion: true});
  const d1 = mid.agentStates.find(a => a.agent.id === 'drone-1');
  assert.ok(d1.altitudeIsReal);
  assert.ok(d1.altitude >= 2.0 && d1.altitude <= 6.0);
  assert.ok(d1.trail.length >= 2);
});

test('computes scalar RMSE and within-25cm analytics on elevation replay', () => {
  const path = new URL('../../../runs/scout-visualizer-demo/mission.json', import.meta.url);
  if (!existsSync(path)) return;
  const replay = readReplay(JSON.parse(readFileSync(path, 'utf8')));
  assert.equal(replay.elevationLayerId, 'elevation_m');
  const elev = replay.analytics.perLayer.get('elevation_m');
  assert.equal(elev.hasRef, true);
  const last = elev.series.at(-1);
  assert.ok(last.rmse !== null && last.rmse >= 0);
  assert.ok(last.within25cm !== null && last.within25cm > 0.5);
});

test('loads static terrain map with zero agents cleanly', () => {
  const path = new URL('../../../runs/scout-map/map.json', import.meta.url);
  if (!existsSync(path)) return;
  const replay = readReplay(JSON.parse(readFileSync(path, 'utf8')));
  assert.equal(replay.agents.length, 0);
  assert.equal(replay.elevationLayerId, 'surface');
  const st = sampleState(replay, 0);
  assert.equal(st.agentStates.length, 0);
});
