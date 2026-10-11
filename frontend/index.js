import {
  parseCo2,
  toDistances,
  SOURCES,
  DEFAULT_SOURCE,
  formatHistoryTimestamp,
  buildShareUrl,
  buildShareText,
  normalizeMastodonInstance,
  consumeEventStream,
} from './co2.js';

const MAX_HISTORY_ENTRIES = 10;
const MASTODON_INSTANCE_KEY = 'mastodonInstance';
const SOURCE_KEY = 'co2Source';

const form = document.getElementById('estimate-form');
const input = document.getElementById('text-input');
const inputError = document.getElementById('input-error');
const loading = document.getElementById('loading');
const reasoningPanel = document.getElementById('reasoning-panel');
const reasoningToggle = document.getElementById('reasoning-toggle');
const reasoningText = document.getElementById('reasoning-text');
const answerPanel = document.getElementById('answer-panel');
const answerToggle = document.getElementById('answer-toggle');
const answerText = document.getElementById('answer-text');
const result = document.getElementById('result');
const fetchError = document.getElementById('fetch-error');
const calcText = document.getElementById('calc-text');
const co2Text = document.getElementById('co2-text');
const planeDistance = document.getElementById('plane-distance');
const carDistance = document.getElementById('car-distance');
const trainDistance = document.getElementById('train-distance');
const sourceSwitch = document.getElementById('source-switch');
const sourceLink = document.getElementById('source-link');
const sourceDescription = document.getElementById('source-description');
const historySection = document.getElementById('history');
const historyList = document.getElementById('history-list');
const shareButtons = document.getElementById('share-buttons');
const shareMastodon = document.getElementById('share-mastodon');
const shareThreads = document.getElementById('share-threads');
const shareLinkedin = document.getElementById('share-linkedin');

let historyEntries = [];
let currentShare = null;
let currentKg = null;
let currentSource = loadSource();

function loadSource() {
  try {
    const stored = localStorage.getItem(SOURCE_KEY);
    if (stored && SOURCES[stored]) return stored;
  } catch {
    // storage may be unavailable (private mode); fall back to the default
  }
  return DEFAULT_SOURCE;
}

function renderDistances() {
  const source = SOURCES[currentSource];
  for (const button of sourceSwitch.children) {
    button.setAttribute('aria-checked', String(button.dataset.source === currentSource));
  }
  sourceLink.href = source.url;
  sourceLink.textContent = source.label;
  sourceDescription.textContent = `— ${source.description}.`;
  if (currentKg === null) return;
  const distances = toDistances(currentKg, currentSource);
  planeDistance.textContent = formatDistance(distances.plane);
  carDistance.textContent = formatDistance(distances.car);
  trainDistance.textContent = formatDistance(distances.train);
}

function setSource(id) {
  currentSource = id;
  try {
    localStorage.setItem(SOURCE_KEY, id);
  } catch {
    // non-essential persistence
  }
  renderDistances();
}

for (const [id, source] of Object.entries(SOURCES)) {
  const button = document.createElement('button');
  button.type = 'button';
  button.setAttribute('role', 'radio');
  button.dataset.source = id;
  button.textContent = source.label;
  button.addEventListener('click', () => setSource(id));
  sourceSwitch.appendChild(button);
}

function renderHistory() {
  historySection.hidden = historyEntries.length === 0;
  historyList.innerHTML = '';
  for (const entry of historyEntries) {
    const item = document.createElement('li');
    const time = formatHistoryTimestamp(entry.timestamp);
    item.textContent = `${entry.text} — ${entry.co2}${time ? ` (${time})` : ''}`;
    historyList.appendChild(item);
  }
}

async function loadHistory() {
  try {
    const response = await fetch('/api/history');
    if (!response.ok) return;
    historyEntries = await response.json();
    renderHistory();
  } catch {
    // history is a non-essential enhancement; ignore failures
  }
}

function addToHistory(entry) {
  historyEntries = [entry, ...historyEntries].slice(0, MAX_HISTORY_ENTRIES);
  renderHistory();
}

loadHistory();

function formatDistance(km) {
  const rounded = Math.round(Math.abs(km));
  const sign = km < 0 ? 'saved ' : '';
  return `${sign}${rounded} km`;
}

function showState({
  showLoading = false,
  showResult = false,
  showInputError = false,
  showFetchError = false,
}) {
  loading.hidden = !showLoading;
  result.hidden = !showResult;
  inputError.hidden = !showInputError;
  fetchError.hidden = !showFetchError;
}

