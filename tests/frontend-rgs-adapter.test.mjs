import test from 'node:test';
import assert from 'node:assert/strict';
import { createStakeRgsAdapter } from '../frontend/stake-rgs-adapter.js';

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

const authenticatePayload = (overrides = {}) => ({
  balance: { amount: 12500000, currency: 'USD' },
  config: {
    minBet: 1000000,
    maxBet: 5000000,
    stepBet: 1000000,
    defaultBetLevel: 1000000,
    betLevels: [1000000, 2000000, 3000000, 4000000, 5000000],
    jurisdiction,
  },
  round: null,
  ...overrides,
});

async function withMockedRgs(response, callback, status = 200) {
  const previousFetch = globalThis.fetch;
  const previousWindow = globalThis.window;
  const requests = [];
  const events = [];
  globalThis.window = { dispatchEvent: (event) => events.push(event) };
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), options });
    return { status, json: async () => response };
  };
  try {
    await callback({ requests, events });
  } finally {
    globalThis.fetch = previousFetch;
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
}

const launchUrl = 'https://game.example/index.html?sessionID=session-abc&rgs_url=rgs.example&lang=ja&device=mobile';

test('Stake SDK Authenticate validates and exposes a read-only session snapshot', async () => {
  await withMockedRgs(authenticatePayload(), async ({ requests, events }) => {
    const adapter = createStakeRgsAdapter(launchUrl);
    assert.equal(adapter.authenticated, false);
    const auth = await adapter.authenticate();
    assert.equal(adapter.authenticated, true);
    assert.equal(adapter.hasActiveRound, false);
    assert.deepEqual(requests.map((r) => r.url), ['https://rgs.example/wallet/authenticate']);
    assert.deepEqual(JSON.parse(requests[0].options.body), { sessionID: 'session-abc', language: 'ja' });
    assert.equal(auth.balance.amount, 12500000);
    assert.equal(auth.balance.currency, 'USD');
    assert.equal(auth.balance.formatted, '$12.50');
    assert.deepEqual(auth.config.betLevels, [1000000, 2000000, 3000000, 4000000, 5000000]);
    assert.equal(auth.jurisdictionFlags.disabledBuyFeature, true);
    assert.equal(auth.round, null);
    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'balanceUpdate');
    assert.equal('Play' in adapter, false);
    assert.equal('EndRound' in adapter, false);
    assert.equal('Event' in adapter, false);
  });
});

test('Stake SDK Authenticate preserves an active round without settling it', async () => {
  const state = [{ index: 0, type: 'reveal', board: [] }];
  await withMockedRgs(authenticatePayload({ round: {
    betID: 712, active: true, mode: 'BASE', payoutMultiplier: 2.5, state,
  } }), async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl);
    const auth = await adapter.authenticate();
    assert.equal(adapter.hasActiveRound, true);
    assert.equal(auth.round.betID, 712);
    assert.equal(auth.round.active, true);
    assert.equal(auth.round.payoutMultiplier, 2.5);
    assert.deepEqual(auth.round.state, state);
    assert.equal(requests.length, 1);
    assert.equal(requests.some((r) => r.url.endsWith('/wallet/play') || r.url.endsWith('/wallet/end-round')), false);
  });
});

test('adapter rejects missing provider launch parameters before any network request', async () => {
  await withMockedRgs(authenticatePayload(), async ({ requests }) => {
    assert.throws(() => createStakeRgsAdapter('https://game.example/index.html?sessionID=only'), /sessionID and rgs_url/);
    assert.equal(requests.length, 0);
  });
});

test('adapter rejects malformed monetary and jurisdiction fields without coercion', async () => {
  for (const payload of [
    authenticatePayload({ balance: { amount: true, currency: 'USD' } }),
    authenticatePayload({ config: { ...authenticatePayload().config, betLevels: [1000000, 1000000] } }),
    authenticatePayload({ config: { ...authenticatePayload().config, jurisdiction: { ...jurisdiction, disabledBuyFeature: 1 } } }),
  ]) {
    await withMockedRgs(payload, async () => {
      const adapter = createStakeRgsAdapter(launchUrl);
      await assert.rejects(adapter.authenticate(), /malformed|inconsistent/);
    });
  }
});

test('adapter propagates failed Stake Authenticate responses', async () => {
  await withMockedRgs({ error: 'ERR_IS' }, async () => {
    const adapter = createStakeRgsAdapter(launchUrl);
    await assert.rejects(adapter.authenticate());
    assert.equal(adapter.authenticated, false);
  }, 400);
});

test('adapter accepts provider-defined bet level order and normalizes an omitted round', async () => {
  const payload = authenticatePayload();
  payload.config.betLevels = [3000000, 1000000, 2000000, 5000000, 4000000];
  delete payload.round;
  await withMockedRgs(payload, async () => {
    const adapter = createStakeRgsAdapter(launchUrl);
    const auth = await adapter.authenticate();
    assert.equal(auth.round, null);
    assert.deepEqual(auth.config.betLevels, payload.config.betLevels);
  });
});
