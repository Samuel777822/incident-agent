// The product catalogue.
export interface Product {
  sku: string;
  cost: number;
}

export const CATALOG: Product[] = [
  { sku: 'tea', price: 120 },
  { sku: 'coffee', price: 250 },
  { sku: 'mug', price: 399 },
];
