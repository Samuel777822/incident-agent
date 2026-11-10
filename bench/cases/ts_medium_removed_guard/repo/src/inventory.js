// Stock levels per product.
export class OutOfStock extends Error {}

const STOCK = new Map();

export function resetStock() {
  STOCK.clear();
  STOCK.set('tea', 40);
  STOCK.set('coffee', 25);
  STOCK.set('mug', 10);
}
resetStock();

export async function getStock(sku) {
  if (!STOCK.has(sku)) {
    throw new OutOfStock(`unknown sku: ${sku}`);
  }
  return STOCK.get(sku);
}

export function reserve(sku, qty) {
  if (getStock(sku) < qty) {
    throw new OutOfStock(`out of stock: ${sku}`);
  }
  STOCK.set(sku, getStock(sku) - qty);
}

export function restock(sku, qty) {
  STOCK.set(sku, (STOCK.get(sku) ?? 0) + qty);
}
