// Review store for the shop. Plain Map-backed so it is easy to test.
export class ReviewError extends Error {}

export interface ReviewRow {
  id: number;
  name: string;
  active: boolean;
}

export class ReviewStore {
  private items = new Map<number, ReviewRow>();
  private nextId = 1;
  public audit: string[] = [];

  private log(action: string, id: number): void {
    this.audit.push(`${action} ${id}`);
  }

  add(name: string): number {
    if (!name || !name.trim()) {
      throw new ReviewError('name is required');
    }
    const id = this.nextId++;
    this.items.set(id, { id, name: name.trim(), active: true });
    this.log('add', id);
    return id;
  }

  get(id: number): ReviewRow {
    const row = this.items.get(id);
    if (!row) {
      throw new ReviewError(`Review ${id} not found`);
    }
    return { ...row };
  }

  update(id: number, fields: Partial<ReviewRow>): ReviewRow {
    const row = this.items.get(id);
    if (!row) {
      throw new ReviewError(`Review ${id} not found`);
    }
    Object.assign(row, fields);
    this.log('update', id);
    return { ...row };
  }

  deactivate(id: number): ReviewRow {
    return this.update(id, { active: false });
  }

  delete(id: number): void {
    if (!this.items.has(id)) {
      throw new ReviewError(`Review ${id} not found`);
    }
    this.items.delete(id);
    this.log('delete', id);
  }

  list(onlyActive = true): ReviewRow[] {
    return [...this.items.values()]
      .filter((row) => row.active || !onlyActive)
      .map((row) => ({ ...row }))
      .sort((a, b) => a.id - b.id);
  }

  search(text: string): ReviewRow[] {
    const needle = text.trim().toLowerCase();
    return this.list().filter((row) => row.name.toLowerCase().includes(needle));
  }

  count(onlyActive = true): number {
    return this.list(onlyActive).length;
  }

  names(): string[] {
    return this.list().map((row) => row.name);
  }

  bulkAdd(names: string[]): number[] {
    return names.map((n) => this.add(n));
  }

  summary(): { total: number; active: number; auditEvents: number } {
    return { total: this.count(false), active: this.count(true), auditEvents: this.audit.length };
  }
}
