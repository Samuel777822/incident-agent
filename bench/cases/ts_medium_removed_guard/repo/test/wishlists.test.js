import { test } from 'node:test';
import assert from 'node:assert/strict';
import { WishlistError, WishlistStore } from '../src/wishlists.js';

test('wishlists: add trims the name', () => {
  const s = new WishlistStore();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('wishlists: a missing item throws', () => {
  assert.throws(() => new WishlistStore().get(99), WishlistError);
});

test('wishlists: search and counts', () => {
  const s = new WishlistStore();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
