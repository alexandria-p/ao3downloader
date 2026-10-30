import { Component, computed, inject, input, output, signal } from '@angular/core';
import { Collection } from './collections';
import {
  CHALLENGE_TYPES,
  CollectionFields,
  CollectionItems,
  CustomCollections,
  TITLE_LIMIT,
  blankFields,
  fieldsOf,
} from './custom-collections';

/**
 * The window for making a collection of your own, or changing what is said about one.
 *
 * Opened three ways, all the same window: **New collection** on the Collections tab, choosing
 * *A new collection* while adding ticked works, and **Edit** on a collection of your own.
 *
 * Bare by default - a name, a description and tags, which is what most people will ever want.
 * **Show every field** opens the rest of what an ao3 collection records, so a collection made
 * here can be described as fully as one read from ao3.
 *
 * **Nothing is written until Save.** Closing it any way - Cancel, the cross, Escape, the
 * backdrop - makes no collection and changes none, and hands nothing back: whoever opened it
 * keeps what they had, ticked works included.
 */
@Component({
  selector: 'app-collection-editor',
  templateUrl: './collection-editor.html',
  styleUrl: './collection-editor.css',
  host: { '(document:keydown.escape)': 'cancel()' },
})
export class CollectionEditor {
  private readonly custom = inject(CustomCollections);

  /** the custom collection to change, or null to make a new one */
  readonly collection = input<Collection | null>(null);
  /** what a new collection starts out holding - the works ticked when it was asked for */
  readonly items = input<CollectionItems | null>(null);

  /** saved: the collection as written */
  readonly saved = output<Collection>();
  /** closed without saving: nothing was written */
  readonly cancelled = output<void>();

  protected readonly fields = signal<CollectionFields>(blankFields());
  protected readonly advanced = signal(false);
  protected readonly busy = signal(false);
  protected readonly problem = signal('');
  protected readonly titleLimit = TITLE_LIMIT;
  protected readonly challengeTypes = CHALLENGE_TYPES;

  protected readonly editing = computed(() => !!this.collection());
  protected readonly holding = computed(() => {
    const items = this.items();
    return items ? items.works.length + items.externals.length : 0;
  });
  protected readonly canSave = computed(() => !this.busy() && !!this.fields().title.trim());

  /**
   * Tags and maintainers are typed as one line, comma-separated, as ao3's own forms take them -
   * kept as typed, and split only on save, so the box is never rewritten under the cursor.
   */
  protected readonly tagsText = signal('');
  protected readonly maintainersText = signal('');

  ngOnInit(): void {
    const collection = this.collection();
    const fields = collection ? fieldsOf(collection) : blankFields();
    this.fields.set(fields);
    this.tagsText.set(fields.tags.join(', '));
    this.maintainersText.set(fields.maintainers.join(', '));
  }

  protected set<K extends keyof CollectionFields>(key: K, value: CollectionFields[K]): void {
    this.fields.update((fields) => ({ ...fields, [key]: value }));
  }


  /** multifandom has three answers on ao3: yes, no, and not said */
  protected setMultifandom(value: string): void {
    this.set('multifandom', value === 'yes' ? true : value === 'no' ? false : null);
  }

  protected multifandomValue(): string {
    const value = this.fields().multifandom;
    return value === true ? 'yes' : value === false ? 'no' : '';
  }

  protected async save(event?: Event): Promise<void> {
    event?.preventDefault();
    if (!this.canSave()) return;
    this.busy.set(true);
    this.problem.set('');
    try {
      const collection = this.collection();
      const fields: CollectionFields = {
        ...this.fields(),
        tags: splitList(this.tagsText()),
        maintainers: splitList(this.maintainersText()),
      };
      const saved = collection?.name
        ? await this.custom.update(collection.name, fields)
        : await this.custom.create(fields, this.items() ?? undefined);
      this.saved.emit(saved);
    } catch (error) {
      this.problem.set(error instanceof Error ? error.message : String(error));
    } finally {
      this.busy.set(false);
    }
  }

  protected cancel(): void {
    // a save under way finishes, or fails and says so; leaving mid-write would hide which
    if (this.busy()) return;
    this.cancelled.emit();
  }
}

function splitList(text: string): string[] {
  return text.split(',').map((x) => x.trim()).filter(Boolean);
}
