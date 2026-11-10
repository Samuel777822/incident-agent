import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ReturnError, ReturnStore } from '../src/returns.js';

test('returns: add trims the name', () => {
  const s = new ReturnStore();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('returns: a missing item throws', () => {
  assert.throws(() => new ReturnStore().get(99), ReturnError);
});

test('returns: search and counts', () => {
  const s = new ReturnStore();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
