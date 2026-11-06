import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getStock, OutOfStock, reserve, resetStock, restock } from '../src/inventory.js';

test('tea stock', () => {
  resetStock();
  assert.equal(getStock('tea'), 40);
});

test('an unknown sku throws OutOfStock', () => {
  assert.throws(() => getStock('juice'), OutOfStock);
});

test('reserve and restock', () => {
  resetStock();
  reserve('mug', 4);
  assert.equal(getStock('mug'), 6);
  assert.throws(() => reserve('mug', 50), OutOfStock);
  restock('mug', 4);
  assert.equal(getStock('mug'), 10);
});
