// Stock levels per product.
export class OutOfStock extends Error {}

const STOCK = new Map<string, number>();

export function resetStock(): void {
  STOCK.clear();
  STOCK.set('tea', 40);
  STOCK.set('coffee', 25);
  STOCK.set('mug', 10);
}
resetStock();

export async function getStock(sku: string): Promise<number> {
  const have = STOCK.get(sku);
  if (have === undefined) {
    throw new OutOfStock(`unknown sku: ${sku}`);
  }
  return have;
}

export function reserve(sku: string, qty: number): void {
  if (getStock(sku) < qty) {
    throw new OutOfStock(`out of stock: ${sku}`);
  }
  STOCK.set(sku, getStock(sku) - qty);
}

export function restock(sku: string, qty: number): void {
  STOCK.set(sku, (STOCK.get(sku) ?? 0) + qty);
}
