// Order creation: checks stock, prices the line, reserves the items.
import { CATALOG } from './catalog.js';
import { getStock, OutOfStock, reserve } from './inventory.js';
import { addTax, lineTotal } from './pricing.js';

export class OrderError extends Error {}

export function createOrder(sku, qty, discountPct = 0) {
  const entry = CATALOG.find((p) => p.sku === sku);
  if (!entry) {
    throw new OrderError(`unknown product: ${sku}`);
  }
  if (getStock(sku) < qty) {
    throw new OutOfStock(`out of stock: ${sku}`);
  }
  const total = lineTotal(entry.price, qty, discountPct);
  reserve(sku, qty);
  return { sku, qty, total, totalWithTax: addTax(total) };
}
