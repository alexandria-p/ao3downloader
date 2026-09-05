import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { Library } from './library';
import {
  Bookmark,
  authorLink,
  chapterCount,
  isComplete,
  ownerFromSource,
  pageItems,
  paragraphs,
  ratingClass,
  warningClass,
} from './bookmarks';

const PER_PAGE = 19;

@Component({
  selector: 'app-root',
  imports: [DecimalPipe, NgTemplateOutlet],
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  private readonly library = inject(Library);

  protected readonly perPage = PER_PAGE;
  protected readonly page = signal(1);

  protected readonly data = this.library.data;
  protected readonly error = this.library.error;
  protected readonly loading = this.library.loading;
  protected readonly sourceName = this.library.sourceName;
  protected readonly htmlFiles = this.library.htmlFiles;
  protected readonly folderName = this.library.folderName;
  protected readonly needsReconnect = this.library.needsReconnect;
  protected readonly canPickFolder = this.library.canPickFolder;

  constructor() {
    // reopen the folder picked last time, if the browser still lets us read it
    void this.library.restore();
  }

  protected readonly works = computed<Bookmark[]>(() => this.data()?.works ?? []);
  protected readonly total = computed(() => this.works().length);
  protected readonly owner = computed(() => ownerFromSource(this.data()?.source ?? ''));
  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PER_PAGE)));
  protected readonly pages = computed(() => pageItems(this.page(), this.totalPages()));

  protected readonly pageWorks = computed(() => {
    const start = (this.page() - 1) * PER_PAGE;
    return this.works().slice(start, start + PER_PAGE);
  });

  protected readonly rangeStart = computed(() =>
    this.total() === 0 ? 0 : (this.page() - 1) * PER_PAGE + 1,
  );
  protected readonly rangeEnd = computed(() => Math.min(this.page() * PER_PAGE, this.total()));

  /** how many of the listed works actually have a downloaded html file alongside them */
  protected readonly linkedCount = computed(() => {
    const files = this.htmlFiles();
    return this.works().filter((work) => work.id && files.has(work.id)).length;
  });

  // template helpers
  protected readonly authorLink = authorLink;
  protected readonly chapterCount = chapterCount;
  protected readonly isComplete = isComplete;
  protected readonly paragraphs = paragraphs;
  protected readonly ratingClass = ratingClass;
  protected readonly warningClass = warningClass;

  protected async choose(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    await this.library.load(input.files);
    this.page.set(1);
    // let the same folder be picked again after a re-export
    input.value = '';
  }

  protected async pickFolder(): Promise<void> {
    await this.library.pickFolder();
    this.page.set(1);
  }

  protected async reconnect(): Promise<void> {
    await this.library.reconnect();
    this.page.set(1);
  }

  protected async forget(): Promise<void> {
    await this.library.forget();
    this.page.set(1);
  }

  protected goTo(page: number): void {
    this.page.set(Math.min(Math.max(page, 1), this.totalPages()));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  protected hasLocalCopy(work: Bookmark): boolean {
    return !!work.id && this.htmlFiles().has(work.id);
  }

  /**
   * Opens the downloaded html file in a new tab, falling back to the work on ao3 when
   * this folder has no local copy of it.
   */
  protected openWork(work: Bookmark, event: Event): void {
    event.preventDefault();

    const file = work.id ? this.htmlFiles().get(work.id) : undefined;
    if (file) {
      const url = URL.createObjectURL(file);
      window.open(url, '_blank');
      // the tab keeps its own copy once loaded, so the handle can be released
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      return;
    }

    if (work.link) window.open(work.link, '_blank', 'noopener');
  }
}
