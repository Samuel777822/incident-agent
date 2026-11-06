import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CategoryError, CategoryStore } from '../src/categories.ts';

test('categories: add trims the name', () => {
  const s = new CategoryStore();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('categories: a missing item throws', () => {
  assert.throws(() => new CategoryStore().get(99), CategoryError);
});

test('categories: search and counts', () => {
  const s = new CategoryStore();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
