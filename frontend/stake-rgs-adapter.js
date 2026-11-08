import { DisplayAmount, RGSClient } from 'stake-engine';

const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const safeInteger = (value, minimum = 0) => Number.isSafeInteger(value) && value >= minimum;
const deepFreeze = (value) => {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
};
const cloneJson = (value, field) => {
  let encoded;
  try { encoded = JSON.stringify(value); } catch (_) { throw new Error(field + ' is not JSON serializable'); }
  if (typeof encoded !== 'string' || encoded.length > 256 * 1024) throw new Error(field + ' is missing or exceeds 256 KiB');
  return JSON.parse(encoded);
};

export class StakeRgsLifecycleError extends Error {
  constructor(message, code, ambiguous = false) {
    super(message);
    this.name = 'StakeRgsLifecycleError';
    this.code = code;
    this.ambiguous = ambiguous;
  }
}

function validateBalance(balance) {
  if (!object(balance) || !safeInteger(balance.amount)
      || typeof balance.currency !== 'string' || !/^[A-Z0-9]{3,4}$/.test(balance.currency)) {
    throw new Error('Stake RGS balance is malformed');
  }
  return Object.freeze({
    amount: balance.amount,
    currency: balance.currency,
    formatted: DisplayAmount(balance, { trimDecimalForIntegers: true }),
  });
}

function validateRound(round) {
  if (round == null) return null;
  if (!object(round) || typeof round.active !== 'boolean'
      || !safeInteger(round.betID, 0) || typeof round.mode !== 'string' || !round.mode
      || !Object.hasOwn(round, 'state')) {
    throw new Error('Stake RGS round metadata is malformed');
  }
  if (round.payoutMultiplier !== undefined
      && (typeof round.payoutMultiplier !== 'number' || !Number.isFinite(round.payoutMultiplier)
        || round.payoutMultiplier < 0)) {
    throw new Error('Stake RGS round payout multiplier is malformed');
  }
  if (round.amount !== undefined && (typeof round.amount !== 'number' || !Number.isFinite(round.amount) || round.amount < 0)) {
    throw new Error('Stake RGS round amount is malformed');
  }
  if (round.payout !== undefined && (typeof round.payout !== 'number' || !Number.isFinite(round.payout) || round.payout < 0)) {
    throw new Error('Stake RGS round payout is malformed');
  }
  if (round.event !== undefined && typeof round.event !== 'string') {
    throw new Error('Stake RGS round event marker is malformed');
  }
  return Object.freeze({
    betID: round.betID,
    active: round.active,
    mode: round.mode,
    amount: round.amount,
    payout: round.payout,
    payoutMultiplier: round.payoutMultiplier,
    event: round.event,
    state: deepFreeze(cloneJson(round.state, 'Stake RGS round.state')),
  });
}

function validateAuthenticateResponse(response) {
  if (!object(response) || !object(response.balance) || !object(response.config)
      || !object(response.jurisdictionFlags)) {
    throw new Error('Stake RGS Authenticate response is malformed');
  }
  const balance = validateBalance(response.balance);
  const { config, jurisdictionFlags: flags } = response;
  for (const field of ['minBet', 'maxBet', 'stepBet', 'defaultBetLevel']) {
    if (!safeInteger(config[field], 1)) throw new Error('Stake RGS bet configuration is malformed: ' + field);
  }
  if (config.maxBet < config.minBet || config.stepBet <= 0
      || config.defaultBetLevel < config.minBet || config.defaultBetLevel > config.maxBet
      || !Array.isArray(config.betLevels) || config.betLevels.length === 0
      || !config.betLevels.every((level) => safeInteger(level, config.minBet)
        && level <= config.maxBet && level % config.stepBet === 0)
      || !config.betLevels.includes(config.defaultBetLevel)
      || new Set(config.betLevels).size !== config.betLevels.length) {
    throw new Error('Stake RGS bet levels are malformed or inconsistent');
  }
  const booleanFlags = [
    'socialCasino', 'disabledFullscreen', 'disabledTurbo', 'disabledSuperTurbo',
    'disabledAutoplay', 'disabledSlamstop', 'disabledSpacebar', 'disabledBuyFeature',
    'displayNetPosition', 'displayRTP', 'displaySessionTimer',
  ];
  if (booleanFlags.some((field) => typeof flags[field] !== 'boolean')
      || typeof flags.minimumRoundDuration !== 'number'
      || !Number.isFinite(flags.minimumRoundDuration) || flags.minimumRoundDuration < 0) {
    throw new Error('Stake RGS jurisdiction flags are malformed');
  }
  const round = validateRound(response.round);
  return Object.freeze({
    balance,
    config: Object.freeze({
      minBet: config.minBet,
      maxBet: config.maxBet,
      stepBet: config.stepBet,
      defaultBetLevel: config.defaultBetLevel,
      betLevels: Object.freeze([...config.betLevels]),
    }),
    jurisdictionFlags: Object.freeze(Object.fromEntries(
      [...booleanFlags, 'minimumRoundDuration'].map((field) => [field, flags[field]]),
    )),
    round,
  });
}

