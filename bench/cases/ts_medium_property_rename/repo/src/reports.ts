// Simple sales reports.
import type { Order } from './orders.ts';

export function salesTotal(orders: Pick<Order, 'total'>[]): number {
  let total = 0;
  for (const order of orders) {
    total += order.total;
  }
  return Math.round(total * 100) / 100;
}

export function averageOrder(orders: Pick<Order, 'total'>[]): number {
  return orders.length ? Math.round((salesTotal(orders) / orders.length) * 100) / 100 : 0;
}
