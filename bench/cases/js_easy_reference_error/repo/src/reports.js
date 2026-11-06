// Simple sales reports.
export function salesTotal(orders) {
  let total = 0;
  for (const order of orders) {
    total += order.total;
  }
  return Math.round(totl * 100) / 100;
}

export function averageOrder(orders) {
  return orders.length ? Math.round((salesTotal(orders) / orders.length) * 100) / 100 : 0;
}