/**
 * Stake SDK lifecycle boundary. The SDK request shapes are implemented, but
 * financial calls are disabled by default. Enabling them requires a separately
 * reviewed canonical Math/replay/completion verifier and Provider approval.
 * This application does not pass enableFinancialLifecycle or verifier callbacks.
 */
export function createStakeRgsAdapter(url = window.location.href, options = {}) {
  if (!object(options)) throw new TypeError('Stake RGS adapter options must be an object');
  const parsed = new URL(url);
  if (!parsed.searchParams.get('sessionID') || !parsed.searchParams.get('rgs_url')) {
    throw new Error('Stake RGS requires sessionID and rgs_url launch parameters');
  }
  if (parsed.searchParams.get('device') && !['desktop', 'mobile'].includes(parsed.searchParams.get('device'))) {
    throw new Error('Stake SDK device must be desktop or mobile');
  }
  const enableFinancialLifecycle = options.enableFinancialLifecycle === true;
  const verifyRoundState = options.verifyRoundState;
  const verifyRoundCompletion = options.verifyRoundCompletion;
  const verifyAmbiguousPlayOwnership = options.verifyAmbiguousPlayOwnership;
  const verifyEventAcknowledgement = options.verifyEventAcknowledgement;
  if (enableFinancialLifecycle && (typeof verifyRoundState !== 'function'
      || typeof verifyRoundCompletion !== 'function'
      || typeof verifyAmbiguousPlayOwnership !== 'function'
      || typeof verifyEventAcknowledgement !== 'function')) {
    throw new TypeError('financial lifecycle requires trusted round-state, completion, ambiguous-Play ownership and Event-acknowledgement verifiers');
  }

  let client = null;
  let authenticatedResponse = null;
  let lifecycleState = 'UNAUTHENTICATED';
  let activeRound = null;
  let activeRoundVerified = false;
  let lastEvent = null;
  let busy = false;
  let lastError = null;
  let ambiguousStage = null;
  let ambiguousEventValue = null;
  let ambiguousPlayRequest = null;

  const newClient = () => RGSClient({ url: parsed.href });
  const requireEnabled = () => {
    if (!enableFinancialLifecycle) {
      throw new StakeRgsLifecycleError('Financial lifecycle is disabled until canonical Math, replay and Provider approval are verified', 'FINANCIAL_LIFECYCLE_DISABLED');
    }
  };
  const requireReady = () => {
    if (lifecycleState === 'AMBIGUOUS' || lifecycleState.startsWith('AMBIGUOUS_')) {
      throw new StakeRgsLifecycleError('Server state is ambiguous; create a fresh client and Authenticate before any further action', 'REAUTHENTICATION_REQUIRED', true);
    }
    if (!client || !authenticatedResponse) throw new StakeRgsLifecycleError('Authenticate is required', 'NOT_AUTHENTICATED');
  };
  const withExclusiveAction = async (action) => {
    if (busy) throw new StakeRgsLifecycleError('Another Stake RGS lifecycle request is in progress', 'LIFECYCLE_BUSY');
    busy = true;
    try { return await action(); } finally { busy = false; }
  };
  const markAmbiguous = (stage, error, context = {}) => {
    lastError = String(error?.message || error || 'unknown transport failure');
    lifecycleState = 'AMBIGUOUS';
    ambiguousStage = stage;
    ambiguousEventValue = stage === 'EVENT' ? context.eventValue : null;
    ambiguousPlayRequest = stage === 'PLAY' ? { amount: context.amount, mode: context.mode } : null;
    client = null;
    authenticatedResponse = null;
    activeRoundVerified = false;
    throw new StakeRgsLifecycleError(
      stage + ' response is ambiguous; no retry was sent. Create a fresh SDK client and Authenticate to read server state',
      'AMBIGUOUS_' + stage.toUpperCase(), true,
    );
  };
  const applyAuthenticated = async (response) => {
    const validated = validateAuthenticateResponse(response);
    authenticatedResponse = validated;
    activeRound = validated.round?.active ? validated.round : null;
    activeRoundVerified = false;
    lastEvent = null;
    lifecycleState = activeRound ? 'ACTIVE_REQUIRES_REPLAY' : 'AUTHENTICATED_IDLE';
    if (activeRound && enableFinancialLifecycle) {
      let replayProof = null;
      try {
        const result = await verifyRoundState({ round: activeRound, source: 'AUTHENTICATE_RESTORE' });
        if (object(result) && result.verified === true && Object.hasOwn(result, 'lastEvent')
            && (result.lastEvent === null || (typeof result.lastEvent === 'string'
              && result.lastEvent.length > 0 && result.lastEvent.length <= 4096))) {
          replayProof = result;
        }
      } catch (_) {
        replayProof = null;
      }
      activeRoundVerified = replayProof !== null;
      lastEvent = replayProof?.lastEvent ?? null;
      if (activeRoundVerified) {
        if (ambiguousStage === 'ENDROUND') {
          // SDK EndRound has no idempotency key. Even if Authenticate still
          // reports an active round, do not issue a second settlement request
          // without a Provider round-history/settlement reconciliation API.
          lifecycleState = 'AMBIGUOUS_ENDROUND_RECONCILIATION_REQUIRED';
          activeRoundVerified = false;
          lastError = 'EndRound response was ambiguous; active-round readback alone does not authorize a second EndRound';
        } else if (ambiguousStage === 'EVENT') {
          // `Round.event` is only typed as an optional string by SDK 0.1.32;
          // its Provider meaning is undocumented. Only an injected Provider
          // decoder may prove that this exact opaque marker was persisted.
          let acknowledged = false;
          try {
            acknowledged = (await verifyEventAcknowledgement({
              round: activeRound, eventValue: ambiguousEventValue, replay: replayProof,
              source: 'AMBIGUOUS_EVENT_RECONCILIATION',
            })) === true;
          } catch (_) { acknowledged = false; }
          if (acknowledged) {
            lastEvent = ambiguousEventValue;
            lifecycleState = 'ACTIVE_LOCAL_ROUND';
            ambiguousStage = null;
            ambiguousEventValue = null;
            ambiguousPlayRequest = null;
          } else {
            lifecycleState = 'AMBIGUOUS_EVENT_RECONCILIATION_REQUIRED';
            activeRoundVerified = false;
            lastError = 'Event response was ambiguous and trusted Provider acknowledgement verification did not prove the exact submitted marker';
          }
        } else if (ambiguousStage === 'PLAY') {
          // Matching amount/mode does not prove ownership: another tab can
          // submit the same bet. Require a Provider-backed unique correlation.
          let owned = false;
          if (ambiguousPlayRequest && activeRound.mode === ambiguousPlayRequest.mode
              && activeRound.amount === ambiguousPlayRequest.amount) {
            try {
              owned = (await verifyAmbiguousPlayOwnership({
                round: activeRound, request: Object.freeze({ ...ambiguousPlayRequest }),
                replay: replayProof, source: 'AMBIGUOUS_PLAY_RECONCILIATION',
              })) === true;
            } catch (_) { owned = false; }
          }
          if (owned) {
            lifecycleState = 'ACTIVE_LOCAL_ROUND';
            ambiguousStage = null;
            ambiguousEventValue = null;
            ambiguousPlayRequest = null;
          } else {
            lifecycleState = 'AMBIGUOUS_PLAY_RECONCILIATION_REQUIRED';
            activeRoundVerified = false;
            lastError = 'Play response was ambiguous and Provider-backed unique Round ownership was not proven';
          }
        } else {
          lifecycleState = 'ACTIVE_LOCAL_ROUND';
          ambiguousStage = null;
          ambiguousEventValue = null;
          ambiguousPlayRequest = null;
        }
      }
      if (!activeRoundVerified && ambiguousStage) {
        lifecycleState = 'AMBIGUOUS_' + ambiguousStage + '_RECONCILIATION_REQUIRED';
        lastError = 'Active Round replay or Provider reconciliation proof is insufficient after ambiguous ' + ambiguousStage;
      }
    }
    if (!activeRound && ambiguousStage) {
      lifecycleState = 'AMBIGUOUS_' + ambiguousStage + '_RECONCILIATION_REQUIRED';
      lastError = 'Authenticate found no active round after an ambiguous ' + ambiguousStage
        + '; balance/round history is insufficient to prove the prior financial outcome';
    } else if (!ambiguousStage) {
      lastError = null;
    }
    return validated;
  };

  const authenticateFresh = async () => withExclusiveAction(async () => {
    client = newClient();
    authenticatedResponse = null;
    activeRound = null;
    lifecycleState = 'AUTHENTICATING';
    try {
      return applyAuthenticated(await client.Authenticate());
    } catch (error) {
      client = null;
      authenticatedResponse = null;
      activeRound = null;
      lifecycleState = 'AUTHENTICATION_FAILED';
      lastError = String(error?.message || error);
      throw error;
    }
  });

  const reconnect = async () => {
    if (busy) throw new StakeRgsLifecycleError('Cannot reconnect while a lifecycle request is in progress', 'LIFECYCLE_BUSY');
    return authenticateFresh();
  };

  const play = async ({ amount, mode = 'BASE' } = {}) => withExclusiveAction(async () => {
    requireEnabled();
    requireReady();
    if (activeRound || lifecycleState !== 'AUTHENTICATED_IDLE') {
      throw new StakeRgsLifecycleError('An active or unreplayed round must be resolved before Play', 'ACTIVE_ROUND_REQUIRES_REPLAY');
    }
    if (mode !== 'BASE') throw new StakeRgsLifecycleError('Only BASE is admitted by this lifecycle boundary; Buy modes are disabled', 'UNAPPROVED_MODE');
    if (!safeInteger(amount, 1) || amount < authenticatedResponse.config.minBet
        || amount > authenticatedResponse.config.maxBet
        || amount % authenticatedResponse.config.stepBet !== 0
        || !authenticatedResponse.config.betLevels.includes(amount)) {
      throw new StakeRgsLifecycleError('Bet amount is outside authenticated Stake bet levels', 'INVALID_BET_AMOUNT');
    }
    lifecycleState = 'PLAY_PENDING';
    try {
      const response = await client.Play({ amount, mode });
      if (!object(response) || !object(response.balance)) throw new Error('Play response envelope is malformed');
      const balance = validateBalance(response.balance);
      const round = validateRound(response.round);
      if (!round || round.mode !== mode) throw new Error('Play response round does not match requested mode');
      const replayProof = await verifyRoundState({ round, source: 'PLAY_RESPONSE', amount, mode });
      if (!object(replayProof) || replayProof.verified !== true || !Object.hasOwn(replayProof, 'lastEvent')
          || !(replayProof.lastEvent === null || (typeof replayProof.lastEvent === 'string'
            && replayProof.lastEvent.length > 0 && replayProof.lastEvent.length <= 4096))) {
        throw new Error('server Play round.state was not accepted by the trusted replay verifier');
      }
      authenticatedResponse = Object.freeze({ ...authenticatedResponse, balance, round });
      activeRound = round.active ? round : null;
      activeRoundVerified = round.active;
      lifecycleState = round.active ? 'ACTIVE_LOCAL_ROUND' : 'ROUND_COMPLETED';
      lastEvent = replayProof.lastEvent;
      return Object.freeze({ balance, round, lifecycleState });
    } catch (error) {
      // SDK 0.1.32 can clear its local round flag on HTTP errors but cannot tell
      // whether a remote commit happened. Treat every post-dispatch exception
      // as ambiguous; never retry Play on this client.
      markAmbiguous('PLAY', error, { amount, mode });
    }
  });

  const saveEvent = async (eventValue) => withExclusiveAction(async () => {
    requireEnabled();
    requireReady();
    if (!activeRound || !activeRoundVerified || !['ACTIVE_LOCAL_ROUND'].includes(lifecycleState)) {
      throw new StakeRgsLifecycleError('Event is permitted only for a locally started and replay-verified active round', 'NO_VERIFIED_ACTIVE_ROUND');
    }
    if (typeof eventValue !== 'string' || eventValue.length === 0 || eventValue.length > 4096) {
      throw new StakeRgsLifecycleError('Event must be a non-empty opaque string of at most 4096 characters', 'INVALID_EVENT');
    }
    if (eventValue === lastEvent) {
      throw new StakeRgsLifecycleError('Event marker is already the server-confirmed last event; duplicate Event is blocked', 'DUPLICATE_EVENT_MARKER');
    }
    try {
      const response = await client.Event(eventValue);
      if (!object(response) || response.event !== eventValue) throw new Error('RGS Event acknowledgement differs from submitted marker');
      lastEvent = response.event;
      return Object.freeze({ event: lastEvent, lifecycleState });
    } catch (error) {
      markAmbiguous('EVENT', error, { eventValue });
    }
  });

  const endRound = async (completion) => withExclusiveAction(async () => {
    requireEnabled();
    requireReady();
    if (!activeRound || !activeRoundVerified || lifecycleState !== 'ACTIVE_LOCAL_ROUND') {
      throw new StakeRgsLifecycleError('EndRound requires a locally started active round; restored rounds require canonical replay first', 'NO_VERIFIED_ACTIVE_ROUND');
    }
    let verified = false;
    try { verified = await verifyRoundCompletion({ round: activeRound, completion, lastEvent }); }
    catch (error) { throw new StakeRgsLifecycleError('Round completion verifier rejected: ' + String(error?.message || error), 'COMPLETION_NOT_VERIFIED'); }
    if (verified !== true) throw new StakeRgsLifecycleError('Round completion is not verified against the final Outcome, Feature Trace, Presentation and payout', 'COMPLETION_NOT_VERIFIED');
    lifecycleState = 'END_ROUND_PENDING';
    try {
      const response = await client.EndRound();
      if (!object(response) || !object(response.balance)) throw new Error('EndRound response envelope is malformed');
      const balance = validateBalance(response.balance);
      authenticatedResponse = Object.freeze({ ...authenticatedResponse, balance, round: null });
      activeRound = null;
      activeRoundVerified = false;
      lifecycleState = 'ROUND_SETTLED';
      return Object.freeze({ balance, lifecycleState });
    } catch (error) {
      markAmbiguous('ENDROUND', error);
    }
  });

  return Object.freeze({
    authenticate: authenticateFresh,
    reconnect,
    play,
    event: saveEvent,
    endRound,
    get authenticated() { return authenticatedResponse !== null; },
    get hasActiveRound() { return Boolean(activeRound); },
    get lifecycleState() { return lifecycleState; },
    get lastEvent() { return lastEvent; },
    get lastError() { return lastError; },
    get ambiguousStage() { return ambiguousStage; },
    get serverStateKnown() { return authenticatedResponse !== null; },
    get session() { return authenticatedResponse; },
    get financialLifecycleEnabled() { return enableFinancialLifecycle; },
  });
}