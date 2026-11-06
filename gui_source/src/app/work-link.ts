/**
 * A link to a work on AO3 that opens your own downloaded copy first.
 *
 * Put `[appWorkLink]="id"` on any `<a>` that names a work by number - History's lists, the
 * run window's, a collection's unindexed works. A plain click opens the work's html from the
 * library in a new tab when the library holds one; otherwise the link goes to AO3 as before.
 * A click with a modifier (ctrl, cmd, shift, a middle click) is left to the browser, so the
 * AO3 page is still a click away.
 */

import { Directive, computed, inject, input } from '@angular/core';
import { Library } from './library';

@Directive({
  selector: 'a[appWorkLink]',
  host: {
    '(click)': 'open($event)',
    '[class.local]': 'local()',
    '[attr.title]': "local() ? 'Open your downloaded copy' : null",
  },
})
export class WorkLink {
  private readonly library = inject(Library);
  /** the work's AO3 number */
  readonly appWorkLink = input<string | null | undefined>(null);
  protected readonly local = computed(() => {
    const id = this.appWorkLink();
    return !!id && this.library.htmlFiles().has(id);
  });

  protected open(event: MouseEvent): void {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const link = (event.currentTarget as HTMLAnchorElement | null)?.href ?? null;
    if (this.library.openWorkCopy(this.appWorkLink(), link)) event.preventDefault();
  }
}
