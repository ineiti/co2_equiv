import { parseCo2, toDistances } from './co2.js';

const form = document.getElementById('estimate-form');
const input = document.getElementById('text-input');
const inputError = document.getElementById('input-error');
const loading = document.getElementById('loading');
const result = document.getElementById('result');
const fetchError = document.getElementById('fetch-error');
const calcText = document.getElementById('calc-text');
const co2Text = document.getElementById('co2-text');
const planeDistance = document.getElementById('plane-distance');
const carDistance = document.getElementById('car-distance');
const trainDistance = document.getElementById('train-distance');

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

async function submitEstimate(text) {
  const response = await fetch('/api/estimate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status}`);
  }
  return response.json();
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = input.value.trim();

  if (!text) {
    showState({ showInputError: true });
    return;
  }

  showState({ showLoading: true });

  try {
    const data = await submitEstimate(text);
    const kg = parseCo2(data.co2);

    if (kg === null) {
      calcText.textContent = '';
      co2Text.textContent = "Couldn't estimate that — try describing it differently.";
      planeDistance.textContent = '';
      carDistance.textContent = '';
      trainDistance.textContent = '';
      showState({ showResult: true });
      return;
    }

    const distances = toDistances(kg);
    calcText.textContent = data.calc ?? '';
    co2Text.textContent = `${kg}kg CO2e`;
    planeDistance.textContent = formatDistance(distances.plane);
    carDistance.textContent = formatDistance(distances.car);
    trainDistance.textContent = formatDistance(distances.train);
    showState({ showResult: true });
  } catch (err) {
    showState({ showFetchError: true });
  }
});
