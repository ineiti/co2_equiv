import { describe, it, expect } from 'vitest';
import { parseCo2, toDistances } from './co2.js';

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
