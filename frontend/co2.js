const FACTORS = {
  plane: 0.15,
  car: 0.17,
  train: 0.035,
};

export function parseCo2(co2String) {
  if (typeof co2String !== 'string') return null;
  const match = co2String.match(/^(-?\d+(\.\d+)?)kg$/);
  if (!match) return null;
  return parseFloat(match[1]);
}

export function toDistances(kgCo2) {
  return {
    plane: kgCo2 / FACTORS.plane,
    car: kgCo2 / FACTORS.car,
    train: kgCo2 / FACTORS.train,
  };
}

export function formatHistoryTimestamp(isoString) {
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return '';
  return date.toLocaleString();
}

export function buildShareUrl(origin, text) {
  return `${origin}/?text=${encodeURIComponent(text)}`;
}

export function buildShareText(text, co2, shareUrl) {
  return `${text} → ${co2} CO2e\n${shareUrl}`;
}

export function normalizeMastodonInstance(input) {
  if (typeof input !== 'string') return '';
  let instance = input.trim();
  instance = instance.replace(/^https?:\/\//i, '');
  instance = instance.replace(/^@[^@/]+@/, '');
  instance = instance.replace(/\/.*$/, '');
  if (!instance.includes('.')) return '';
  return instance;
}

export function parseSseChunk(buffer) {
  const events = [];
  let remainder = buffer;

  while (true) {
    const boundary = remainder.indexOf('\n\n');
    if (boundary === -1) break;

    const rawEvent = remainder.slice(0, boundary);
    remainder = remainder.slice(boundary + 2);

    let type = null;
    let data = null;
    for (const line of rawEvent.split('\n')) {
      if (line.startsWith('event: ')) type = line.slice('event: '.length);
      else if (line.startsWith('data: ')) data = line.slice('data: '.length);
    }
    if (type !== null && data !== null) {
      events.push({ type, data });
    }
  }

  return { events, remainder };
}

// Consumes an SSE Response produced by POST /api/estimate/stream. Dispatches
// `reasoning`/`restart` events to the matching handler as they arrive, then
// resolves with the terminal `result` event's payload, or rejects on an
// `error` event or if the stream ends without either. If `signal` aborts,
// stops dispatching further events and rejects immediately - the caller is
// responsible for ignoring/discarding that rejection if it was intentional.
export async function consumeEventStream(response, handlers, signal) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      if (signal?.aborted) {
        throw new Error('stream consumption aborted');
      }
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { events, remainder } = parseSseChunk(buffer);
      buffer = remainder;
      for (const event of events) {
        if (signal?.aborted) {
          throw new Error('stream consumption aborted');
        }
        const data = JSON.parse(event.data);
        if (event.type === 'result') {
          return { type: 'result', data };
        }
        if (event.type === 'error') {
          throw new Error(typeof data === 'string' ? data : 'stream reported an error');
        }
        handlers[event.type]?.(data);
      }
    }
  } finally {
    reader.releaseLock?.();
  }

  throw new Error('stream ended without a result or error event');
}
