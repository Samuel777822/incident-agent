import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CouponError, CouponStore } from '../src/coupons.js';

test('coupons: add trims the name', () => {
  const s = new CouponStore();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('coupons: a missing item throws', () => {
  assert.throws(() => new CouponStore().get(99), CouponError);
});

test('coupons: search and counts', () => {
  const s = new CouponStore();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
