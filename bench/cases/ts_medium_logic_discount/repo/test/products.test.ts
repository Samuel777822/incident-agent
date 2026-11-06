import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ProductError, ProductStore } from '../src/products.ts';

test('products: add trims the name', () => {
  const s = new ProductStore();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('products: a missing item throws', () => {
  assert.throws(() => new ProductStore().get(99), ProductError);
});

test('products: search and counts', () => {
  const s = new ProductStore();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
