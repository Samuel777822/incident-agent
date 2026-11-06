// Order creation: checks stock, prices the line, reserves the items.
import { CATALOG } from './catalog.ts';
import { getStock, OutOfStock, reserve } from './inventory.ts';
import { addTax, lineTotal } from './pricing.ts';

export class OrderError extends Error {}

export interface Order {
  sku: string;
  qty: number;
  total: number;
  totalWithTax: number;
}

export function createOrder(sku: string, qty: number, discountPct = 0): Order {
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
