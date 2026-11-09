import { deriveExpandedWildDisplayBoard } from './presentation-contract.js';
import './config.js';

(() => {
  const status = document.getElementById('message');
  const connection = document.getElementById('connection-label');
  const boardElement = document.getElementById('board');
  const readbackElement = document.getElementById('round-readback');
  const roundStatusElement = document.getElementById('round-status');
  const featureProgressElement = document.getElementById('feature-progress');
  const payoutElement = document.getElementById('final-payout');
  const eventCountElement = document.getElementById('event-count');
  const eventHistoryElement = document.getElementById('event-history');
  const restoreRoundInput = document.getElementById('restore-round-id');
  const restoreRoundButton = document.getElementById('restore-round-button');
  const recoverRoundButton = document.getElementById('recover-round-button');
  const restoreRoundMessage = document.getElementById('restore-round-message');
  const demoButton = document.getElementById('demo-spin-button');
  const engineFixtureButton = document.getElementById('engine-fixture-button');
  const fixturePanel = document.getElementById('fixture-readback');
  const fixtureStatus = document.getElementById('fixture-status');
  const fixtureFeatureProgress = document.getElementById('fixture-feature-progress');
  const fixtureEventCount = document.getElementById('fixture-event-count');
  const fixturePayout = document.getElementById('fixture-payout');
  const fixtureEngineState = document.getElementById('fixture-engine-state');
  const fixtureEventHistory = document.getElementById('fixture-event-history');
  const runtimeButton = document.getElementById('runtime-button');
  const runtimePanel = document.getElementById('runtime-readback');
  const runtimeStatus = document.getElementById('runtime-status');
  const runtimeFeatureProgress = document.getElementById('runtime-feature-progress');
  const runtimePayout = document.getElementById('runtime-payout');
  const runtimeEventCount = document.getElementById('runtime-event-count');
  const runtimeEventHistory = document.getElementById('runtime-event-history');
  const config = window.GANESHA_CONFIG || {};
  const endpoint = (config.roundEndpoint || '').replace(/\/$/, '');
  const launchParams = new URLSearchParams(window.location.search);
  const providerSessionRequested = launchParams.has('sessionID') || launchParams.has('rgs_url');
  const stakeSessionPanel = document.getElementById('stake-session-panel');
  const stakeBalance = document.getElementById('stake-balance');
  const stakeSessionStatus = document.getElementById('stake-session-status');
  const stakeReconnectButton = document.getElementById('stake-reconnect-button');
  const soundToggle = document.getElementById('sound-toggle');
  let soundEnabled = false;
  const soundSources = {
    reelStop: new URL('./assets/sfx/reel-stop.wav', import.meta.url).href,
    wildExpansion: new URL('./assets/sfx/wild-expansion.wav', import.meta.url).href,
    freeSpins: new URL('./assets/sfx/free-spins.wav', import.meta.url).href,
    win: new URL('./assets/sfx/win.wav', import.meta.url).href,
  };
  const soundPlayers = new Set();
  const playSfx = (name) => {
    if (!soundEnabled || !Object.hasOwn(soundSources, name)) return;
    try {
      // Use a one-shot player per event. Rewinding a shared Audio object while
      // its previous play() promise is pending aborts that promise and cuts off
      // overlapping reel/feature cues.
      const player = new Audio(soundSources[name]);
      player.preload = 'auto';
      player.volume = 0.34;
      player.setAttribute('aria-hidden', 'true');
      player.tabIndex = -1;
      document.body.append(player);
      soundPlayers.add(player);
      const release = () => {
        soundPlayers.delete(player);
        player.remove();
      };
      player.addEventListener('ended', release, { once: true });
      player.addEventListener('error', release, { once: true });
      const playback = player.play();
      if (playback && typeof playback.catch === 'function') playback.catch(release);
    } catch (_) {
      // Audio is optional; playback failure never affects the confirmed game state.
    }
  };
  if (soundToggle) {
    soundToggle.addEventListener('click', () => {
      soundEnabled = !soundEnabled;
      soundToggle.setAttribute('aria-pressed', String(soundEnabled));
      soundToggle.textContent = soundEnabled ? 'SOUND ON' : 'SOUND OFF';
      soundToggle.setAttribute('aria-label', soundEnabled ? 'Disable preview sound' : 'Enable preview sound');
      if (soundEnabled) playSfx('reelStop');
      else {
        for (const player of soundPlayers) {
          player.pause();
          player.remove();
        }
        soundPlayers.clear();
      }
    });
  }
  let demoSessionId = null;
  let demoEventCount = 0;
  let demoBusy = false;
  let demoSpinCount = 0;
  let fixtureSessionId = null;
  let fixtureRoundId = null;
  let fixtureRequestId = null;
  let fixtureBusy = false;
  let demoApiAvailable = false;
  let gameFixtureApiAvailable = false;
  let runtimeApiAvailable = false;
  let roundRestoreBusy = false;
  let stakeAdapter = null;
  let stakeReconnectBusy = false;
  const inFlightRoundReads = new Map();
  readbackElement.hidden = false;

  const symbolAssets = Object.freeze({
    WILD_GANESHA: ['./assets/ganesha_wild_v15.svg', 'GANESHA WILD', 'premium', 'tier-wild', 'WILD'],
    SCATTER: ['./assets/lotus_scatter_v15.svg', 'LOTUS SCATTER', 'lotus', 'tier-scatter', 'SCATTER'],
    SCATTER_LOTUS: ['./assets/lotus_scatter_v15.svg', 'LOTUS SCATTER', 'lotus', 'tier-scatter', 'SCATTER'],
    ELEPHANT: ['./assets/elephant_icon_v15.svg', 'ELEPHANT', 'premium', 'tier-high', 'HIGH PAY'],
    CHAKRA: ['./assets/chakra_icon_v15.svg', 'CHAKRA', 'standard', 'tier-low', 'LOW PAY'],
    MODAK: ['./assets/modak_icon_v15.svg', 'MODAK', 'standard', 'tier-low', 'LOW PAY'],
    MOUSE: ['./assets/mouse_icon_v15.svg', 'MOUSE', 'premium', 'tier-high', 'HIGH PAY'],
    A: ['./assets/a_icon_v15.svg', 'A', 'standard', 'tier-low', 'LOW PAY'],
    K: ['./assets/k_icon_v15.svg', 'K', 'standard', 'tier-low', 'LOW PAY'],
  });

  const appendSymbolArtwork = (cell, definition, fallback) => {
    if (definition?.[4]) {
      const rank = document.createElement('span');
      rank.className = 'symbol-rank';
      rank.textContent = definition[4];
      cell.appendChild(rank);
    }
    if (definition) {
      const image = document.createElement('img');
      image.src = definition[0];
      image.alt = definition[1];
      cell.appendChild(image);
    }
    const label = document.createElement('small');
    label.textContent = definition ? definition[1] : fallback;
    cell.appendChild(label);
  };

  const disableAllWagerControls = () => {
    document.querySelectorAll('button:not(#sound-toggle)').forEach((button) => { button.disabled = true; });
  };
  disableAllWagerControls();
  if (providerSessionRequested) {
    if (stakeSessionPanel) stakeSessionPanel.hidden = false;
    connection.textContent = 'STAKE RGS · AUTHENTICATING';
    status.textContent = 'Provider session detected. Only read-only authentication is enabled; no bet or settlement request will be sent.';
  }

  const validBoard = (board) => Array.isArray(board) && board.length === 5
    && board.every((reel) => Array.isArray(reel) && reel.length === 3
      && reel.every((symbol) => typeof symbol === 'string' && symbol.length > 0 && symbol.length <= 32));

  const renderServerBoard = (board, roundId, sequence, source = 'authenticated-server-event', sourceLabel = 'Authenticated server event') => {
    if (!validBoard(board)) throw new Error('server event contains a malformed 5x3 board');
    const cells = [];
    for (let row = 0; row < 3; row += 1) {
      for (let reel = 0; reel < 5; reel += 1) {
        const symbol = board[reel][row];
        const definition = symbolAssets[symbol];
        const cell = document.createElement('div');
        cell.className = 'symbol ' + (definition ? definition[2] + ' ' + definition[3] : 'standard');
        appendSymbolArtwork(cell, definition, symbol);
        cells.push(cell);
      }
    }
    boardElement.replaceChildren(...cells);
    boardElement.setAttribute('aria-label', sourceLabel + ' for round ' + roundId + ', event sequence ' + sequence);
    boardElement.setAttribute('aria-live', 'polite');
    boardElement.dataset.source = source;
  };

  const renderDemoReel = (reelIndex, symbols, source = 'scripted-demo-fixture') => {
    if (!Number.isSafeInteger(reelIndex) || reelIndex < 0 || reelIndex > 4
        || !Array.isArray(symbols) || symbols.length !== 3
        || !symbols.every((symbol) => typeof symbol === 'string' && symbol.length > 0 && symbol.length <= 32)) {
      throw new Error('demo reel event is malformed');
    }
    const cells = Array.from(boardElement.children);
    for (let row = 0; row < 3; row += 1) {
      const index = row * 5 + reelIndex;
      const definition = symbolAssets[symbols[row]];
      const cell = document.createElement('div');
      cell.className = 'symbol ' + (definition ? definition[2] + ' ' + definition[3] : 'standard') + ' demo-reel-stopped';
      appendSymbolArtwork(cell, definition, symbols[row]);
      cells[index] = cell;
    }
    boardElement.replaceChildren(...cells);
    boardElement.dataset.source = source;
    boardElement.setAttribute('aria-label', (source === 'engine-fixture-test-only' ? 'Test-only GameEngine fixture board' : 'Scripted non-wagering demonstration board') + '; reel ' + (reelIndex + 1) + ' stopped');
  };

  const delayForMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ? Promise.resolve() : new Promise((resolve) => window.setTimeout(resolve, 130));

  const replayCue = (element, className) => {
    if (!element || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    element.classList.remove(className);
    void element.offsetWidth;
    element.classList.add(className);
    element.addEventListener('animationend', () => element.classList.remove(className), { once: true });
  };

  const featureRawBoard = (events, spinNumber) => {
    const stops = events.filter((event) => event.event_type === 'FEATURE_REEL_STOPPED'
      && event.payload.spin_number === spinNumber)
      .sort((left, right) => left.payload.reel_index - right.payload.reel_index);
    if (stops.length !== 5 || stops.some((event, index) => event.payload.reel_index !== index)) {
      throw new Error('Wild expansion requires all five authenticated feature reel stops');
    }
    return stops.map((event) => event.payload.symbols);
  };

  const animateExpandedReels = async (reels) => {
    if (!Array.isArray(reels) || reels.some((reel) => !Number.isSafeInteger(reel) || reel < 0 || reel > 4)
        || new Set(reels).size !== reels.length || boardElement.children.length !== 15) {
      throw new Error('Wild expansion animation indices or board are invalid');
    }
    if (reels.length === 0) throw new Error('Wild expansion event must identify at least one reel');
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const boardRect = boardElement.getBoundingClientRect();
    const overlays = [];
    for (const reel of reels) {
      const sourceCell = [...Array(3).keys()].map((row) => boardElement.children[row * 5 + reel])
        .find((cell) => cell.querySelector('img[alt="GANESHA WILD"]'));
      if (!sourceCell) throw new Error('Wild expansion source reel has no visible Ganesha Wild symbol');
      const topCell = boardElement.children[reel];
      const bottomCell = boardElement.children[10 + reel];
      const topRect = topCell.getBoundingClientRect();
      const bottomRect = bottomCell.getBoundingClientRect();
      const overlay = document.createElement('div');
      overlay.className = 'wild-expansion-overlay';
      overlay.dataset.reelIndex = String(reel);
      overlay.setAttribute('aria-label', 'Ganesha Wild expanding to fill reel ' + (reel + 1));
      overlay.style.left = (topRect.left - boardRect.left) + 'px';
      overlay.style.top = (topRect.top - boardRect.top) + 'px';
      overlay.style.width = topRect.width + 'px';
      overlay.style.height = (bottomRect.bottom - topRect.top) + 'px';
      const sourceRect = sourceCell.getBoundingClientRect();
      overlay.style.transformOrigin = '50% ' + (((sourceRect.top
        + sourceRect.height / 2 - topRect.top) / (bottomRect.bottom - topRect.top)) * 100) + '%';
      const image = document.createElement('img');
      image.src = symbolAssets.WILD_GANESHA[0];
      image.alt = 'GANESHA WILD';
      const label = document.createElement('span');
      label.textContent = 'WILD';
      overlay.append(image, label);
      boardElement.appendChild(overlay);
      overlays.push(overlay);
    }
    const animations = overlays.map((overlay) => overlay.animate([
      { transform: 'scaleY(.14)', filter: 'brightness(.72) saturate(1.1)' },
      { offset: .28, transform: 'scaleY(.42)', filter: 'brightness(1.55) saturate(1.35)' },
      { offset: .62, transform: 'scaleY(1.06)', filter: 'brightness(1.32) saturate(1.2)' },
      { offset: .82, transform: 'scaleY(.97)', filter: 'brightness(1.12)' },
      { transform: 'scaleY(1)', filter: 'brightness(1)' },
    ], { duration: 820, easing: 'cubic-bezier(.12,.76,.16,1)', fill: 'both' }));
    try {
      await Promise.all(animations.map((animation) => animation.finished));
    } finally {
      overlays.forEach((overlay) => overlay.remove());
    }
  };

  const playDemo = async () => {
    if (demoBusy || !endpoint || !demoApiAvailable) return;
    demoBusy = true;
    demoButton.disabled = true;
    engineFixtureButton.disabled = true;
    try {
      if (!demoSessionId) {
        const created = await fetch(endpoint + '/api/demo/sessions', {
          method: 'POST', credentials: 'omit', cache: 'no-store',
          headers: { 'Content-Type': 'application/json' }, body: '{}', redirect: 'error',
        });
        if (!created.ok) throw new Error('demo session creation failed: ' + created.status);
        const session = await created.json();
        if (session.contract !== 'ganesha.demo.events' || session.schema_version !== 1
            || typeof session.session_id !== 'string' || !/^[a-f0-9]{32}$/.test(session.session_id)) {
          throw new Error('demo session contract is invalid');
        }
        demoSessionId = session.session_id;
      }
      const requestId = window.crypto && typeof window.crypto.randomUUID === 'function'
        ? window.crypto.randomUUID() : 'demo-' + Date.now() + '-' + Math.random().toString(16).slice(2);
      const response = await fetch(endpoint + '/api/demo/sessions/' + demoSessionId + '/spins', {
        method: 'POST', credentials: 'omit', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: requestId }), redirect: 'error',
      });
      if (!response.ok) throw new Error('demo spin failed: ' + response.status);
      const result = await response.json();
      if (result.contract !== 'ganesha.demo.events' || result.schema_version !== 1
          || result.session_id !== demoSessionId || result.classification !== 'SCRIPTED_VISUAL_FIXTURE'
          || !Array.isArray(result.events)) throw new Error('demo event contract is invalid');
      boardElement.replaceChildren(...Array.from({ length: 15 }, () => {
        const cell = document.createElement('div');
        cell.className = 'symbol demo-reel-waiting';
        cell.textContent = '·';
        return cell;
      }));
      for (const event of result.events) {
        if (!event || event.session_id !== demoSessionId || event.schema_version !== 1
            || event.sequence !== demoEventCount + 1 || !event.payload || typeof event.payload !== 'object') {
          throw new Error('demo event order or identity is invalid');
        }
        demoEventCount = event.sequence;
        if (event.event_type === 'DEMO_REEL_STOPPED') {
          playSfx('reelStop');
          renderDemoReel(event.payload.reel_index, event.payload.symbols);
          await delayForMotion();
        } else if (event.event_type === 'DEMO_BOARD_REVEALED') {
          if (!validBoard(event.payload.board)) throw new Error('demo board is not 5x3');
          renderServerBoard(event.payload.board, 'DEMO', event.sequence, 'scripted-demo-fixture', 'Scripted demo fixture event');
          boardElement.dataset.source = 'scripted-demo-fixture';
        } else if (!['DEMO_SPIN_STARTED', 'DEMO_PRESENTATION_COMPLETED'].includes(event.event_type)) {
          throw new Error('unknown demo event type');
        }
      }
      demoSpinCount = result.spin_number;
      connection.textContent = 'LOCAL SCRIPTED DEMO · NO PROVIDER';
      status.textContent = 'Demo presentation ' + demoSpinCount + ' completed. Fixed fixture only — no RNG, Math, wager, balance or payout.';
    } catch (error) {
      status.textContent = 'Demo unavailable: ' + error.message + '. No financial action was taken.';
    } finally {
      demoBusy = false;
      demoButton.disabled = !demoApiAvailable;
      engineFixtureButton.disabled = !gameFixtureApiAvailable;
    }
  };

  const canonicalJson = (value) => {
    if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
    if (value && typeof value === 'object') {
      return '{' + Object.keys(value).sort().map((key) => JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}';
    }
    return JSON.stringify(value);
  };

  const sha256Hex = async (value) => {
    if (!window.crypto || !window.crypto.subtle || typeof window.TextEncoder !== 'function') {
      throw new Error('Web Crypto SHA-256 is required to verify fixture event integrity');
    }
    const digest = await window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, '0')).join('');
  };

  const verifyPresentationEvents = async (result) => {
    if (result.contract !== 'ganesha.game.presentation' || result.schema_version !== 1
        || result.session_contract !== 'ganesha.game.fixture.sessions' || result.session_schema_version !== 1
        || result.classification !== 'TEST_FIXTURE_ONLY' || result.financial_effects !== false
        || result.session_id !== fixtureSessionId || result.round_id !== fixtureRoundId
        || !Array.isArray(result.events) || !result.state || typeof result.state !== 'object') {
      throw new Error('GameEngine fixture response contract is invalid');
    }
    let previousHash = '0'.repeat(64);
    const knownTypes = new Set([
      'ROUND_PRESENTATION_STARTED', 'BASE_REEL_STOPPED', 'BASE_OUTCOME_REVEALED',
      'FEATURE_STARTED', 'FEATURE_REEL_STOPPED', 'WILD_EXPANSION_APPLIED',
      'MULTIPLIER_APPLIED', 'FEATURE_SPIN_RESOLVED', 'FEATURE_ENDED',
      'ROUND_PRESENTATION_COMPLETED',
    ]);
    for (let index = 0; index < result.events.length; index += 1) {
      const event = result.events[index];
      if (!event || event.contract !== 'ganesha.game.presentation' || event.schema_version !== 1
          || event.round_id !== fixtureRoundId || event.sequence !== index + 1
          || !knownTypes.has(event.event_type) || !event.payload || typeof event.payload !== 'object'
          || Array.isArray(event.payload) || event.previous_hash !== previousHash) {
        throw new Error('GameEngine presentation event identity, order or schema is invalid');
      }
      const eventId = await sha256Hex(fixtureRoundId + ':presentation:' + event.sequence + ':'
        + event.event_type + ':' + canonicalJson(event.payload));
      if (event.event_id !== eventId) throw new Error('GameEngine presentation event ID mismatch');
      const unhashed = { ...event };
      delete unhashed.event_hash;
      const eventHash = await sha256Hex(canonicalJson(unhashed));
      if (event.event_hash !== eventHash) throw new Error('GameEngine presentation hash chain mismatch');
      previousHash = eventHash;
    }
    const completion = result.events[result.events.length - 1];
    const baseOutcome = result.events.find((event) => event.event_type === 'BASE_OUTCOME_REVEALED');
    const featureStart = result.events.find((event) => event.event_type === 'FEATURE_STARTED');
    const featureResolutions = result.events.filter((event) => event.event_type === 'FEATURE_SPIN_RESOLVED');
    const featureEnd = result.events.find((event) => event.event_type === 'FEATURE_ENDED');
    const baseStops = result.events.filter((event) => event.event_type === 'BASE_REEL_STOPPED')
      .sort((a, b) => a.payload.reel_index - b.payload.reel_index);
    if (!baseOutcome || baseStops.length !== 5
        || canonicalJson(baseStops.map((event) => event.payload.symbols)) !== canonicalJson(baseOutcome.payload.board)
        || canonicalJson(baseOutcome.payload.board) !== canonicalJson(baseOutcome.payload.display_board)) {
      throw new Error('GameEngine fixture BASE reel stops, raw board and display board disagree');
    }
    const scatterCount = baseOutcome.payload.board.flat()
      .filter((symbol) => symbol === 'SCATTER_LOTUS' || symbol === 'SCATTER').length;
    if (scatterCount === 5) throw new Error('5 Scatter requires the unavailable provider-authoritative embedded EPICBUY_V37 payload');
    if (scatterCount >= 6) throw new Error('6+ Scatter is rejected by the current BASE contract (fail closed)');
    const expectedFreeSpins = scatterCount === 3 ? 10 : scatterCount === 4 ? 12 : 0;
    let projectedTotal = baseOutcome.payload.payout_milli;
    let featurePayoutTotal = 0;
    for (let spin = 1; spin <= featureResolutions.length; spin += 1) {
      const resolution = featureResolutions[spin - 1];
      const stops = result.events.filter((event) => event.event_type === 'FEATURE_REEL_STOPPED'
        && event.payload.spin_number === spin).sort((a, b) => a.payload.reel_index - b.payload.reel_index);
      const rawBoard = stops.map((event) => event.payload.symbols);
      const wildEvent = result.events.find((event) => event.event_type === 'WILD_EXPANSION_APPLIED'
        && event.payload.spin_number === spin);
      const multiplierEvent = result.events.find((event) => event.event_type === 'MULTIPLIER_APPLIED'
        && event.payload.spin_number === spin);
      const wildReels = resolution.payload.wild_reels;
      const expectedDisplay = deriveExpandedWildDisplayBoard(rawBoard, wildReels);
      if (stops.length !== 5 || canonicalJson(rawBoard) !== canonicalJson(resolution.payload.board)
          || canonicalJson(expectedDisplay) !== canonicalJson(resolution.payload.display_board)
          || (wildReels.length > 0 && (!wildEvent
            || canonicalJson(wildEvent.payload.reels) !== canonicalJson(wildReels)
            || canonicalJson(wildEvent.payload.display_board) !== canonicalJson(expectedDisplay)))
          || (wildReels.length === 0 && wildEvent)
          || (resolution.payload.multiplier > 1
            ? (!multiplierEvent || multiplierEvent.payload.multiplier !== resolution.payload.multiplier)
            : Boolean(multiplierEvent))) {
        throw new Error('GameEngine fixture feature reel stops, Wild display or multiplier disagree');
      }
      const nextTotal = resolution.payload.round_payout_after_milli;
      if (resolution.payload.payout_awarded_milli !== nextTotal - projectedTotal
          || resolution.payload.payout_milli < resolution.payload.payout_awarded_milli) {
        throw new Error('GameEngine fixture per-spin payout does not reconcile to the round total');
      }
      projectedTotal = nextTotal;
      featurePayoutTotal += resolution.payload.payout_awarded_milli;
    }
    if (result.state.status !== 'COMPLETED' || result.state.classification !== 'NON_FINANCIAL_PRESENTATION_ONLY'
        || result.state.event_count !== result.events.length || result.state.last_event_hash !== previousHash
        || result.state.feature_initial_spins !== expectedFreeSpins || result.state.feature_spins_played !== expectedFreeSpins
        || result.state.feature_spins_remaining !== 0
        || !baseOutcome || baseOutcome.payload.free_spins_awarded !== expectedFreeSpins
        || (expectedFreeSpins > 0 ? (!featureStart || featureStart.payload.initial_spins !== expectedFreeSpins) : Boolean(featureStart))
        || featureResolutions.length !== expectedFreeSpins
        || featureResolutions.some((event, index) => event.payload.spin_number !== index + 1
          || event.payload.retrigger_awarded !== 0
          || event.payload.remaining_spins !== expectedFreeSpins - 1 - index)
        || (expectedFreeSpins > 0 ? (!featureEnd || featureEnd.payload.spins_played !== expectedFreeSpins || featureEnd.payload.remaining_spins !== 0) : Boolean(featureEnd))
        || (expectedFreeSpins > 0 && featureEnd.payload.payout_milli !== featurePayoutTotal)
        || projectedTotal !== result.state.total_payout_milli
        || !completion || completion.event_type !== 'ROUND_PRESENTATION_COMPLETED'
        || completion.payload.total_payout_milli !== result.state.total_payout_milli
        || completion.payload.feature_spins_played !== result.state.feature_spins_played
        || completion.payload.round_cap_reached !== result.state.round_cap_reached) {
      throw new Error('GameEngine fixture terminal state or final payout does not match its event stream');
    }
    return result.events;
  };

  const verifyRuntimeResponse = async (result, sessionId) => {
    if (result.contract !== 'ganesha.game.runtime' || result.schema_version !== 1
        || result.classification !== 'NON_FINANCIAL_SIMULATION' || result.financial_effects !== false
        || result.session_id !== sessionId || typeof result.round_id !== 'string'
        || !result.round_id.startsWith('runtime-') || !Array.isArray(result.events)
        || !result.state || !result.outcome) {
      throw new Error('independent runtime response contract is invalid');
    }
    let previousHash = '0'.repeat(64);
    const allowed = new Set(['ROUND_PRESENTATION_STARTED', 'BASE_REEL_STOPPED', 'BASE_OUTCOME_REVEALED',
      'FEATURE_STARTED', 'FEATURE_REEL_STOPPED', 'WILD_EXPANSION_APPLIED', 'MULTIPLIER_APPLIED',
      'FEATURE_SPIN_RESOLVED', 'FEATURE_ENDED', 'ROUND_PRESENTATION_COMPLETED']);
    for (let index = 0; index < result.events.length; index += 1) {
      const event = result.events[index];
      if (!event || event.contract !== 'ganesha.game.presentation' || event.schema_version !== 1
          || event.round_id !== result.round_id || event.sequence !== index + 1
          || !allowed.has(event.event_type) || !event.payload || typeof event.payload !== 'object'
          || Array.isArray(event.payload) || event.previous_hash !== previousHash) {
        throw new Error('runtime event identity, sequence or schema is invalid');
      }
      const expectedId = await sha256Hex(result.round_id + ':presentation:' + event.sequence + ':'
        + event.event_type + ':' + canonicalJson(event.payload));
      if (event.event_id !== expectedId) throw new Error('runtime deterministic event ID mismatch');
      const envelope = { ...event };
      delete envelope.event_hash;
      const digest = await sha256Hex(canonicalJson(envelope));
      if (digest !== event.event_hash) throw new Error('runtime event hash chain mismatch');
      previousHash = digest;
    }
    if (result.state.status !== 'COMPLETED'
        || result.state.classification !== 'NON_FINANCIAL_SIMULATION'
        || result.state.event_count !== result.events.length
        || result.state.last_event_hash !== previousHash
        || result.state.feature_spins_played !== result.outcome.free_spins_played
        || result.state.total_payout_milli !== result.outcome.total_payout_milli
        || canonicalJson(result.state.base_board) !== canonicalJson(result.outcome.base_result.board)) {
      throw new Error('runtime replay projection differs from the committed engine outcome');
    }
    if (!Array.isArray(result.lifecycle_events) || result.lifecycle_events.length !== 3
        || !result.lifecycle_state || result.lifecycle_state.status !== 'COMPLETED'
        || result.lifecycle_state.classification !== 'NON_FINANCIAL_SIMULATION'
        || result.lifecycle_state.financial_effects !== false
        || result.lifecycle_state.event_count !== result.lifecycle_events.length) {
      throw new Error('runtime lifecycle Event Contract is missing or incomplete');
    }
    let lifecycleHash = '0'.repeat(64);
    const lifecycleTypes = ['SIMULATION_STARTED', 'SIMULATION_OUTCOME_COMMITTED', 'SIMULATION_COMPLETED'];
    for (let index = 0; index < result.lifecycle_events.length; index += 1) {
      const event = result.lifecycle_events[index];
      if (!event || event.schema_version !== 1 || event.round_id !== result.round_id
          || event.sequence !== index + 1 || event.event_type !== lifecycleTypes[index]
          || event.previous_hash !== lifecycleHash || !event.payload || typeof event.payload !== 'object') {
        throw new Error('runtime lifecycle event sequence or schema is invalid');
      }
      const eventId = result.round_id + ':simulation:' + event.sequence;
      if (event.event_id !== eventId) throw new Error('runtime lifecycle event ID mismatch');
      const envelope = { ...event };
      delete envelope.event_hash;
      lifecycleHash = await sha256Hex(canonicalJson(envelope));
      if (event.event_hash !== lifecycleHash) throw new Error('runtime lifecycle event hash mismatch');
    }
    if (result.lifecycle_state.last_event_hash !== lifecycleHash
        || result.lifecycle_state.base_board === null
        || canonicalJson(result.lifecycle_state.base_board) !== canonicalJson(result.state.base_board)
        || canonicalJson(result.lifecycle_state.base_board) !== canonicalJson(result.outcome.base_result.board)
        || result.lifecycle_state.scatter_count !== result.outcome.base_result.scatter_count
        || result.lifecycle_state.initial_free_spins !== result.outcome.initial_free_spins
        || result.lifecycle_state.free_spins_played !== result.outcome.free_spins_played
        || result.lifecycle_state.base_payout_milli !== result.outcome.base_result.payout_milli
        || result.lifecycle_state.total_payout_milli !== result.state.total_payout_milli
        || result.lifecycle_state.feature_payout_milli !== result.state.total_payout_milli - result.outcome.base_result.payout_milli
        || result.lifecycle_state.round_cap_reached !== result.outcome.round_cap_reached) {
      throw new Error('runtime lifecycle Event Contract differs from presentation replay');
    }
    return result.events;
  };

  const runtimePendingStorageKey = 'ganesha.runtime.pending.v1:' + endpoint;
  let runtimePendingMemory = null;
  const readRuntimePending = () => {
    if (runtimePendingMemory) return runtimePendingMemory;
    try {
      const raw = window.sessionStorage.getItem(runtimePendingStorageKey);
      if (!raw) return null;
      const value = JSON.parse(raw);
      if (!value || !/^[a-f0-9]{32}$/.test(value.session_id || '')
          || typeof value.request_id !== 'string' || !/^[A-Za-z0-9._:-]{1,128}$/.test(value.request_id)) {
        window.sessionStorage.removeItem(runtimePendingStorageKey);
        return null;
      }
      runtimePendingMemory = value;
      return value;
    } catch (_) { return null; }
  };
  const writeRuntimePending = (value) => {
    runtimePendingMemory = value;
    try { window.sessionStorage.setItem(runtimePendingStorageKey, JSON.stringify(value)); } catch (_) { /* memory retry remains available in this tab */ }
  };
  const clearRuntimePending = () => {
    runtimePendingMemory = null;
    try { window.sessionStorage.removeItem(runtimePendingStorageKey); } catch (_) { /* best-effort cleanup */ }
  };

  const renderRuntimeResult = async (result, sessionId) => {
      const events = await verifyRuntimeResponse(result, sessionId);
      boardElement.replaceChildren(...Array.from({ length: 15 }, () => {
        const cell = document.createElement('div');
        cell.className = 'symbol demo-reel-waiting';
        cell.textContent = '·';
        return cell;
      }));
      for (const event of events) {
        runtimeEventCount.textContent = String(event.sequence);
        const item = document.createElement('li');
        item.textContent = String(event.sequence).padStart(2, '0') + ' · ' + event.event_type.replace(/_/g, ' ');
        runtimeEventHistory.appendChild(item);
        if (event.event_type === 'BASE_REEL_STOPPED' || event.event_type === 'FEATURE_REEL_STOPPED') {
          playSfx('reelStop');
          renderDemoReel(event.payload.reel_index, event.payload.symbols, 'independent-runtime-simulation');
          await delayForMotion();
        } else if (event.event_type === 'BASE_OUTCOME_REVEALED') {
          renderServerBoard(event.payload.display_board, result.round_id, event.sequence,
            'independent-runtime-simulation', 'Non-financial independent runtime projection');
          runtimeStatus.textContent = 'BASE OUTCOME · SIMULATION';
          if (event.payload.payout_milli > 0) {
            playSfx('win');
            replayCue(runtimeStatus, 'event-pulse');
          }
        } else if (event.event_type === 'FEATURE_STARTED') {
          playSfx('freeSpins');
          runtimeFeatureProgress.textContent = '0 / ' + event.payload.initial_spins + ' played · ' + event.payload.initial_spins + ' remaining';
          runtimeStatus.textContent = 'FREE SPINS · SIMULATION';
          replayCue(runtimeStatus, 'feature-start-reveal');
          await delayForMotion();
        } else if (event.event_type === 'WILD_EXPANSION_APPLIED') {
          playSfx('wildExpansion');
          const rawBoard = featureRawBoard(events, event.payload.spin_number);
          renderServerBoard(rawBoard, result.round_id, event.sequence,
            'independent-runtime-simulation', 'Stopped feature reels before Ganesha Wild expansion');
          await animateExpandedReels(event.payload.reels);
          renderServerBoard(event.payload.display_board, result.round_id, event.sequence,
            'independent-runtime-simulation', 'Non-financial Wild expanded reel projection');
          runtimeStatus.textContent = 'WILD EXPANSION · SIMULATION';
          replayCue(runtimeStatus, 'event-pulse');
          await delayForMotion();
        } else if (event.event_type === 'MULTIPLIER_APPLIED') {
          runtimeStatus.textContent = 'MULTIPLIER ×' + event.payload.multiplier + ' · SIMULATION';
          replayCue(runtimeStatus, 'multiplier-reveal');
          await delayForMotion();
        } else if (event.event_type === 'FEATURE_SPIN_RESOLVED') {
          if (event.payload.payout_awarded_milli > 0) playSfx('win');
          renderServerBoard(event.payload.display_board, result.round_id, event.sequence,
            'independent-runtime-simulation', 'Non-financial resolved feature board');
          runtimeFeatureProgress.textContent = event.payload.spin_number + ' / ' + result.outcome.initial_free_spins + ' played · ' + event.payload.remaining_spins + ' remaining';
          runtimePayout.textContent = event.payload.round_payout_after_milli + ' milli-units · simulation projection';
          if (event.payload.payout_awarded_milli > 0) replayCue(runtimePayout, 'payout-reveal');
        } else if (event.event_type === 'FEATURE_ENDED') {
          runtimeStatus.textContent = 'FREE SPINS ENDED · ' + event.payload.termination_reason;
          replayCue(runtimeStatus, 'event-pulse');
        } else if (event.event_type === 'ROUND_PRESENTATION_COMPLETED') {
          runtimeStatus.textContent = 'COMPLETED · NON-FINANCIAL';
          replayCue(runtimePayout, 'payout-reveal');
        }
      }
      runtimePayout.textContent = result.state.total_payout_milli + ' milli-units · simulation only';
      connection.textContent = 'INDEPENDENT RUNTIME · DEVELOPMENT MATH';
      status.textContent = 'Independent GameRuntime completed and browser-verified. Deterministic development Math only; no wager, debit, Wallet, settlement or Provider call.';
  };

  const readRuntimeSnapshot = async (sessionId) => {
    const response = await fetch(endpoint + '/api/runtime/sessions/' + sessionId, {
      credentials: 'omit', cache: 'no-store', redirect: 'error',
    });
    if (!response.ok) throw new Error('runtime snapshot read failed: ' + response.status);
    const snapshot = await response.json();
    if (snapshot.contract !== 'ganesha.game.runtime' || snapshot.schema_version !== 1
        || snapshot.session_id !== sessionId || snapshot.classification !== 'NON_FINANCIAL_SIMULATION'
        || snapshot.financial_effects !== false) throw new Error('runtime snapshot identity is invalid');
    return snapshot;
  };

  const playIndependentRuntime = async () => {
    if (!runtimeApiAvailable || !endpoint) return;
    runtimeButton.disabled = true;
    runtimePanel.hidden = false;
    runtimeStatus.textContent = 'STARTING / RESTORING';
    runtimeFeatureProgress.textContent = '—';
    runtimePayout.textContent = '—';
    runtimeEventCount.textContent = '0';
    runtimeEventHistory.replaceChildren();
    try {
      let pending = readRuntimePending();
      let result = null;
      if (pending) {
        const snapshot = await readRuntimeSnapshot(pending.session_id);
        if (snapshot.status === 'COMPLETED') {
          result = snapshot;
          runtimeStatus.textContent = 'RESTORED FROM SERVER EVENT REPLAY';
        } else if (snapshot.status !== 'CREATED') {
          throw new Error('runtime server returned an unsupported recovery state: ' + snapshot.status);
        }
      } else {
        const created = await fetch(endpoint + '/api/runtime/sessions', {
          method: 'POST', credentials: 'omit', cache: 'no-store',
          headers: { 'Content-Type': 'application/json' }, body: '{}', redirect: 'error',
        });
        if (!created.ok) throw new Error('runtime session creation failed: ' + created.status);
        const session = await created.json();
        if (session.contract !== 'ganesha.game.runtime' || session.schema_version !== 1
            || session.classification !== 'NON_FINANCIAL_SIMULATION' || session.financial_effects !== false
            || typeof session.session_id !== 'string' || !/^[a-f0-9]{32}$/.test(session.session_id)) {
          throw new Error('runtime session contract is invalid');
        }
        const requestId = window.crypto && typeof window.crypto.randomUUID === 'function'
          ? window.crypto.randomUUID() : await sha256Hex(session.session_id + ':' + Date.now());
        pending = { session_id: session.session_id, request_id: requestId };
        writeRuntimePending(pending);
      }

      if (!result) {
        let response;
        try {
          response = await fetch(endpoint + '/api/runtime/sessions/' + pending.session_id + '/rounds', {
            method: 'POST', credentials: 'omit', cache: 'no-store',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ request_id: pending.request_id }), redirect: 'error',
          });
        } catch (transportError) {
          // A lost browser response does not prove the server failed to commit.
          // Read the durable session first; if still CREATED, retry only with
          // the same request_id so the server's fingerprint cache remains valid.
          const snapshot = await readRuntimeSnapshot(pending.session_id);
          if (snapshot.status === 'COMPLETED') result = snapshot;
          else if (snapshot.status === 'CREATED') {
            response = await fetch(endpoint + '/api/runtime/sessions/' + pending.session_id + '/rounds', {
              method: 'POST', credentials: 'omit', cache: 'no-store',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ request_id: pending.request_id }), redirect: 'error',
            });
          } else throw transportError;
        }
        if (!result) {
          if (!response || !response.ok) {
            // Even non-2xx is reconciled by reading the persisted state before
            // deciding that no completed response exists.
            const snapshot = await readRuntimeSnapshot(pending.session_id);
            if (snapshot.status === 'COMPLETED') result = snapshot;
            else throw new Error('runtime resolution failed: ' + (response ? response.status : 'no response'));
          } else result = await response.json();
        }
      }
      await renderRuntimeResult(result, pending.session_id);
      clearRuntimePending();
    } catch (error) {
      runtimeStatus.textContent = 'UNAVAILABLE';
      status.textContent = 'Independent runtime unavailable: ' + error.message + '. Pending session/request identity is retained where available; reconnect using the same request ID. No financial action was taken.';
    } finally {
      runtimeButton.disabled = !runtimeApiAvailable;
    }
  };

  const playEngineFixture = async () => {
    if (fixtureBusy || !endpoint || !gameFixtureApiAvailable) return;
    fixtureBusy = true;
    engineFixtureButton.disabled = true;
    demoButton.disabled = true;
    fixturePanel.hidden = false;
    fixtureStatus.textContent = 'STARTING';
    fixtureEngineState.textContent = 'RUNNING';
    fixtureFeatureProgress.textContent = '—';
    fixtureEventCount.textContent = '0';
    if (fixturePayout) fixturePayout.textContent = '—';
    fixtureEventHistory.replaceChildren();
    try {
      if (!fixtureSessionId) {
        const created = await fetch(endpoint + '/api/demo/game-sessions', {
          method: 'POST', credentials: 'omit', cache: 'no-store',
          headers: { 'Content-Type': 'application/json' }, body: '{}', redirect: 'error',
        });
        if (!created.ok) throw new Error('fixture session creation failed: ' + created.status);
        const session = await created.json();
        if (session.contract !== 'ganesha.game.fixture.sessions' || session.schema_version !== 1
            || session.classification !== 'TEST_FIXTURE_ONLY' || session.financial_effects !== false
            || typeof session.session_id !== 'string' || !/^[a-f0-9]{32}$/.test(session.session_id)
            || typeof session.round_id !== 'string' || !session.round_id.startsWith('fixture-')) {
          throw new Error('GameEngine fixture session contract is invalid');
        }
        fixtureSessionId = session.session_id;
        fixtureRoundId = session.round_id;
      }
      if (!fixtureRequestId) {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') fixtureRequestId = window.crypto.randomUUID();
        else {
          const randomBytes = new Uint8Array(16);
          if (!window.crypto || typeof window.crypto.getRandomValues !== 'function') throw new Error('Secure request ID generation is unavailable');
          window.crypto.getRandomValues(randomBytes);
          fixtureRequestId = Array.from(randomBytes).map((byte) => byte.toString(16).padStart(2, '0')).join('');
        }
      }
      const response = await fetch(endpoint + '/api/demo/game-sessions/' + fixtureSessionId + '/rounds', {
        method: 'POST', credentials: 'omit', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: fixtureRequestId }), redirect: 'error',
      });
      if (!response.ok) throw new Error('GameEngine fixture round failed: ' + response.status);
      const result = await response.json();
      const events = await verifyPresentationEvents(result);
      boardElement.replaceChildren(...Array.from({ length: 15 }, () => {
        const cell = document.createElement('div');
        cell.className = 'symbol demo-reel-waiting';
        cell.textContent = '·';
        return cell;
      }));
      let displayedEventCount = 0;
      for (const event of events) {
        displayedEventCount += 1;
        fixtureEventCount.textContent = String(displayedEventCount);
        const item = document.createElement('li');
        item.textContent = String(event.sequence).padStart(2, '0') + ' · ' + event.event_type.replace(/_/g, ' ');
        fixtureEventHistory.appendChild(item);
        if (event.event_type === 'BASE_REEL_STOPPED' || event.event_type === 'FEATURE_REEL_STOPPED') {
          playSfx('reelStop');
          renderDemoReel(event.payload.reel_index, event.payload.symbols, 'engine-fixture-test-only');
          await delayForMotion();
        } else if (event.event_type === 'BASE_OUTCOME_REVEALED') {
          renderServerBoard(event.payload.display_board, fixtureRoundId, event.sequence, 'engine-fixture-test-only', 'Test-only GameEngine fixture event');
          fixtureStatus.textContent = 'BASE OUTCOME · TEST FIXTURE';
          if (event.payload.payout_milli > 0) {
            playSfx('win');
            replayCue(fixtureStatus, 'event-pulse');
          }
        } else if (event.event_type === 'FEATURE_STARTED') {
          playSfx('freeSpins');
          fixtureFeatureProgress.textContent = '0 / ' + event.payload.initial_spins + ' played · ' + event.payload.initial_spins + ' remaining';
          fixtureStatus.textContent = 'FREE SPINS STARTED · TEST FIXTURE';
          replayCue(fixtureStatus, 'feature-start-reveal');
          await delayForMotion();
        } else if (event.event_type === 'WILD_EXPANSION_APPLIED') {
          playSfx('wildExpansion');
          const rawBoard = featureRawBoard(events, event.payload.spin_number);
          renderServerBoard(rawBoard, fixtureRoundId, event.sequence,
            'engine-fixture-test-only', 'Stopped feature reels before Ganesha Wild expansion');
          await animateExpandedReels(event.payload.reels);
          renderServerBoard(event.payload.display_board, fixtureRoundId, event.sequence,
            'engine-fixture-test-only', 'Test-only GameEngine expanded Wild board');
          fixtureStatus.textContent = 'WILD EXPANSION · TEST FIXTURE';
          replayCue(fixtureStatus, 'event-pulse');
          await delayForMotion();
        } else if (event.event_type === 'MULTIPLIER_APPLIED') {
          fixtureStatus.textContent = 'WILD MULTIPLIER ×' + event.payload.multiplier + ' · TEST FIXTURE';
          replayCue(fixtureStatus, 'multiplier-reveal');
          await delayForMotion();
        } else if (event.event_type === 'FEATURE_SPIN_RESOLVED') {
          if (event.payload.payout_awarded_milli > 0) playSfx('win');
          renderServerBoard(event.payload.display_board, fixtureRoundId, event.sequence, 'engine-fixture-test-only', 'Test-only GameEngine fixture event');
          fixtureFeatureProgress.textContent = event.payload.spin_number + ' / ' + result.state.feature_initial_spins + ' played · ' + event.payload.remaining_spins + ' remaining';
          if (event.payload.payout_awarded_milli > 0) {
            fixturePayout.textContent = event.payload.round_payout_after_milli + ' milli-units · test only';
            replayCue(fixturePayout, 'payout-reveal');
          }
        } else if (event.event_type === 'FEATURE_ENDED') {
          fixtureStatus.textContent = 'FREE SPINS ENDED · ' + event.payload.termination_reason;
          replayCue(fixtureStatus, 'event-pulse');
        } else if (event.event_type === 'ROUND_PRESENTATION_COMPLETED') {
          fixtureStatus.textContent = 'COMPLETED · FIXTURE ONLY';
          fixtureEngineState.textContent = 'COMPLETED';
          replayCue(fixturePayout, 'payout-reveal');
        }
      }
      if (fixturePayout) fixturePayout.textContent = result.state.total_payout_milli + ' milli-units · test only';
      connection.textContent = 'LOCAL ENGINE FIXTURE · NO PROVIDER';
      status.textContent = 'GameEngine fixture completed: BASE, 4 Scatter, 12 Free Spins, Wild Expansion and multiplier events. Fixed test-only Math; no RNG, wager, Wallet, settlement or financial payout.';
      fixtureSessionId = null;
      fixtureRoundId = null;
      fixtureRequestId = null;
    } catch (error) {
      fixtureStatus.textContent = 'UNAVAILABLE';
      fixtureEngineState.textContent = 'NOT COMPLETED';
      status.textContent = 'GameEngine fixture unavailable: ' + error.message + '. No financial action was taken.';
    } finally {
      fixtureBusy = false;
      engineFixtureButton.disabled = !gameFixtureApiAvailable;
      demoButton.disabled = !demoApiAvailable;
    }
  };

  const renderRoundReadback = (snapshot, roundId) => {
    const allowedTypes = new Set([
      'ROUND_OPENED', 'BET_RESERVED', 'RNG_COMMITTED', 'FEATURE_STARTED',
      'FEATURE_SPIN_RESOLVED', 'FEATURE_ENDED', 'OUTCOME_COMMITTED',
      'WIN_PRESENTED', 'SETTLED', 'REFUNDED', 'END_ROUND',
    ]);
    if (!['BET_RESERVED', 'OUTCOME_COMMITTED', 'SETTLED', 'REFUNDED'].includes(snapshot.status)
        || !snapshot.state || typeof snapshot.state !== 'object'
        || !Number.isSafeInteger(snapshot.state.event_count)
        || snapshot.state.event_count !== snapshot.events.length
        || typeof snapshot.currency !== 'string' || snapshot.currency.length < 3 || snapshot.currency.length > 12) {
      throw new Error('server round state summary is malformed');
    }
    snapshot.events.forEach((event, index) => {
      if (!event || event.round_id !== roundId || event.schema_version !== 1
          || event.sequence !== index + 1 || !allowedTypes.has(event.event_type)
          || !event.payload || typeof event.payload !== 'object' || Array.isArray(event.payload)) {
        throw new Error('server event identity, schema, sequence or payload is invalid');
      }
    });

    const featureEvents = snapshot.events.filter((event) => event.event_type === 'FEATURE_SPIN_RESOLVED');
    const outcomeEvent = snapshot.events.find((event) => event.event_type === 'OUTCOME_COMMITTED');
    const latestFeatureBoard = featureEvents.length
      ? (featureEvents[featureEvents.length - 1].payload.display_board || featureEvents[featureEvents.length - 1].payload.board)
      : null;
    const baseBoard = outcomeEvent
      ? (outcomeEvent.payload.base_display_board || outcomeEvent.payload.base_board)
      : null;
    const board = latestFeatureBoard || baseBoard;
    if (board) renderServerBoard(board, roundId, snapshot.events.length);
    else {
      boardElement.replaceChildren();
      boardElement.setAttribute('aria-label', 'No committed server-derived board is available for round ' + roundId);
      boardElement.dataset.source = 'authenticated-server-event-empty';
    }

    const played = snapshot.state.feature_spins_played;
    const remaining = snapshot.state.feature_spins_remaining;
    if (!Number.isSafeInteger(played) || played < 0 || !Number.isSafeInteger(remaining) || remaining < 0) {
      throw new Error('server Free Spins counters are malformed');
    }
    featureProgressElement.textContent = played + ' played · ' + remaining + ' remaining';
    eventCountElement.textContent = String(snapshot.events.length);
    if (snapshot.status === 'SETTLED') {
      if (!Number.isSafeInteger(snapshot.state.payout_minor) || snapshot.state.payout_minor < 0) {
        throw new Error('settled round payout is malformed');
      }
      payoutElement.textContent = snapshot.state.payout_minor + ' ' + snapshot.currency + ' minor units · settled';
    } else if (snapshot.status === 'OUTCOME_COMMITTED') {
      payoutElement.textContent = snapshot.state.payout_minor + ' ' + snapshot.currency + ' minor units · committed, not settled';
    } else if (snapshot.status === 'REFUNDED') {
      payoutElement.textContent = 'No payout · bet refunded';
    } else {
      payoutElement.textContent = 'Not committed';
    }
    roundStatusElement.textContent = snapshot.status;
    eventHistoryElement.replaceChildren(...snapshot.events.map((event) => {
      const item = document.createElement('li');
      item.textContent = String(event.sequence).padStart(2, '0') + ' · ' + event.event_type.replace(/_/g, ' ');
      return item;
    }));
    readbackElement.hidden = false;
  };

  const stableJson = (value) => {
    if (Array.isArray(value)) return '[' + value.map(stableJson).join(',') + ']';
    if (value && typeof value === 'object') {
      return '{' + Object.keys(value).sort().map((key) => JSON.stringify(key) + ':' + stableJson(value[key])).join(',') + '}';
    }
    return JSON.stringify(value);
  };

  const verifyRoundProjection = async (snapshot, roundId) => {
    if (!window.crypto || !window.crypto.subtle || typeof TextEncoder !== 'function') {
      throw new Error('Web Crypto SHA-256 is required to verify the persisted round projection');
    }
    let previousHash = '0'.repeat(64);
    for (let index = 0; index < snapshot.events.length; index += 1) {
      const event = snapshot.events[index];
      if (event.previous_hash !== previousHash || typeof event.event_id !== 'string'
          || !/^[0-9a-f]{64}$/.test(event.event_hash || '')) {
        throw new Error('persisted round event hash chain is malformed');
      }
      const envelope = { schema_version: event.schema_version, round_id: event.round_id,
        sequence: event.sequence, event_id: event.event_id, event_type: event.event_type,
        payload: event.payload, previous_hash: event.previous_hash };
      const digest = await window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(stableJson(envelope)));
      const actual = Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, '0')).join('');
      if (actual !== event.event_hash) throw new Error('persisted round event hash verification failed at sequence ' + event.sequence);
      previousHash = actual;
    }
    if (!snapshot.state || snapshot.state.last_event_hash !== previousHash) {
      throw new Error('round state head hash does not match the verified event projection');
    }
    const outcome = snapshot.events.find((event) => event.event_type === 'OUTCOME_COMMITTED');
    if (outcome && outcome.payload.base_display_board && !validBoard(outcome.payload.base_display_board)) {
      throw new Error('committed base display board is invalid');
    }
    snapshot.events.filter((event) => event.event_type === 'FEATURE_SPIN_RESOLVED').forEach((event) => {
      if (event.payload.display_board && !validBoard(event.payload.display_board)) throw new Error('committed feature display board is invalid');
    });
    return snapshot;
  };

  const connect = async ({ roundId, readbackProvider } = {}) => {
    if (typeof readbackProvider !== 'function') {
      throw new Error('A trusted host-side readback provider is required; browser credentials are not accepted');
    }
    if (typeof roundId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(roundId)) {
      throw new Error('A valid round ID is required');
    }
    // The HMAC secret must remain server-side. The embedding host supplies a
    // same-origin backend-for-frontend callback; this page never receives a key.
    const snapshot = await readbackProvider({ roundId });
    if (snapshot.contract !== 'ganesha.game.events' || snapshot.schema_version !== 1
        || snapshot.round_id !== roundId || !Array.isArray(snapshot.events)) {
      throw new Error('unsupported or mismatched round event contract');
    }
    await verifyRoundProjection(snapshot, roundId);
    renderRoundReadback(snapshot, roundId);

    connection.textContent = 'LOCAL REFERENCE ROUND · NOT PROVIDER';
    connection.setAttribute('aria-live', 'polite');
    status.textContent = 'Host-authenticated server round ' + snapshot.status + ' · ' + snapshot.events.length
      + ' ordered events. Board and lifecycle are read-only server projections; no wager is enabled.';
    return snapshot;
  };

  const restoreExistingRound = async ({ roundId, recover = false } = {}) => {
    if (roundRestoreBusy) throw new Error('a round restore operation is already in progress');
    if (typeof roundId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(roundId)) {
      throw new Error('a valid existing round ID is required before host recovery is requested');
    }
    const host = window.GaneshaHost;
    if (!host || typeof host.readRound !== 'function' || (recover && typeof host.recoverRound !== 'function')) {
      throw new Error('trusted host readRound' + (recover ? ' and recoverRound' : '') + ' bridge is unavailable');
    }
    roundRestoreBusy = true;
    restoreRoundButton.disabled = true;
    recoverRoundButton.disabled = true;
    try {
      const readbackProvider = async ({ roundId: id }) => {
        if (inFlightRoundReads.has(id)) return inFlightRoundReads.get(id);
        const pending = Promise.resolve(host.readRound({ roundId: id }));
        inFlightRoundReads.set(id, pending);
        try { return await pending; } finally { inFlightRoundReads.delete(id); }
      };
      if (recover) {
        const recovery = await host.recoverRound({ roundId });
        if (!recovery || recovery.contract !== 'ganesha.game.recovery' || recovery.schema_version !== 1
            || recovery.round_id !== roundId || recovery.recovered !== true) {
          throw new Error('host recovery response contract is invalid');
        }
        restoreRoundMessage.textContent = 'Recovery result: ' + recovery.status + '. Reloading persisted events…';
      }
      const snapshot = await connect({ roundId, readbackProvider });
      restoreRoundMessage.textContent = 'Verified ' + snapshot.events.length + ' persisted events. Board and payout are read-only server projections.';
      return snapshot;
    } finally {
      roundRestoreBusy = false;
      const available = Boolean(window.GaneshaHost && typeof window.GaneshaHost.readRound === 'function');
      restoreRoundButton.disabled = !available;
      recoverRoundButton.disabled = !(available && typeof window.GaneshaHost.recoverRound === 'function');
    }
  };

  // The embedding host must provide a server-mediated readback callback. No
  // bearer token or HMAC secret is accepted, read, or persisted in this page.
  window.GaneshaRoundState = Object.freeze({ connect });
  window.GaneshaRoundRecovery = Object.freeze({ restore: restoreExistingRound });
  if (restoreRoundButton && recoverRoundButton) {
    const bridgeAvailable = Boolean(window.GaneshaHost && typeof window.GaneshaHost.readRound === 'function');
    if (bridgeAvailable) {
      const requestedRoundId = new URLSearchParams(window.location.search).get('round_id');
      if (requestedRoundId && restoreRoundInput) restoreRoundInput.value = requestedRoundId;
    } else if (restoreRoundMessage) {
      restoreRoundMessage.textContent = 'Disabled: the embedding host must provide server-mediated readRound and recoverRound callbacks. Browser-held secrets are not supported.';
    }
    restoreRoundButton.disabled = !bridgeAvailable;
    recoverRoundButton.disabled = !(bridgeAvailable && typeof window.GaneshaHost.recoverRound === 'function');
    restoreRoundButton.addEventListener('click', async () => {
      try { await restoreExistingRound({ roundId: restoreRoundInput.value.trim() }); }
      catch (error) { restoreRoundMessage.textContent = 'Restore unavailable: ' + error.message; }
    });
    recoverRoundButton.addEventListener('click', async () => {
      try { await restoreExistingRound({ roundId: restoreRoundInput.value.trim(), recover: true }); }
      catch (error) { restoreRoundMessage.textContent = 'Recovery unavailable: ' + error.message; }
    });
  }
  if (demoButton) demoButton.addEventListener('click', playDemo);
  if (engineFixtureButton) engineFixtureButton.addEventListener('click', playEngineFixture);
  if (runtimeButton) runtimeButton.addEventListener('click', playIndependentRuntime);

  if (!endpoint && !providerSessionRequested) {
    connection.textContent = 'LOCAL PREVIEW · API OFFLINE';
    status.textContent = 'Visual preview only. No RGS endpoint configured. Gameplay and purchases are disabled.';
    return;
  }

  const initializeStakeSession = async () => {
    if (!providerSessionRequested) return;
    if (!launchParams.has('sessionID') || !launchParams.has('rgs_url')) {
      connection.textContent = 'STAKE RGS · INVALID LAUNCH';
      stakeSessionStatus.textContent = 'Both sessionID and rgs_url are required';
      return;
    }
    try {
      const { createStakeRgsAdapter } = await import('./stake-rgs-adapter.js');
      stakeAdapter = createStakeRgsAdapter(window.location.href);
      const auth = await stakeAdapter.authenticate();
      stakeBalance.textContent = auth.balance.formatted;
      stakeSessionStatus.textContent = auth.round?.active
        ? 'ACTIVE ROUND ' + auth.round.betID + ' · ' + auth.round.mode + ' · REPLAY REQUIRED · NO AUTO-SETTLEMENT'
        : 'AUTHENTICATED · PLAY AND END-ROUND DISABLED';
      if (stakeReconnectButton) stakeReconnectButton.disabled = false;
      connection.textContent = 'STAKE RGS · AUTHENTICATED · READ ONLY';
      status.textContent = auth.round?.active
        ? 'Stake Engine Authenticate restored an active round. Its opaque state is retained by the adapter, but no canonical replay handler is available; no Event or EndRound request was sent.'
        : 'Stake Engine Authenticate succeeded. SDK lifecycle methods exist behind a disabled financial gate; no Play, Event or EndRound request was sent.';
    } catch (error) {
      connection.textContent = 'STAKE RGS · AUTHENTICATION FAILED';
      stakeSessionStatus.textContent = 'SESSION NOT AUTHENTICATED · NO BET SENT';
      if (stakeReconnectButton) stakeReconnectButton.disabled = !stakeAdapter;
      status.textContent = 'Stake RGS authentication failed. Verify the provider launch session and RGS endpoint. No Play or EndRound request was sent.';
    }
  };

  const reconnectStakeSession = async () => {
    if (stakeReconnectBusy || !stakeAdapter) return;
    stakeReconnectBusy = true;
    if (stakeReconnectButton) stakeReconnectButton.disabled = true;
    stakeSessionStatus.textContent = 'RECONNECTING · FRESH SDK CLIENT · AUTHENTICATE ONLY';
    try {
      const auth = await stakeAdapter.reconnect();
      stakeBalance.textContent = auth.balance.formatted;
      stakeSessionStatus.textContent = auth.round?.active
        ? 'ACTIVE ROUND ' + auth.round.betID + ' · ' + auth.round.mode + ' · REPLAY REQUIRED · NO AUTO-SETTLEMENT'
        : 'AUTHENTICATED · NO ACTIVE ROUND · PLAY DISABLED';
      connection.textContent = 'STAKE RGS · RECONNECTED · READ ONLY';
      status.textContent = auth.round?.active
        ? 'Server reports an active round. The SDK client was recreated and the server state was re-read; replay and settlement remain disabled because no canonical Provider event decoder is available.'
        : 'Fresh Authenticate confirms no active round. No Play retry, Event or EndRound request was sent.';
    } catch (error) {
      stakeSessionStatus.textContent = 'RECONNECT FAILED · ' + error.message;
      connection.textContent = 'STAKE RGS · RECONNECT REQUIRED';
      status.textContent = 'Server state remains unverified. No financial request was retried.';
    } finally {
      stakeReconnectBusy = false;
      if (stakeReconnectButton) stakeReconnectButton.disabled = false;
    }
  };
  if (stakeReconnectButton) stakeReconnectButton.addEventListener('click', reconnectStakeSession);

  if (endpoint && !providerSessionRequested) {
    fetch(endpoint + '/health', { credentials: 'omit', cache: 'no-store', redirect: 'error' })
      .then((response) => {
        if (!response.ok) throw new Error('health check ' + response.status);
        return response.json();
      })
      .then((health) => {
        if (health.environment !== 'local-development' || health.provider_connected !== false) {
          throw new Error('unexpected adapter environment');
        }
        if (providerSessionRequested) return;
        connection.textContent = 'LOCAL REFERENCE API · NO PROVIDER';
        status.textContent = health.round_api_enabled === false
          ? (health.game_fixture_api_enabled === true
            ? 'Scripted Demo and GameEngine test-fixture playback are available. The fixture uses fixed outcomes only; no RNG, canonical Math, Wallet or financial Round API is enabled.'
            : health.demo_api_enabled === true
              ? 'Scripted visual demo is available. Financial round API is disabled; no wallet, wager, RNG outcome or payout can be created.'
              : 'Local static preview server is reachable. The round API is disabled; no wallet, wager or outcome can be created from this page.')
          : 'Local read-only round-state integration is available to an authenticated host. Wager and Buy controls remain disabled because canonical Math and Provider contracts are not approved.';
        demoApiAvailable = health.demo_api_enabled === true && config.demoApiEnabled === true;
        gameFixtureApiAvailable = health.game_fixture_api_enabled === true && config.gameFixtureApiEnabled === true;
        runtimeApiAvailable = health.runtime_api_enabled === true && config.runtimeApiEnabled === true;
        if (demoButton) demoButton.disabled = !demoApiAvailable;
        if (engineFixtureButton) engineFixtureButton.disabled = !gameFixtureApiAvailable;
        if (runtimeButton) runtimeButton.disabled = !runtimeApiAvailable;
      })
      .catch((error) => {
        if (providerSessionRequested) return;
        connection.textContent = 'LOCAL PREVIEW · API UNAVAILABLE';
        status.textContent = 'Visual preview only. Local API check failed: ' + error.message + '. All gameplay controls remain disabled.';
      });
  } else if (!providerSessionRequested) {
    connection.textContent = 'OFFLINE PREVIEW · NO PROVIDER';
    status.textContent = 'Static offline preview. No API, session, wallet, wager, outcome or payout is connected.';
  }
  initializeStakeSession();
})();
