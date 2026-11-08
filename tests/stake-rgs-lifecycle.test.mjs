import test from 'node:test';
import assert from 'node:assert/strict';
import { createStakeRgsAdapter, StakeRgsLifecycleError } from '../frontend/stake-rgs-adapter.js';

const jurisdiction = {
  socialCasino: false, disabledFullscreen: false, disabledTurbo: false,
  disabledSuperTurbo: false, disabledAutoplay: false, disabledSlamstop: false,
  disabledSpacebar: false, disabledBuyFeature: true, displayNetPosition: true,
  displayRTP: true, displaySessionTimer: true, minimumRoundDuration: 0,
};
const auth = (round = null) => ({
  balance: { amount: 1_000_000, currency: 'USD' },
  config: { minBet: 100_000, maxBet: 1_000_000, stepBet: 100_000,
    defaultBetLevel: 100_000, betLevels: [100_000, 200_000, 500_000, 1_000_000], jurisdiction },
  round,
});
const activeRound = (betID = 7, state = [{ sequence: 1, event: 'BASE_OUTCOME' }]) => ({
  betID, active: true, mode: 'BASE', amount: 100_000, payout: 0,
  payoutMultiplier: 0, event: 'BASE_OUTCOME', state,
});
const closedRound = (betID = 8) => ({
  betID, active: false, mode: 'BASE', amount: 100_000, payout: 0,
  payoutMultiplier: 0, event: 'ROUND_COMPLETE', state: [],
});
const response = (body, status = 200) => ({ status, json: async () => body });
const launchUrl = 'https://game.example/index.html?sessionID=lifecycle-session&rgs_url=rgs.example&lang=ja&device=desktop';

async function withSdk(responses, callback) {
  const previous = { fetch: globalThis.fetch, window: globalThis.window,
    setInterval: globalThis.setInterval, clearInterval: globalThis.clearInterval };
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
    if (typeof next === 'function') return next();
    if (!next) throw new Error('unexpected SDK request');
    return next;
  };
  try { await callback({ requests, emitted, queue }); }
  finally {
    globalThis.fetch = previous.fetch;
    globalThis.setInterval = previous.setInterval;
    globalThis.clearInterval = previous.clearInterval;
    if (previous.window === undefined) delete globalThis.window;
    else globalThis.window = previous.window;
  }
}

const financialOptions = {
  enableFinancialLifecycle: true,
  verifyRoundState: async ({ round }) => ({
    verified: Array.isArray(round.state) && round.state.length > 0,
    lastEvent: Array.isArray(round.state) && round.state.length > 0
      ? round.state[round.state.length - 1].event : null,
  }),
  verifyAmbiguousPlayOwnership: async ({ round, request }) => round.mode === request.mode
    && round.amount === request.amount && Array.isArray(round.state) && round.state.length > 0,
  verifyEventAcknowledgement: async ({ round, eventValue }) => Array.isArray(round.state)
    && round.state.some((item) => item.event === eventValue),
  verifyRoundCompletion: async ({ completion, lastEvent }) => completion?.status === 'COMPLETED'
    && completion?.total_payout_milli === 1_500 && lastEvent === completion.final_event,
};

test('financial lifecycle cannot be enabled without Provider ownership and Event acknowledgement verifiers', () => {
  assert.throws(() => createStakeRgsAdapter(launchUrl, {
    enableFinancialLifecycle: true,
    verifyRoundState: async () => ({ verified: true, lastEvent: null }),
    verifyRoundCompletion: async () => true,
  }), /ambiguous-Play ownership and Event-acknowledgement verifiers/);
});

test('financial SDK lifecycle is fail-closed by default and sends no Play, Event or EndRound', async () => {
  await withSdk([response(auth())], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl);
    await adapter.authenticate();
    assert.equal(adapter.financialLifecycleEnabled, false);
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }),
      (error) => error instanceof StakeRgsLifecycleError && error.code === 'FINANCIAL_LIFECYCLE_DISABLED');
    await assert.rejects(adapter.event('progress-1'), /Financial lifecycle is disabled/);
    await assert.rejects(adapter.endRound({}), /Financial lifecycle is disabled/);
    assert.deepEqual(requests.map((item) => new URL(item.url).pathname), ['/wallet/authenticate']);
  });
});

