import { Component, computed, inject, input, output, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Library } from './library';
import {
  TAG_KINDS,
  TagChoice,
  TagCount,
  TagIndex,
  highlight,
  suggestTags,
  tagKey,
} from './tags';

/** how many of a kind's tags are offered to tick, before typing is the way to find the rest */
const TOP_PER_KIND = 10;

/**
 * One half of the tag filter - Include or Exclude - laid out as ao3's own Sort and Filter
 * panel is: a fold per kind of tag (Ratings, Warnings, ... Additional Tags) offering this
 * listing's most-used tags of that kind to tick, then **Other tags to include** (or exclude),
 * a box that suggests any tag in the library as it is typed.
 *
 * Suggestions come from the whole library (`Library.tagIndex`), so a tag can be found even
 * when this listing has none of it; the folds count this listing's own works, which is what
 * ticking one will narrow.
 */
@Component({
  selector: 'app-tag-filter',
  imports: [DecimalPipe],
  templateUrl: './tag-filter.html',
  styleUrl: './tag-filter.css',
})
export class TagFilter {
  private readonly library = inject(Library);

  /** 'Include' or 'Exclude' */
  readonly label = input.required<string>();
  readonly chosen = input<TagChoice[]>([]);
  /** what the other half has chosen: a tag cannot be both included and left out */
  readonly elsewhere = input<TagChoice[]>([]);
  /** the tags of this listing's works, for the folds */
  readonly listing = input.required<TagIndex>();
  readonly chosenChange = output<TagChoice[]>();

  protected readonly kinds = TAG_KINDS;
  protected readonly typed = signal('');
  /** which suggestion the arrow keys are on */
  protected readonly active = signal(0);
  protected readonly highlight = highlight;

  private readonly taken = computed(
    () => new Set([...this.chosen(), ...this.elsewhere()].map(tagKey)),
  );
  private readonly chosenKeys = computed(() => new Set(this.chosen().map(tagKey)));

  /** the library's tags are only counted once someone types - never just to draw the box */
  protected readonly suggestions = computed(() =>
    this.typed().trim() ? suggestTags(this.library.tagIndex(), this.typed(), this.taken()) : [],
  );

  /** this listing's most-used tags of one kind, to tick */
  protected top(kind: TagCount['kind']): TagCount[] {
    return this.listing().byKind[kind].slice(0, TOP_PER_KIND);
  }

  protected kindLabel(kind: TagCount['kind']): string {
    return TAG_KINDS.find((k) => k.kind === kind)?.one ?? kind;
  }

  protected isChosen(tag: TagChoice): boolean {
    return this.chosenKeys().has(tagKey(tag));
  }

  protected isElsewhere(tag: TagChoice): boolean {
    return !this.isChosen(tag) && this.taken().has(tagKey(tag));
  }

  protected toggle(tag: TagChoice): void {
    if (this.isChosen(tag)) this.remove(tag);
    else this.add(tag);
  }

  protected add(tag: TagChoice): void {
    if (this.taken().has(tagKey(tag))) return;
    this.chosenChange.emit([...this.chosen(), { kind: tag.kind, name: tag.name }]);
    this.typed.set('');
    this.active.set(0);
  }

  protected remove(tag: TagChoice): void {
    this.chosenChange.emit(this.chosen().filter((t) => tagKey(t) !== tagKey(tag)));
  }

  protected onType(value: string): void {
    this.typed.set(value);
    this.active.set(0);
  }

  /** up and down move through the suggestions, enter takes one, escape closes them */
  protected onKey(event: KeyboardEvent): void {
    const list = this.suggestions();
    if (event.key === 'ArrowDown' && list.length) {
      event.preventDefault();
      this.active.set((this.active() + 1) % list.length);
    } else if (event.key === 'ArrowUp' && list.length) {
      event.preventDefault();
      this.active.set((this.active() - 1 + list.length) % list.length);
    } else if (event.key === 'Enter') {
      // never submits anything: the filters apply as they change
      event.preventDefault();
      const pick = list[this.active()];
      if (pick) this.add(pick);
    } else if (event.key === 'Escape' && this.typed()) {
      event.stopPropagation();
      this.typed.set('');
    }
  }
}
