import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createTimeline, readReplay} from '../replay.mjs';

test('opening a generator config points to the generated map', () => {
  const path = new URL('../../../configs/scout/map.json', import.meta.url);
  assert.throws(() => readReplay(JSON.parse(readFileSync(path, 'utf8'))), /runs\/scout-map\/map\.json/);
  assert.throws(() => readReplay({schema: 'other'}), /oczekiwano scout-replay-v1/);
});

test('empty ticks hold the latest map and active tasks, with no repeated events', () => {
  const first = {tick: 0, layers: {a: [null]}, completed: [], scheduled: ['planned']};
  const capture = {tick: 3, layers: {a: ['soil']}, completed: ['capture'], scheduled: [], messages: ['result']};
  const finish = {tick: 5, layers: {a: ['soil']}, completed: [], scheduled: []};
  const timeline = createTimeline([first, capture, finish]);
  assert.equal(timeline.length, 6);
  assert.deepEqual(Array.from({length: timeline.length}, (_, step) => timeline.at(step).frame.tick), [0, 1, 2, 3, 4, 5]);
  assert.deepEqual(timeline.at(2), {frame: {...first, tick: 2, messages: undefined}, eventIndex: 0});
  assert.deepEqual(timeline.at(3), {frame: capture, eventIndex: 1});
  assert.deepEqual(timeline.at(4), {frame: {...capture, tick: 4, completed: [], messages: []}, eventIndex: 1});
});

test('fractional timestamps preserve the original event order', () => {
  const frames = [{tick: 0}, {tick: 1.5}, {tick: 4}];
  const timeline = createTimeline(frames);
  assert.equal(timeline.length, 3);
  assert.equal(timeline.tickAt(1), 1.5);
  assert.deepEqual(timeline.at(2), {frame: frames[2], eventIndex: 2});
});
