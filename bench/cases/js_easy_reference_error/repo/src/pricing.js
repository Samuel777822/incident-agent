// Pricing rules: discounts, tax and shipping.
export const TAX_RATE = 0.18;

export function round2(value) {
  return Math.round(value * 100) / 100;
}

export function applyDiscount(price, pct) {
  if (pct < 0 || pct > 100) {
    throw new RangeError('discount must be between 0 and 100');
  }
  return round2(price - (price * pct) / 100);
}

export function addTax(price) {
  return round2(price * (1 + TAX_RATE));
}

export function shippingCost(weightKg) {
  if (weightKg <= 0) {
    throw new RangeError('weight must be positive');
  }
  return weightKg <= 1 ? 40 : 40 + 25 * (weightKg - 1);
}

export function lineTotal(unitPrice, qty, discountPct = 0) {
  return round2(applyDiscount(unitPrice, discountPct) * qty);
}