function makeLivePanel(panel, textEl) {
  let collapsed = false;
  return {
    reset() {
      textEl.textContent = '';
      panel.hidden = true;
      panel.classList.remove('collapsed');
      collapsed = false;
    },
    append(delta) {
      if (panel.hidden) {
        panel.hidden = false;
      }
      textEl.textContent += delta;
      textEl.scrollTop = textEl.scrollHeight;
    },
    collapse() {
      if (!panel.hidden && !collapsed) {
        panel.classList.add('collapsed');
        collapsed = true;
      }
    },
    toggle() {
      panel.classList.toggle('collapsed');
      collapsed = panel.classList.contains('collapsed');
    },
  };
}

const reasoningLivePanel = makeLivePanel(reasoningPanel, reasoningText);
const answerLivePanel = makeLivePanel(answerPanel, answerText);

reasoningToggle.addEventListener('click', () => reasoningLivePanel.toggle());
answerToggle.addEventListener('click', () => answerLivePanel.toggle());

function renderResult(text, data, save) {
  const kg = parseCo2(data.co2);

  if (kg === null) {
    calcText.textContent = '';
    co2Text.textContent = "Couldn't estimate that — try describing it differently.";
    currentKg = null;
    planeDistance.textContent = '';
    carDistance.textContent = '';
    trainDistance.textContent = '';
    currentShare = null;
    shareButtons.hidden = true;
    showState({ showResult: true });
    return;
  }

  calcText.textContent = data.calc ?? '';
  co2Text.textContent = `${kg}kg CO2e`;
  currentKg = kg;
  renderDistances();
  currentShare = { text, co2: data.co2 };
  shareButtons.hidden = false;
  showState({ showResult: true });
  if (save) {
    addToHistory({ text, calc: data.calc, co2: data.co2, timestamp: new Date().toISOString() });
  }
}

renderDistances();

let currentRunController = null;

async function runEstimate(text, { save, showReasoning = true }) {
  currentRunController?.abort();
  const controller = new AbortController();
  currentRunController = controller;

  showState({ showLoading: true });
  reasoningLivePanel.reset();
  answerLivePanel.reset();

  try {
    const response = await fetch('/api/estimate/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, save }),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`request failed: ${response.status}`);
    }

    const outcome = await consumeEventStream(
      response,
      {
        reasoning: (delta) => {
          if (!showReasoning) return;
          loading.hidden = true;
          reasoningLivePanel.append(delta);
        },
        answer: (delta) => {
          if (!showReasoning) return;
          loading.hidden = true;
          answerLivePanel.append(delta);
        },
        restart: () => {
          if (!showReasoning) return;
          reasoningLivePanel.reset();
          answerLivePanel.reset();
          loading.hidden = false;
        },
      },
      controller.signal,
    );
    reasoningLivePanel.collapse();
    answerLivePanel.collapse();
    renderResult(text, outcome.data, save);
  } catch (err) {
    if (err.name === 'AbortError' || controller.signal.aborted) return;
    reasoningLivePanel.reset();
    answerLivePanel.reset();
    showState({ showFetchError: true });
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const text = input.value.trim();

  if (!text) {
    showState({ showInputError: true });
    return;
  }

  runEstimate(text, { save: true });
});

function getShareLink() {
  const shareUrl = buildShareUrl(location.origin, currentShare.text);
  return buildShareText(currentShare.text, currentShare.co2, shareUrl);
}

shareMastodon.addEventListener('click', (event) => {
  if (!currentShare) return;
  const stored = localStorage.getItem(MASTODON_INSTANCE_KEY);
  let instance = normalizeMastodonInstance(stored);
  // Shift-click re-prompts, so a wrong/stale instance isn't stuck forever.
  if (!instance || event.shiftKey) {
    const typed = prompt('Your Mastodon instance (e.g. mastodon.social):', stored ?? '');
    instance = normalizeMastodonInstance(typed);
    if (!instance) {
      localStorage.removeItem(MASTODON_INSTANCE_KEY);
      return;
    }
    localStorage.setItem(MASTODON_INSTANCE_KEY, instance);
  }
  const url = `https://${instance}/share?text=${encodeURIComponent(getShareLink())}`;
  window.open(url, '_blank', 'noopener');
});

shareThreads.addEventListener('click', () => {
  if (!currentShare) return;
  const url = `https://www.threads.com/intent/post?text=${encodeURIComponent(getShareLink())}`;
  window.open(url, '_blank', 'noopener');
});

shareLinkedin.addEventListener('click', () => {
  if (!currentShare) return;
  const shareUrl = buildShareUrl(location.origin, currentShare.text);
  const url = `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(shareUrl)}`;
  window.open(url, '_blank', 'noopener');
});

function runFromQueryParam() {
  const params = new URLSearchParams(location.search);
  const text = params.get('text')?.trim();
  if (!text) return;

  history.replaceState(null, '', location.pathname);
  input.value = text;
  runEstimate(text, { save: false, showReasoning: false });
}

runFromQueryParam();
