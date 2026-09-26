import { Component, inject, output, signal } from '@angular/core';
import { HelperConnection } from './helper-connection';

/**
 * The window a passcode-protected page opens with, and comes back to whenever the helper
 * refuses the passcode it holds.
 *
 * It cannot be dismissed: a copy of the page set up with a passcode is one person's, and
 * nothing on it works without the helper. The passcode is checked by the helper, not here -
 * the page is public, so anything it could check against would be readable by anyone - and
 * it is saved in this browser only once the helper has accepted it.
 */
@Component({
  selector: 'app-passcode-gate',
  templateUrl: './passcode-gate.html',
  styleUrl: './passcode-gate.css',
})
export class PasscodeGate {
  private readonly helper = inject(HelperConnection);

  /** the helper took the passcode */
  readonly unlocked = output<void>();

  protected readonly passcode = signal('');
  protected readonly checking = signal(false);
  protected readonly problem = signal('');

  protected async submit(event?: Event): Promise<void> {
    // a form, so enter works - but nothing here is meant to navigate
    event?.preventDefault();
    const passcode = this.passcode();
    if (!passcode || this.checking()) return;
    this.checking.set(true);
    this.problem.set('');
    try {
      switch (await this.helper.tryPasscode(passcode)) {
        case 'accepted':
          this.passcode.set('');
          this.unlocked.emit();
          return;
        case 'refused':
          this.problem.set('That passcode was not accepted.');
          return;
        case 'unreachable':
          // never names the address: where a hosted helper lives is not the page's to tell.
          // a local one is usually just not started; a hosted one is usually asleep, and
          // wakes on its own
          this.problem.set(
            this.helper.isLocal()
              ? 'Could not reach the local helper. Please make sure you ran the correct ' +
                  'powershell script, and that the python helper console application is running.'
              : 'Could not reach the remote helper. It may be waking up, which can take a ' +
                  'minute - try again shortly.',
          );
          return;
      }
    } finally {
      this.checking.set(false);
    }
  }
}
