import { test } from 'node:test';
import assert from 'node:assert/strict';
import { averageOrder, salesTotal } from '../src/reports.js';

test('sales total', () => {
  assert.equal(salesTotal([{ total: 10.5 }, { total: 4.5 }]), 15);
});

test('average order', () => {
  assert.equal(averageOrder([{ total: 10.5 }, { total: 4.5 }]), 7.5);
  assert.equal(averageOrder([]), 0);
});
