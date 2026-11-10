import { test } from 'node:test';
import assert from 'node:assert/strict';
import { InvoiceError, InvoiceStore } from '../src/invoices.js';

test('invoices: add trims the name', () => {
  const s = new InvoiceStore();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('invoices: a missing item throws', () => {
  assert.throws(() => new InvoiceStore().get(99), InvoiceError);
});

test('invoices: search and counts', () => {
  const s = new InvoiceStore();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
