import { Component, input } from '@angular/core';

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
        [attr.aria-label]="label() || caption()"
        [attr.aria-valuenow]="percent()"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <div class="fill" [class.indeterminate]="percent() === null" [style.width.%]="percent() ?? 100"></div>
      </div>
      <p class="notice" role="status">
        {{ caption() }}@if (percent() !== null) {<span class="percent"> - {{ percent() }}%</span>}
      </p>
    </div>
  `,
  styles: `
    .read-progress {
      margin: 0 0 14px;
      max-width: 640px;
    }

    .notice {
      margin: 4px 0 0;
      color: var(--text-dim);
      font-size: 0.85rem;
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
}
