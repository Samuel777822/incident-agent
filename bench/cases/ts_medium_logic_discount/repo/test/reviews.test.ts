import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ReviewError, ReviewStore } from '../src/reviews.ts';

test('reviews: add trims the name', () => {
  const s = new ReviewStore();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('reviews: a missing item throws', () => {
  assert.throws(() => new ReviewStore().get(99), ReviewError);
});

test('reviews: search and counts', () => {
  const s = new ReviewStore();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
