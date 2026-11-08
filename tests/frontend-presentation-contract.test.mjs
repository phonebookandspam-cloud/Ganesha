import test from 'node:test';
import assert from 'node:assert/strict';
import {
  deriveExpandedWildDisplayBoard,
  GANESHA_WILD_SYMBOL,
} from '../frontend/presentation-contract.js';

const rawBoard = [
  ['A', 'K', 'MODAK'],
  ['MOUSE', 'A', 'K'],
  [GANESHA_WILD_SYMBOL, 'A', 'MODAK'],
  ['K', 'CHAKRA', 'A'],
  ['SCATTER_LOTUS', 'MOUSE', GANESHA_WILD_SYMBOL],
];

test('Wild display board is derived from exact WILD_GANESHA raw reels only', () => {
  const display = deriveExpandedWildDisplayBoard(rawBoard, [2, 4]);
  assert.deepEqual(display[2], [GANESHA_WILD_SYMBOL, GANESHA_WILD_SYMBOL, GANESHA_WILD_SYMBOL]);
  assert.deepEqual(display[4], [GANESHA_WILD_SYMBOL, GANESHA_WILD_SYMBOL, GANESHA_WILD_SYMBOL]);
  assert.deepEqual(display[0], rawBoard[0]);
  assert.deepEqual(display[1], rawBoard[1]);
  assert.deepEqual(display[3], rawBoard[3]);
  assert.notEqual(display, rawBoard);
});

test('No expansion preserves the raw board without alias substitution', () => {
  const display = deriveExpandedWildDisplayBoard(rawBoard, []);
  assert.deepEqual(display, rawBoard);
  assert.notEqual(display[2], rawBoard[2]);
});

test('Expanded reel without original WILD_GANESHA is rejected', () => {
  assert.throws(() => deriveExpandedWildDisplayBoard(rawBoard, [0]), /original WILD_GANESHA/);
});

test('Duplicate, fractional and out-of-range reel indices are rejected', () => {
  assert.throws(() => deriveExpandedWildDisplayBoard(rawBoard, [2, 2]), /unique integers/);
  assert.throws(() => deriveExpandedWildDisplayBoard(rawBoard, [2.5]), /unique integers/);
  assert.throws(() => deriveExpandedWildDisplayBoard(rawBoard, [5]), /unique integers/);
});

test('Legacy WILD alias and malformed raw boards are rejected', () => {
  const legacy = rawBoard.map((reel) => [...reel]);
  legacy[2][0] = 'WILD';
  assert.throws(() => deriveExpandedWildDisplayBoard(legacy, [2]), /original WILD_GANESHA/);
  assert.throws(() => deriveExpandedWildDisplayBoard(rawBoard.slice(1), []), /5x3 matrix/);
});
