import { Component, inject } from '@angular/core';
import { UpdateCheck } from './updates';

/**
 * The things people ask, and the things they hit without asking.
 *
 * Deliberately free of any dependency on the helper - the page's own config, read before
 * anything started, is all it uses: the most likely moment
 * someone wants this page is when a download did not come out how they expected, which is
 * also a moment the helper may not be running.
 */
@Component({
  selector: 'app-faq',
  templateUrl: './faq.html',
  styleUrl: './faq.css',
})
export class Faq {
  private readonly updates = inject(UpdateCheck);

  /** always the latest release's page, whatever it is called */
  protected readonly latestUrl = this.updates.latestUrl();
  /** the version this page was built as, when it was built by a deployment */
  protected readonly version = this.updates.version();
}
