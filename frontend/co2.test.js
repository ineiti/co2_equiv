import { describe, it, expect, vi } from 'vitest';
import {
  parseCo2,
  toDistances,
  formatHistoryTimestamp,
  buildShareUrl,
  buildShareText,
  normalizeMastodonInstance,
  parseSseChunk,
  consumeEventStream,
} from './co2.js';

describe('parseCo2', () => {
  it('parses a positive kg value', () => {
    expect(parseCo2('4.3kg')).toBe(4.3);
  });

  it('parses a negative kg value', () => {
    expect(parseCo2('-6.8kg')).toBe(-6.8);
  });

  it('returns null for unknown', () => {
    expect(parseCo2('unknown')).toBeNull();
  });

  it('returns null for unparseable strings', () => {
    expect(parseCo2('abc')).toBeNull();
    expect(parseCo2('')).toBeNull();
    expect(parseCo2(undefined)).toBeNull();
  });
});

describe('toDistances', () => {
  it('computes plane/car/train distances from a positive kg value', () => {
    const d = toDistances(4.3);
    expect(d.plane).toBeCloseTo(4.3 / 0.15, 5);
    expect(d.car).toBeCloseTo(4.3 / 0.17, 5);
    expect(d.train).toBeCloseTo(4.3 / 0.035, 5);
  });

  it('computes negative distances for negative kg (savings)', () => {
    const d = toDistances(-6.8);
    expect(d.plane).toBeLessThan(0);
    expect(d.car).toBeLessThan(0);
    expect(d.train).toBeLessThan(0);
  });

  it('returns zero distances for zero kg', () => {
    const d = toDistances(0);
    expect(d.plane).toBe(0);
    expect(d.car).toBe(0);
    expect(d.train).toBe(0);
  });
});

describe('formatHistoryTimestamp', () => {
  it('formats an ISO timestamp as a locale date-time string', () => {
    const isoString = '2026-10-04T12:30:00.000Z';
    expect(formatHistoryTimestamp(isoString)).toBe(new Date(isoString).toLocaleString());
  });

  it('returns empty string for an invalid timestamp', () => {
    expect(formatHistoryTimestamp('not-a-date')).toBe('');
  });
});

describe('buildShareUrl', () => {
  it('encodes the text as a text query param on the given origin', () => {
    expect(buildShareUrl('https://example.com', 'drove 25km')).toBe(
      'https://example.com/?text=drove%2025km',
    );
  });

  it('encodes special characters safely', () => {
    expect(buildShareUrl('https://example.com', 'a & b?')).toBe(
      'https://example.com/?text=a%20%26%20b%3F',
    );
  });
});

describe('buildShareText', () => {
  it('joins the original text, the co2 result, and the share link on separate lines', () => {
    expect(buildShareText('drove 25km', '4.3kg', 'https://example.com/?text=drove%2025km')).toBe(
      'drove 25km → 4.3kg CO2e\nhttps://example.com/?text=drove%2025km',
    );
  });
});

describe('normalizeMastodonInstance', () => {
  it('passes through a bare domain', () => {
    expect(normalizeMastodonInstance('mastodon.social')).toBe('mastodon.social');
  });

  it('trims whitespace', () => {
    expect(normalizeMastodonInstance('  mastodon.social  ')).toBe('mastodon.social');
  });

  it('strips an https:// scheme', () => {
    expect(normalizeMastodonInstance('https://mastodon.social')).toBe('mastodon.social');
  });

  it('strips an http:// scheme', () => {
    expect(normalizeMastodonInstance('http://mastodon.social')).toBe('mastodon.social');
  });

  it('strips a trailing slash and path', () => {
    expect(normalizeMastodonInstance('mastodon.social/@someone')).toBe('mastodon.social');
    expect(normalizeMastodonInstance('mastodon.social/')).toBe('mastodon.social');
  });

  it('strips a leading @user@ handle prefix', () => {
    expect(normalizeMastodonInstance('@me@mastodon.social')).toBe('mastodon.social');
  });

  it('returns empty string for input without a dot', () => {
    expect(normalizeMastodonInstance('notadomain')).toBe('');
  });

  it('returns empty string for empty or missing input', () => {
    expect(normalizeMastodonInstance('')).toBe('');
    expect(normalizeMastodonInstance(null)).toBe('');
  });
});