test('verified BASE lifecycle sends exact SDK Play, opaque Event marker and EndRound requests', async () => {
  const marker = 'ganesha-presentation:v1:sequence:90:hash:0123456789abcdef';
  await withSdk([
    response(auth()),
    response({ balance: { amount: 900_000, currency: 'USD' }, round: activeRound() }),
    response({ event: marker }),
    response({ balance: { amount: 1_001_500, currency: 'USD' } }),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, financialOptions);
    await adapter.authenticate();
    const played = await adapter.play({ amount: 100_000, mode: 'BASE' });
    assert.equal(played.lifecycleState, 'ACTIVE_LOCAL_ROUND');
    assert.equal(adapter.hasActiveRound, true);
    assert.equal((await adapter.event(marker)).event, marker);
    const completion = { status: 'COMPLETED', total_payout_milli: 1_500, final_event: marker };
    const settled = await adapter.endRound(completion);
    assert.equal(settled.lifecycleState, 'ROUND_SETTLED');
    assert.equal(settled.balance.amount, 1_001_500);
    assert.equal(adapter.hasActiveRound, false);
    assert.deepEqual(requests.map((item) => new URL(item.url).pathname), [
      '/wallet/authenticate', '/wallet/play', '/bet/event', '/wallet/end-round',
    ]);
    assert.deepEqual(requests.map((item) => JSON.parse(item.options.body)), [
      { sessionID: 'lifecycle-session', language: 'ja' },
      { sessionID: 'lifecycle-session', mode: 'BASE', amount: 100_000 },
      { sessionID: 'lifecycle-session', event: marker },
      { sessionID: 'lifecycle-session' },
    ]);
  });
});

test('Buy modes and invalid bets are rejected before any wager request', async () => {
  await withSdk([response(auth())], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, financialOptions);
    await adapter.authenticate();
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'EPIC_BUY' }), /Only BASE/);
    await assert.rejects(adapter.play({ amount: 150_000, mode: 'BASE' }), /Bet amount/);
    await assert.rejects(adapter.play({ amount: 1_100_000, mode: 'BASE' }), /Bet amount/);
    assert.equal(requests.length, 1);
  });
});

test('Authenticate rejects bet levels that the pinned SDK would reject before fetch', async () => {
  const incompatible = auth();
  incompatible.config.minBet = 150_000;
  incompatible.config.maxBet = 250_000;
  incompatible.config.stepBet = 100_000;
  incompatible.config.defaultBetLevel = 150_000;
  incompatible.config.betLevels = [150_000, 250_000];
  await withSdk([response(incompatible)], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, financialOptions);
    await assert.rejects(adapter.authenticate(), /bet levels are malformed or inconsistent/);
    assert.equal(requests.length, 1);
    assert.equal(new URL(requests[0].url).pathname, '/wallet/authenticate');
  });
});

test('restored active round requires verifier approval before Event or EndRound', async () => {
  await withSdk([response(auth(activeRound()))], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, {
      ...financialOptions,
      verifyRoundState: async () => false,
    });
    const restored = await adapter.authenticate();
    assert.equal(restored.round.active, true);
    assert.equal(adapter.lifecycleState, 'ACTIVE_REQUIRES_REPLAY');
    assert.equal(Object.isFrozen(adapter.session.round.state), true);
    assert.equal(Object.isFrozen(adapter.session.round.state[0]), true);
    await assert.rejects(adapter.event('cannot-replay-yet'), /Financial lifecycle|verified active round/);
    await assert.rejects(adapter.endRound({ status: 'COMPLETED', total_payout_milli: 0 }), /restored rounds require canonical replay/);
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }), /active or unreplayed round/);
    assert.equal(requests.length, 1);
  });
});

