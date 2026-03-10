/* ────────────────────────────────────────────────────────────────
   OBS Live Translator — Frontend Controller
   ──────────────────────────────────────────────────────────────── */

(() => {
  'use strict';

  // ── DOM refs ──────────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const connectionDot  = $('#connectionDot');
  const statusIcon     = $('#statusIcon');
  const statusEmoji    = $('#statusEmoji');
  const statusLabel    = $('#statusLabel');
  const statusPill     = $('#statusPill');
  const statusPillText = $('#statusPillText');
  const statusDetail   = $('#statusDetail');
  const btnStart       = $('#btnStart');
  const btnStop        = $('#btnStop');
  const btnSettings    = $('#btnSettings');
  const btnClear       = $('#btnClear');
  const btnSave        = $('#btnSaveSettings');
  const feedList       = $('#feedList');
  const feedEmpty      = $('#feedEmpty');
  const settingsSheet  = $('#settingsSheet');
  const sheetBackdrop  = $('#sheetBackdrop');
  const settingsForm   = $('#settingsForm');

  // ── State ─────────────────────────────────────────────────────
  let ws = null;
  let reconnectTimer = null;
  let engineState = 'stopped';
  const RECONNECT_DELAY = 2000;
  const MAX_FEED_ITEMS = 100;

  // ── WebSocket ─────────────────────────────────────────────────

  function getWsUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/ws`;
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    setConnectionState('connecting');

    try {
      ws = new WebSocket(getWsUrl());
    } catch (e) {
      setConnectionState('disconnected');
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      setConnectionState('connected');
      clearTimeout(reconnectTimer);
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        handleMessage(msg);
      } catch (e) {
        console.warn('Invalid message:', evt.data);
      }
    };

    ws.onclose = () => {
      setConnectionState('disconnected');
      scheduleReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  function scheduleReconnect() {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
  }

  function send(type, payload = {}) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type, ...payload }));
    }
  }

  // ── Message Handler ───────────────────────────────────────────

  function handleMessage(msg) {
    switch (msg.type) {
      case 'status':
        updateEngineState(msg.state, msg.error, msg.dropped_chunks);
        break;

      case 'result':
        addSubtitleEntry({
          original: msg.original ?? '',
          translation: msg.translation ?? '',
          language: msg.language ?? '',
          latencyMs: Number.isFinite(msg.latency_ms) ? msg.latency_ms : 0,
        });
        break;

      case 'config':
        populateSettings(msg);
        break;

      default:
        console.log('Unknown message type:', msg.type);
    }
  }

  // ── Engine State UI ───────────────────────────────────────────

  const STATE_MAP = {
    starting: { emoji: '⏳', label: 'Starting',  pillClass: 'pill--idle',  pillText: 'Initializing', detail: 'Loading models…' },
    running:  { emoji: '🎙', label: 'Running',   pillClass: 'pill--live',  pillText: 'Live',         detail: 'Listening for speech' },
    stopping: { emoji: '⏳', label: 'Stopping',  pillClass: 'pill--idle',  pillText: 'Stopping',     detail: 'Shutting down…' },
    stopped:  { emoji: '⏸', label: 'Stopped',   pillClass: 'pill--idle',  pillText: 'Idle',         detail: 'Waiting to start' },
    failed:   { emoji: '⚠', label: 'Failed',    pillClass: 'pill--error', pillText: 'Error',        detail: 'Engine encountered an error' },
  };

  function updateEngineState(state, error, droppedChunks) {
    engineState = state;
    const info = STATE_MAP[state] || STATE_MAP.stopped;

    statusEmoji.textContent = info.emoji;
    statusIcon.setAttribute('data-state', state);
    statusLabel.textContent = info.label;

    // Update pill
    statusPill.className = `pill ${info.pillClass}`;
    statusPillText.textContent = info.pillText;

    // Detail
    if (error) {
      statusDetail.textContent = error;
    } else if (droppedChunks > 0) {
      statusDetail.textContent = `${info.detail} · ${droppedChunks} chunks dropped`;
    } else {
      statusDetail.textContent = info.detail;
    }

    // Button states
    btnStart.disabled = ['starting', 'running', 'stopping'].includes(state);
    btnStop.disabled = !['starting', 'running'].includes(state);
  }

  // ── Connection State UI ───────────────────────────────────────

  function setConnectionState(state) {
    connectionDot.setAttribute('data-state', state);
    const labels = { connected: 'Connected', connecting: 'Connecting…', disconnected: 'Disconnected' };
    connectionDot.title = `WebSocket ${labels[state] || state}`;
  }

  // ── Subtitle Feed ─────────────────────────────────────────────

  function addSubtitleEntry({ original, translation, language, latencyMs }) {
    // Remove empty placeholder
    if (feedEmpty) {
      feedEmpty.style.display = 'none';
    }

    const li = document.createElement('li');
    li.className = 'subtitle-entry';

    const langBadge = language ? `<span class="subtitle-entry__lang">${escapeHtml(language)}</span>` : '';
    const latencyStr = latencyMs > 0 ? `<span class="latency-badge">${Math.round(latencyMs)} ms</span>` : '';
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    li.innerHTML = `
      ${original ? `<div class="subtitle-entry__original">${escapeHtml(original)}</div>` : ''}
      <div class="subtitle-entry__translation">${escapeHtml(translation || original)}</div>
      <div class="subtitle-entry__meta">
        ${langBadge}
        ${latencyStr}
        <span>${time}</span>
      </div>
    `;

    feedList.appendChild(li);

    // Cap list length
    while (feedList.children.length > MAX_FEED_ITEMS + 1) {
      const first = feedList.querySelector('.subtitle-entry');
      if (first) first.remove();
    }

    // Smooth scroll to bottom
    requestAnimationFrame(() => {
      feedList.scrollTo({ top: feedList.scrollHeight, behavior: 'smooth' });
    });
  }

  function clearFeed() {
    feedList.querySelectorAll('.subtitle-entry').forEach((el) => {
      el.style.animation = 'none';
      el.style.transition = `opacity ${150}ms ease, transform ${150}ms ease`;
      el.style.opacity = '0';
      el.style.transform = 'scale(0.95)';
      setTimeout(() => el.remove(), 160);
    });
    setTimeout(() => {
      if (feedEmpty) feedEmpty.style.display = '';
    }, 200);
  }

  // ── Settings Sheet ────────────────────────────────────────────

  function openSettings() {
    settingsSheet.classList.add('is-open');
    sheetBackdrop.classList.add('is-open');
    document.body.style.overflow = 'hidden';
    // Request current config from server
    send('get_config');
  }

  function closeSettings() {
    settingsSheet.classList.remove('is-open');
    sheetBackdrop.classList.remove('is-open');
    document.body.style.overflow = '';
  }

  function populateSettings(config) {
    if (config.asr_model)          $('#asrModel').value = config.asr_model;
    if (config.asr_language)       $('#asrLanguage').value = config.asr_language;
    if (config.target_lang)        $('#targetLang').value = config.target_lang;
    if (config.translation_model)  $('#translationModel').value = config.translation_model;
    if (config.model_cache_dir)    $('#modelCacheDir').value = config.model_cache_dir;
    $('#offlineOnly').checked = !!config.offline_only;
    $('#trustRemoteCode').checked = config.trust_remote_code !== false;
  }

  function saveSettings(e) {
    e.preventDefault();
    send('config', {
      asr_model: $('#asrModel').value || undefined,
      asr_language: $('#asrLanguage').value || undefined,
      target_lang: $('#targetLang').value || undefined,
      translation_model: $('#translationModel').value || undefined,
      model_cache_dir: $('#modelCacheDir').value || undefined,
      offline_only: $('#offlineOnly').checked,
      trust_remote_code: $('#trustRemoteCode').checked,
    });
    closeSettings();
  }

  // ── Utility ───────────────────────────────────────────────────

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Event Listeners ───────────────────────────────────────────

  btnStart.addEventListener('click', () => {
    send('start');
    updateEngineState('starting');
  });

  btnStop.addEventListener('click', () => {
    send('stop');
    updateEngineState('stopping');
  });

  btnSettings.addEventListener('click', openSettings);
  sheetBackdrop.addEventListener('click', closeSettings);
  btnClear.addEventListener('click', clearFeed);
  settingsForm.addEventListener('submit', saveSettings);

  // Close sheet on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && settingsSheet.classList.contains('is-open')) {
      closeSettings();
    }
  });

  // ── Init ──────────────────────────────────────────────────────

  connect();
})();
