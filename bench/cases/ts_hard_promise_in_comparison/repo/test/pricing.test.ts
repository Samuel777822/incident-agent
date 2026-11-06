import { test } from 'node:test';
import assert from 'node:assert/strict';
import { addTax, applyDiscount, lineTotal, shippingCost } from '../src/pricing.ts';

test('ten percent off 200 is 180', () => {
  assert.equal(applyDiscount(200, 10), 180);
});

test('a line with a discount', () => {
  assert.equal(lineTotal(100, 3, 10), 270);
});

test('tax is 18 percent', () => {
  assert.equal(addTax(100), 118);
});

test('shipping for two kilos', () => {
  assert.equal(shippingCost(2), 65);
});

test('a discount over 100 is rejected', () => {
  assert.throws(() => applyDiscount(10, 120), RangeError);
});