test('ambiguous Play response is never retried; fresh client Authenticate discovers active round', async () => {
  await withSdk([
    response(auth()),
    new Error('socket closed after Play dispatch'),
    response(auth(activeRound(21))),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, {
      ...financialOptions,
      verifyRoundState: async ({ source }) => ({ verified: source === 'PLAY_RESPONSE', lastEvent: 'BASE_OUTCOME' }),
    });
    await adapter.authenticate();
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }),
      (error) => error.code === 'AMBIGUOUS_PLAY' && error.ambiguous === true);
    assert.equal(adapter.lifecycleState, 'AMBIGUOUS');
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }),
      (error) => error.code === 'REAUTHENTICATION_REQUIRED');
    const restored = await adapter.reconnect();
    assert.equal(restored.round.betID, 21);
    assert.equal(adapter.lifecycleState, 'AMBIGUOUS_PLAY_RECONCILIATION_REQUIRED');
    assert.deepEqual(requests.map((item) => new URL(item.url).pathname), [
      '/wallet/authenticate', '/wallet/play', '/wallet/authenticate',
    ]);
  });
});

test('ambiguous Play does not adopt an unrelated active round with a different bet amount', async () => {
  await withSdk([
    response(auth()),
    new Error('Play response lost after dispatch'),
    response(auth({ ...activeRound(22), amount: 200_000 })),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, {
      ...financialOptions,
      verifyRoundState: async () => ({ verified: true, lastEvent: 'BASE_OUTCOME' }),
    });
    await adapter.authenticate();
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }),
      (error) => error.code === 'AMBIGUOUS_PLAY');
    await adapter.reconnect();
    assert.equal(adapter.lifecycleState, 'AMBIGUOUS_PLAY_RECONCILIATION_REQUIRED');
    assert.equal(adapter.ambiguousStage, 'PLAY');
    await assert.rejects(adapter.event('feature-progress'),
      (error) => error.code === 'REAUTHENTICATION_REQUIRED');
    await assert.rejects(adapter.endRound({ status: 'COMPLETED' }),
      (error) => error.code === 'REAUTHENTICATION_REQUIRED');
    assert.deepEqual(requests.map((item) => new URL(item.url).pathname), [
      '/wallet/authenticate', '/wallet/play', '/wallet/authenticate',
    ]);
  });
});

test('ambiguous Play with matching amount/mode remains blocked without unique Provider ownership proof', async () => {
  await withSdk([
    response(auth()),
    new Error('Play response lost after dispatch'),
    response(auth({ ...activeRound(29), state: [{ sequence: 1, event: 'BASE_OUTCOME' }] })),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, {
      ...financialOptions,
      verifyAmbiguousPlayOwnership: async () => false,
    });
    await adapter.authenticate();
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }),
      (error) => error.code === 'AMBIGUOUS_PLAY');
    await adapter.reconnect();
    assert.equal(adapter.lifecycleState, 'AMBIGUOUS_PLAY_RECONCILIATION_REQUIRED');
    assert.equal(adapter.ambiguousStage, 'PLAY');
    assert.equal(requests.filter((item) => new URL(item.url).pathname === '/wallet/play').length, 1);
  });
});

test('ambiguous Event acknowledgement requires fresh Authenticate and never resends the event', async () => {
  const marker = 'feature-spin-10';
  await withSdk([
    response(auth()),
    response({ balance: { amount: 900_000, currency: 'USD' }, round: activeRound() }),
    new Error('Event response lost after persistence'),
    response(auth({ ...activeRound(7, [{ sequence: 1, event: 'BASE_OUTCOME' }, { sequence: 2, event: marker }]), event: marker })),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, financialOptions);
    await adapter.authenticate();
    await adapter.play({ amount: 100_000, mode: 'BASE' });
    await assert.rejects(adapter.event(marker), (error) => error.code === 'AMBIGUOUS_EVENT');
    await adapter.reconnect();
    assert.equal(adapter.lifecycleState, 'ACTIVE_LOCAL_ROUND');
    await assert.rejects(adapter.event(marker), (error) => error.code === 'DUPLICATE_EVENT_MARKER');
    assert.deepEqual(requests.map((item) => new URL(item.url).pathname), [
      '/wallet/authenticate', '/wallet/play', '/bet/event', '/wallet/authenticate',
    ]);
  });
});

