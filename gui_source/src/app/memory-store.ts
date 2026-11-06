/**
 * A library held in memory, by path. The DEBUG tab's Resolve issues mock and debug mode's dummy
 * data both use it, so whatever they rename, write or delete never reaches a real library.
 */

import { LibraryStore } from './library-store';

/** a library held in memory, by path - what a mock renames and deletes, and nothing else */
export class MemoryStore implements LibraryStore {
  readonly files = new Map<string, string>();
  /** when each file was last changed, by path; a file not here cannot say */
  readonly changed = new Map<string, number>();

  constructor(
    paths: Iterable<string> = [],
    changed: Record<string, number> = {},
    readonly label = 'mock library (in memory)',
  ) {
    for (const path of paths) this.files.set(path, '');
    for (const [path, at] of Object.entries(changed)) this.changed.set(path, at);
  }

  async check(): Promise<void> {}

  async list(path: string, recursive = true): Promise<string[]> {
    const prefix = path ? `${path.replace(/\/+$/, '')}/` : '';
    return [...this.files.keys()]
      .filter((p) => p.startsWith(prefix) && (recursive || !p.slice(prefix.length).includes('/')))
      .sort();
  }

  async read(path: string): Promise<string | null> {
    return this.files.get(path) ?? null;
  }

  async write(path: string, body: Response): Promise<number> {
    const text = await body.text();
    this.files.set(path, text);
    return text.length;
  }

  async size(path: string): Promise<number | null> {
    return this.files.has(path) ? (this.files.get(path) ?? '').length : null;
  }

  async modified(path: string): Promise<number | null> {
    return this.files.has(path) ? (this.changed.get(path) ?? null) : null;
  }

  async delete(path: string): Promise<void> {
    this.files.delete(path);
    this.changed.delete(path);
  }

  async rename(from: string, to: string): Promise<void> {
    if (this.files.has(to)) throw new Error(`${to} is already there`);
    if (!this.files.has(from)) throw new Error(`${from} is not there`);
    this.files.set(to, this.files.get(from) ?? '');
    this.files.delete(from);
    const at = this.changed.get(from);
    this.changed.delete(from);
    if (at !== undefined) this.changed.set(to, at);
  }

  async mkdir(): Promise<void> {}
}
