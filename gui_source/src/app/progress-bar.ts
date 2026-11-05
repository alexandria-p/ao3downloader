import { Component, computed, input } from '@angular/core';

/**
 * A progress bar and its caption, in the palette's accent colour: reading the library, reading
 * the run history. `percent` null means there is no total to divide by, so the bar sweeps
 * rather than claiming a number.
 */
@Component({
  selector: 'app-progress-bar',
  template: `
    <div class="read-progress">
      <div
        class="bar"
        role="progressbar"
        [attr.aria-label]="label() || plain()"
        [attr.aria-valuenow]="percent()"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <div class="fill" [class.indeterminate]="percent() === null" [style.width.%]="percent() ?? 100"></div>
      </div>
      <p class="notice" role="status">
        @for (part of parts(); track $index) {@if (part.code) {<code>{{ part.text }}</code>} @else {<ng-container>{{ part.text }}</ng-container>}}@if (percent() !== null) {<span class="percent"> - {{ percent() }}%</span>}
      </p>
    </div>
  `,
  styles: `
    :host {
      display: block;
    }

    /* the full width of the page (or of the tab's column) */
    .read-progress {
      margin: 0 0 14px;
    }

    .notice {
      margin: 4px 0 0;
      color: var(--text-dim);
      font-size: 0.85rem;
    }

    .notice code {
      padding: 0 4px;
      border-radius: 3px;
      background: var(--surface-2);
      color: var(--text);
      font-size: 0.95em;
    }

    .bar {
      height: 10px;
      border: 1px solid var(--border-strong);
      border-radius: 5px;
      background: var(--bg);
      overflow: hidden;
    }

    .fill {
      height: 100%;
      background: var(--accent);
      transition: width 0.3s ease;
    }

    /* no total to divide by - a listing, or a zip Dropbox builds as it sends - so show motion
       rather than a false number */
    .fill.indeterminate {
      background: linear-gradient(90deg, transparent, var(--accent), transparent);
      background-size: 40% 100%;
      background-repeat: no-repeat;
      animation: read-sweep 1.4s ease-in-out infinite;
    }

    @keyframes read-sweep {
      from { background-position: -40% 0; }
      to { background-position: 140% 0; }
    }

    @media (prefers-reduced-motion: reduce) {
      .fill.indeterminate { animation: none; opacity: 0.5; }
    }
  `,
})
export class ProgressBar {
  readonly percent = input<number | null>(null);
  readonly caption = input('');
  /** what the bar is for, to a screen reader; the caption when not given */
  readonly label = input('');

  /**
   * The caption in pieces: text between backticks is a folder or file location, shown as code
   * (`Creating folder \`Dropbox/Apps/FicFairy/works\``)
   */
  protected readonly parts = computed(() =>
    this.caption()
      .split('`')
      .map((text, i) => ({ text, code: i % 2 === 1 }))
      .filter((part) => part.text),
  );
  protected readonly plain = computed(() => this.caption().replaceAll('`', ''));
}