test('ambiguous Event remains blocked when fresh Authenticate does not confirm the exact marker', async () => {
  const submittedMarker = 'feature-spin-10';
  const priorMarker = 'feature-spin-9';
  await withSdk([
    response(auth()),
    response({ balance: { amount: 900_000, currency: 'USD' }, round: activeRound() }),
    new Error('Event response lost before acknowledgement'),
    response(auth({
      ...activeRound(7, [{ sequence: 1, event: 'BASE_OUTCOME' }, { sequence: 2, event: priorMarker }]),
      event: priorMarker,
    })),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, financialOptions);
    await adapter.authenticate();
    await adapter.play({ amount: 100_000, mode: 'BASE' });
    await assert.rejects(adapter.event(submittedMarker), (error) => error.code === 'AMBIGUOUS_EVENT');
    await adapter.reconnect();
    assert.equal(adapter.lifecycleState, 'AMBIGUOUS_EVENT_RECONCILIATION_REQUIRED');
    assert.equal(adapter.ambiguousStage, 'EVENT');
    await assert.rejects(adapter.event('feature-spin-11'),
      (error) => error.code === 'REAUTHENTICATION_REQUIRED');
    await assert.rejects(adapter.endRound({ status: 'COMPLETED', total_payout_milli: 1_500 }),
      (error) => error.code === 'REAUTHENTICATION_REQUIRED');
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }),
      (error) => error.code === 'REAUTHENTICATION_REQUIRED');
    assert.equal(requests.filter((item) => new URL(item.url).pathname === '/bet/event').length, 1);
    assert.equal(requests.filter((item) => new URL(item.url).pathname === '/wallet/end-round').length, 0);
    assert.equal(requests.filter((item) => new URL(item.url).pathname === '/wallet/play').length, 1);
  });
});

test('round.event string alone cannot resolve an ambiguous Event without trusted state acknowledgement', async () => {
  const marker = 'feature-spin-10';
  await withSdk([
    response(auth()),
    response({ balance: { amount: 900_000, currency: 'USD' }, round: activeRound() }),
    new Error('Event response lost after persistence'),
    response(auth({ ...activeRound(7, [{ sequence: 1, event: 'BASE_OUTCOME' }, { sequence: 2, event: marker }]), event: marker })),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, {
      ...financialOptions,
      verifyEventAcknowledgement: async () => false,
    });
    await adapter.authenticate();
    await adapter.play({ amount: 100_000, mode: 'BASE' });
    await assert.rejects(adapter.event(marker), (error) => error.code === 'AMBIGUOUS_EVENT');
    await adapter.reconnect();
    assert.equal(adapter.lifecycleState, 'AMBIGUOUS_EVENT_RECONCILIATION_REQUIRED');
    assert.equal(adapter.ambiguousStage, 'EVENT');
    assert.equal(requests.filter((item) => new URL(item.url).pathname === '/bet/event').length, 1);
  });
});

test('EndRound response loss is ambiguous and does not cause duplicate settlement', async () => {
  await withSdk([
    response(auth()),
    response({ balance: { amount: 900_000, currency: 'USD' }, round: activeRound() }),
    response({ event: 'final-event' }),
    new Error('EndRound response lost after settlement'),
    response(auth({ ...closedRound(7), state: [{ sequence: 90, event: 'ROUND_COMPLETE' }] })),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, financialOptions);
    await adapter.authenticate();
    await adapter.play({ amount: 100_000, mode: 'BASE' });
    const marker = 'final-event';
    await adapter.event(marker);
    const completion = { status: 'COMPLETED', total_payout_milli: 1_500, final_event: marker };
    await assert.rejects(adapter.endRound(completion), (error) => error.code === 'AMBIGUOUS_ENDROUND');
    await adapter.reconnect();
    assert.equal(adapter.lifecycleState, 'AMBIGUOUS_ENDROUND_RECONCILIATION_REQUIRED');
    assert.equal(adapter.serverStateKnown, true);
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }),
      (error) => error.code === 'REAUTHENTICATION_REQUIRED');
    assert.deepEqual(requests.map((item) => new URL(item.url).pathname), [
      '/wallet/authenticate', '/wallet/play', '/bet/event', '/wallet/end-round', '/wallet/authenticate',
    ]);
  });
});

