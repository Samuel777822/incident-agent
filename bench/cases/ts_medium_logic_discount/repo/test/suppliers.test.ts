import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SupplierError, SupplierStore } from '../src/suppliers.ts';

test('suppliers: add trims the name', () => {
  const s = new SupplierStore();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('suppliers: a missing item throws', () => {
  assert.throws(() => new SupplierStore().get(99), SupplierError);
});

test('suppliers: search and counts', () => {
  const s = new SupplierStore();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
