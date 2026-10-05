import { describe, it, expect } from 'vitest';
import {
  parseCo2,
  toDistances,
  formatHistoryTimestamp,
  buildShareUrl,
  buildShareText,
  normalizeMastodonInstance,
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