test('ambiguous EndRound with active readback still blocks a second settlement request', async () => {
  const marker = 'final-event';
  await withSdk([
    response(auth()),
    response({ balance: { amount: 900_000, currency: 'USD' }, round: activeRound() }),
    response({ event: marker }),
    new Error('EndRound response lost after dispatch'),
    response(auth({ ...activeRound(7, [{ sequence: 90, event: 'ROUND_COMPLETE' }]), event: marker })),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, financialOptions);
    await adapter.authenticate();
    await adapter.play({ amount: 100_000, mode: 'BASE' });
    await adapter.event(marker);
    await assert.rejects(adapter.endRound({ status: 'COMPLETED', total_payout_milli: 1_500, final_event: marker }),
      (error) => error.code === 'AMBIGUOUS_ENDROUND');
    await adapter.reconnect();
    assert.equal(adapter.lifecycleState, 'AMBIGUOUS_ENDROUND_RECONCILIATION_REQUIRED');
    await assert.rejects(adapter.endRound({ status: 'COMPLETED', total_payout_milli: 1_500, final_event: marker }),
      (error) => error.code === 'REAUTHENTICATION_REQUIRED');
    assert.equal(requests.filter((item) => new URL(item.url).pathname === '/wallet/end-round').length, 1);
  });
});

test('ambiguous Play followed by no active round remains blocked pending round-history reconciliation', async () => {
  await withSdk([
    response(auth()),
    new Error('Play response lost after dispatch'),
    response(auth(null)),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, financialOptions);
    await adapter.authenticate();
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }),
      (error) => error.code === 'AMBIGUOUS_PLAY');
    await adapter.reconnect();
    assert.equal(adapter.lifecycleState, 'AMBIGUOUS_PLAY_RECONCILIATION_REQUIRED');
    assert.equal(adapter.serverStateKnown, true);
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }),
      (error) => error.code === 'REAUTHENTICATION_REQUIRED');
    assert.deepEqual(requests.map((item) => new URL(item.url).pathname), [
      '/wallet/authenticate', '/wallet/play', '/wallet/authenticate',
    ]);
  });
});

test('completion verifier failure blocks EndRound without contacting the RGS', async () => {
  await withSdk([
    response(auth()),
    response({ balance: { amount: 900_000, currency: 'USD' }, round: activeRound() }),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, {
      ...financialOptions,
      verifyRoundCompletion: async () => false,
    });
    await adapter.authenticate();
    await adapter.play({ amount: 100_000, mode: 'BASE' });
    await assert.rejects(adapter.endRound({ status: 'COMPLETED', total_payout_milli: 999_999 }),
      (error) => error.code === 'COMPLETION_NOT_VERIFIED');
    assert.equal(adapter.lifecycleState, 'ACTIVE_LOCAL_ROUND');
    assert.equal(requests.length, 2);
  });
});

test('concurrent Play attempts are serialized and the second request is rejected', async () => {
  let resolvePlay;
  const pending = new Promise((resolve) => { resolvePlay = resolve; });
  await withSdk([response(auth()), () => pending], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, financialOptions);
    await adapter.authenticate();
    const first = adapter.play({ amount: 100_000, mode: 'BASE' });
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }),
      (error) => error.code === 'LIFECYCLE_BUSY');
    resolvePlay(response({ balance: { amount: 900_000, currency: 'USD' }, round: activeRound() }));
    await first;
    assert.equal(requests.filter((item) => new URL(item.url).pathname === '/wallet/play').length, 1);
  });
});

test('malformed SDK round state after Play is treated as ambiguous, not as a clean failure', async () => {
  await withSdk([
    response(auth()),
    response({ balance: { amount: 900_000, currency: 'USD' }, round: {
      betID: 9, active: true, mode: 'BASE', state: undefined,
    } }),
  ], async ({ requests }) => {
    const adapter = createStakeRgsAdapter(launchUrl, financialOptions);
    await adapter.authenticate();
    await assert.rejects(adapter.play({ amount: 100_000, mode: 'BASE' }),
      (error) => error.code === 'AMBIGUOUS_PLAY');
    assert.equal(adapter.lifecycleState, 'AMBIGUOUS');
    assert.equal(requests.filter((item) => new URL(item.url).pathname === '/wallet/play').length, 1);
  });
});
