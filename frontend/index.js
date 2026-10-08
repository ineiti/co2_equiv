import {
  parseCo2,
  toDistances,
  formatHistoryTimestamp,
  buildShareUrl,
  buildShareText,
  normalizeMastodonInstance,
  consumeEventStream,
} from './co2.js';

const MAX_HISTORY_ENTRIES = 10;
const MASTODON_INSTANCE_KEY = 'mastodonInstance';

const form = document.getElementById('estimate-form');
const input = document.getElementById('text-input');
const inputError = document.getElementById('input-error');
const loading = document.getElementById('loading');
const reasoningPanel = document.getElementById('reasoning-panel');
const reasoningToggle = document.getElementById('reasoning-toggle');
const reasoningText = document.getElementById('reasoning-text');
const result = document.getElementById('result');
const fetchError = document.getElementById('fetch-error');
const calcText = document.getElementById('calc-text');
const co2Text = document.getElementById('co2-text');
const planeDistance = document.getElementById('plane-distance');
const carDistance = document.getElementById('car-distance');
const trainDistance = document.getElementById('train-distance');
const historySection = document.getElementById('history');
const historyList = document.getElementById('history-list');
const shareButtons = document.getElementById('share-buttons');
const shareMastodon = document.getElementById('share-mastodon');
const shareThreads = document.getElementById('share-threads');
const shareLinkedin = document.getElementById('share-linkedin');

let historyEntries = [];
let currentShare = null;

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

let reasoningCollapsed = false;

function resetReasoningPanel() {
  reasoningText.textContent = '';
  reasoningPanel.hidden = true;
  reasoningPanel.classList.remove('collapsed');
  reasoningCollapsed = false;
}

function appendReasoning(delta) {
  if (reasoningPanel.hidden) {
    reasoningPanel.hidden = false;
  }
  reasoningText.textContent += delta;
  reasoningText.scrollTop = reasoningText.scrollHeight;
}

function collapseReasoningPanel() {
  if (!reasoningPanel.hidden && !reasoningCollapsed) {
    reasoningPanel.classList.add('collapsed');
    reasoningCollapsed = true;
  }
}

reasoningToggle.addEventListener('click', () => {
  reasoningPanel.classList.toggle('collapsed');
  reasoningCollapsed = reasoningPanel.classList.contains('collapsed');
});

function renderResult(text, data, save) {
  const kg = parseCo2(data.co2);

  if (kg === null) {
    calcText.textContent = '';
    co2Text.textContent = "Couldn't estimate that — try describing it differently.";
    planeDistance.textContent = '';
    carDistance.textContent = '';
    trainDistance.textContent = '';
    currentShare = null;
    shareButtons.hidden = true;
    showState({ showResult: true });
    return;
  }

  const distances = toDistances(kg);
  calcText.textContent = data.calc ?? '';
  co2Text.textContent = `${kg}kg CO2e`;
  planeDistance.textContent = formatDistance(distances.plane);
  carDistance.textContent = formatDistance(distances.car);
  trainDistance.textContent = formatDistance(distances.train);
  currentShare = { text, co2: data.co2 };
  shareButtons.hidden = false;
  showState({ showResult: true });
  if (save) {
    addToHistory({ text, calc: data.calc, co2: data.co2, timestamp: new Date().toISOString() });
  }
}

let currentRunController = null;

async function runEstimate(text, { save, showReasoning = true }) {
  currentRunController?.abort();
  const controller = new AbortController();
  currentRunController = controller;

  showState({ showLoading: true });
  resetReasoningPanel();

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
          appendReasoning(delta);
        },
        restart: () => {
          if (!showReasoning) return;
          resetReasoningPanel();
          loading.hidden = false;
        },
      },
      controller.signal,
    );
    collapseReasoningPanel();
    renderResult(text, outcome.data, save);
  } catch (err) {
    if (err.name === 'AbortError' || controller.signal.aborted) return;
    resetReasoningPanel();
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
