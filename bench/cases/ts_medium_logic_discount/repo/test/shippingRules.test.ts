import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ShippingRuleError, ShippingRuleStore } from '../src/shippingRules.ts';

test('shippingRules: add trims the name', () => {
  const s = new ShippingRuleStore();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('shippingRules: a missing item throws', () => {
  assert.throws(() => new ShippingRuleStore().get(99), ShippingRuleError);
});

test('shippingRules: search and counts', () => {
  const s = new ShippingRuleStore();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
