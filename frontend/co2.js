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
