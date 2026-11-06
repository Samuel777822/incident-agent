import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resetStock } from '../src/inventory.js';
import { createOrder, OrderError } from '../src/orders.js';

test('an order is priced with the discount', () => {
  resetStock();
  const order = createOrder('tea', 2, 10);
  assert.equal(order.total, 216);
  assert.equal(order.totalWithTax, 254.88);
});

test('an unknown product is an OrderError', () => {
  resetStock();
  assert.throws(() => createOrder('juice', 1), OrderError);
});

test('ordering more than we have is refused', () => {
  resetStock();
  assert.throws(() => createOrder('mug', 99), /out of stock/);
});