describe('parseSseChunk', () => {
  it('parses a single complete event', () => {
    const result = parseSseChunk('event: reasoning\ndata: hello\n\n');
    expect(result.events).toEqual([{ type: 'reasoning', data: 'hello' }]);
    expect(result.remainder).toBe('');
  });

  it('parses multiple complete events in one buffer', () => {
    const result = parseSseChunk('event: reasoning\ndata: one\n\nevent: reasoning\ndata: two\n\n');
    expect(result.events).toEqual([
      { type: 'reasoning', data: 'one' },
      { type: 'reasoning', data: 'two' },
    ]);
    expect(result.remainder).toBe('');
  });

  it('leaves an incomplete trailing event in remainder', () => {
    const result = parseSseChunk('event: reasoning\ndata: one\n\nevent: reasoning\ndata: tw');
    expect(result.events).toEqual([{ type: 'reasoning', data: 'one' }]);
    expect(result.remainder).toBe('event: reasoning\ndata: tw');
  });

  it('completes an event split across two calls when remainder is prepended', () => {
    const first = parseSseChunk('event: reasoning\ndata: hel');
    expect(first.events).toEqual([]);
    expect(first.remainder).toBe('event: reasoning\ndata: hel');

    const second = parseSseChunk(first.remainder + 'lo\n\n');
    expect(second.events).toEqual([{ type: 'reasoning', data: 'hello' }]);
    expect(second.remainder).toBe('');
  });

  it('ignores a buffer with no complete event', () => {
    const result = parseSseChunk('event: result');
    expect(result.events).toEqual([]);
    expect(result.remainder).toBe('event: result');
  });

  it('returns no events for an empty buffer', () => {
    const result = parseSseChunk('');
    expect(result.events).toEqual([]);
    expect(result.remainder).toBe('');
  });
});

function sseResponse(chunks) {
  const stream = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
      controller.close();
    },
  });
  return new Response(stream);
}

describe('consumeEventStream', () => {
  it('resolves with the result payload when a result event arrives', async () => {
    const response = sseResponse(['event: result\ndata: {"co2": "1kg"}\n\n']);
    const reasoning = vi.fn();
    const outcome = await consumeEventStream(response, { reasoning });
    expect(outcome).toEqual({ type: 'result', data: { co2: '1kg' } });
    expect(reasoning).not.toHaveBeenCalled();
  });

  it('calls the reasoning handler for each reasoning event before resolving', async () => {
    const response = sseResponse([
      'event: reasoning\ndata: "a"\n\n',
      'event: reasoning\ndata: "b"\n\n',
      'event: result\ndata: {"co2": "1kg"}\n\n',
    ]);
    const seen = [];
    await consumeEventStream(response, { reasoning: (d) => seen.push(d) });
    expect(seen).toEqual(['a', 'b']);
  });

  it('calls the restart handler when a restart event arrives', async () => {
    const response = sseResponse([
      'event: reasoning\ndata: "a"\n\n',
      'event: restart\ndata: null\n\n',
      'event: reasoning\ndata: "b"\n\n',
      'event: result\ndata: {"co2": "1kg"}\n\n',
    ]);
    const restart = vi.fn();
    await consumeEventStream(response, { restart });
    expect(restart).toHaveBeenCalledTimes(1);
  });

  it('rejects when an error event arrives', async () => {
    const response = sseResponse(['event: error\ndata: "boom"\n\n']);
    await expect(consumeEventStream(response, {})).rejects.toThrow('boom');
  });

  it('rejects when the stream ends with no result or error event', async () => {
    const response = sseResponse(['event: reasoning\ndata: "a"\n\n']);
    await expect(consumeEventStream(response, {})).rejects.toThrow('stream ended without a result');
  });

  it('reassembles an event split across two stream reads', async () => {
    const response = sseResponse([
      'event: reasoning\ndata: "hel',
      'lo"\n\n',
      'event: result\ndata: {"co2": "1kg"}\n\n',
    ]);
    const seen = [];
    await consumeEventStream(response, { reasoning: (d) => seen.push(d) });
    expect(seen).toEqual(['hello']);
  });

  it('stops dispatching once the given signal is aborted', async () => {
    const controller = new AbortController();
    const response = sseResponse([
      'event: reasoning\ndata: "a"\n\n',
      'event: reasoning\ndata: "b"\n\n',
      'event: result\ndata: {"co2": "1kg"}\n\n',
    ]);
    const seen = [];
    const promise = consumeEventStream(
      response,
      {
        reasoning: (d) => {
          seen.push(d);
          if (d === 'a') controller.abort();
        },
      },
      controller.signal,
    );
    await expect(promise).rejects.toThrow('aborted');
    expect(seen).toEqual(['a']);
  });
});
