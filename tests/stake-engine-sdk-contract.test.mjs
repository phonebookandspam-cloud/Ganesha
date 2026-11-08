import test from 'node:test';
import assert from 'node:assert/strict';
import { RGSClient } from 'stake-engine';

const jurisdiction = {
  socialCasino: false,
  disabledFullscreen: false,
  disabledTurbo: false,
  disabledSuperTurbo: false,
  disabledAutoplay: false,
  disabledSlamstop: false,
  disabledSpacebar: false,
  disabledBuyFeature: true,
  displayNetPosition: true,
  displayRTP: true,
  displaySessionTimer: true,
  minimumRoundDuration: 0,
};

const auth = (round = null) => ({
  balance: { amount: 1_000_000, currency: 'USD' },
  config: {
    minBet: 100_000,
    maxBet: 1_000_000,
    stepBet: 100_000,
    defaultBetLevel: 100_000,
    betLevels: [100_000, 200_000, 500_000, 1_000_000],
    jurisdiction,
  },
  round,
});

const response = (body, status = 200) => ({
  status,
  json: async () => body,
});

async function withSdkEnvironment(responses, callback) {
  const previous = {
    fetch: globalThis.fetch,
    window: globalThis.window,
    setInterval: globalThis.setInterval,
    clearInterval: globalThis.clearInterval,
  };
  const requests = [];
  const emitted = [];
  const queue = [...responses];
  globalThis.window = { dispatchEvent: (event) => emitted.push(event) };
  globalThis.setInterval = () => 1;
  globalThis.clearInterval = () => {};
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), options });
    const next = queue.shift();
    if (next instanceof Error) throw next;
    if (!next) throw new Error('unexpected SDK request');
    return next;
  };
  try {
    await callback({ requests, emitted, queue });
  } finally {
    globalThis.fetch = previous.fetch;
    globalThis.window = previous.window;
    globalThis.setInterval = previous.setInterval;
    globalThis.clearInterval = previous.clearInterval;
  }
}

const launchUrl = 'https://game.example/index.html?sessionID=contract-session&rgs_url=rgs.example&lang=ja&device=desktop';

test('pinned SDK 0.1.32 contract: Authenticate -> Play(active) -> Event -> EndRound', async () => {
  const savedEvent = 'feature-spin-4';
  await withSdkEnvironment([
    response(auth()),
    response({ balance: { amount: 900_000, currency: 'USD' }, round: {
      betID: 77, active: true, mode: 'BASE', state: [{ index: 0, type: 'reveal' }],
    } }),
    response({ event: savedEvent }),
    response({ balance: { amount: 1_250_000, currency: 'USD' } }),
  ], async ({ requests, emitted }) => {
    const client = RGSClient({ url: launchUrl });
    const authenticated = await client.Authenticate();
    assert.equal(authenticated.config.minBet, 100_000);
    const played = await client.Play({ amount: 100_000, mode: 'BASE' });
    assert.equal(played.round.active, true);
    assert.equal(played.round.betID, 77);
    const event = await client.Event(savedEvent);
    assert.equal(event.event, savedEvent);
    const settled = await client.EndRound();
    assert.equal(settled.balance.amount, 1_250_000);

    assert.deepEqual(requests.map((request) => request.url), [
      'https://rgs.example/wallet/authenticate',
      'https://rgs.example/wallet/play',
      'https://rgs.example/bet/event',
      'https://rgs.example/wallet/end-round',
    ]);
    assert.deepEqual(requests.map((request) => JSON.parse(request.options.body)), [
      { sessionID: 'contract-session', language: 'ja' },
      { sessionID: 'contract-session', mode: 'BASE', amount: 100_000 },
      { sessionID: 'contract-session', event: savedEvent },
      { sessionID: 'contract-session' },
    ]);
    assert.deepEqual(emitted.map((event) => event.type), [
      'balanceUpdate', 'roundActive', 'balanceUpdate', 'balanceUpdate', 'roundActive',
    ]);
    assert.deepEqual(emitted.filter((event) => event.type === 'roundActive').map((event) => event.detail.active),
      [true, false]);
  });
});

test('pinned SDK contract: zero-payout Play closes the round without EndRound', async () => {
  await withSdkEnvironment([
    response(auth()),
    response({ balance: { amount: 900_000, currency: 'USD' }, round: {
      betID: 78, active: false, mode: 'BASE', state: [],
    } }),
  ], async ({ requests, emitted }) => {
    const client = RGSClient({ url: launchUrl });
    await client.Authenticate();
    const played = await client.Play({ amount: 100_000, mode: 'BASE' });
    assert.equal(played.round.active, false);
    assert.deepEqual(requests.map((request) => new URL(request.url).pathname), [
      '/wallet/authenticate', '/wallet/play',
    ]);
    assert.deepEqual(emitted.filter((event) => event.type === 'roundActive').map((event) => event.detail.active),
      [true, false]);
  });
});

test('pinned SDK contract: Authenticate restores an active round and blocks another Play', async () => {
  await withSdkEnvironment([response(auth({
    betID: 79, active: true, mode: 'BASE', state: [{ index: 0, type: 'reveal' }],
  }))], async ({ requests, emitted }) => {
    const client = RGSClient({ url: launchUrl });
    const restored = await client.Authenticate();
    assert.equal(restored.round.active, true);
    await assert.rejects(client.Play({ amount: 100_000, mode: 'BASE' }), /round is already active/);
    assert.equal(requests.length, 1);
    assert.deepEqual(emitted.filter((event) => event.type === 'roundActive').map((event) => event.detail.active),
      [true]);
  });
});

test('pinned SDK limitation: a transport failure after Play starts leaves its in-memory round lock active', async () => {
  await withSdkEnvironment([
    response(auth()),
    new Error('simulated response lost after request dispatch'),
  ], async ({ requests }) => {
    const client = RGSClient({ url: launchUrl });
    await client.Authenticate();
    await assert.rejects(client.Play({ amount: 100_000, mode: 'BASE' }), /response lost/);
    await assert.rejects(client.Play({ amount: 100_000, mode: 'BASE' }), /round is already active/);
    assert.equal(requests.length, 2);
    // Never retry a Play after an ambiguous transport failure. A fresh client
    // plus Authenticate/readback is required to determine whether a round exists.
  });
});
