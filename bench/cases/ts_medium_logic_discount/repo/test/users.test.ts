import { test } from 'node:test';
import assert from 'node:assert/strict';
import { UserError, UserStore } from '../src/users.ts';

test('users: add trims the name', () => {
  const s = new UserStore();
  const id = s.add('  Alpha ');
  assert.equal(s.get(id).name, 'Alpha');
});

test('users: a missing item throws', () => {
  assert.throws(() => new UserStore().get(99), UserError);
});

test('users: search and counts', () => {
  const s = new UserStore();
  s.bulkAdd(['red', 'green', 'redder']);
  assert.deepEqual(s.search('red').map((r) => r.name), ['red', 'redder']);
  s.deactivate(1);
  assert.equal(s.count(), 2);
  assert.equal(s.count(false), 3);
  assert.equal(s.summary().total, 3);
});
