// Category store for the shop. Plain Map-backed so it is easy to test.
export class CategoryError extends Error {}

export class CategoryStore {
  #items = new Map();
  #nextId = 1;
  audit = [];

  #log(action, id) {
    this.audit.push(`${action} ${id}`);
  }

  add(name) {
    if (!name || !String(name).trim()) {
      throw new CategoryError('name is required');
    }
    const id = this.#nextId++;
    this.#items.set(id, { id, name: String(name).trim(), active: true });
    this.#log('add', id);
    return id;
  }

  get(id) {
    const row = this.#items.get(id);
    if (!row) {
      throw new CategoryError(`Category ${id} not found`);
    }
    return { ...row };
  }

  update(id, fields) {
    const row = this.#items.get(id);
    if (!row) {
      throw new CategoryError(`Category ${id} not found`);
    }
    Object.assign(row, fields);
    this.#log('update', id);
    return { ...row };
  }

  deactivate(id) {
    return this.update(id, { active: false });
  }

  delete(id) {
    if (!this.#items.has(id)) {
      throw new CategoryError(`Category ${id} not found`);
    }
    this.#items.delete(id);
    this.#log('delete', id);
  }

  list(onlyActive = true) {
    return [...this.#items.values()]
      .filter((row) => row.active || !onlyActive)
      .map((row) => ({ ...row }))
      .sort((a, b) => a.id - b.id);
  }

  search(text) {
    const needle = String(text).trim().toLowerCase();
    return this.list().filter((row) => row.name.toLowerCase().includes(needle));
  }

  count(onlyActive = true) {
    return this.list(onlyActive).length;
  }

  names() {
    return this.list().map((row) => row.name);
  }

  bulkAdd(names) {
    return names.map((n) => this.add(n));
  }

  summary() {
    return { total: this.count(false), active: this.count(true), auditEvents: this.audit.length };
  }
}
