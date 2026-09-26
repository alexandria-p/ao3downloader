import { Component, inject } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { LibrarySetup, WORKS_FOLDER } from './library-setup';

/**
 * Covers the page while a library is being set up, and asks the one question setting it up
 * can raise.
 *
 * Deliberately blocks everything underneath. Folders are being made and files moved; a run
 * started, or another folder picked, halfway through would be working against a library in
 * no settled state. It says what is happening rather than showing a bare spinner, because
 * a screen that stops responding for no stated reason reads as a crash.
 */
@Component({
  selector: 'app-setup-overlay',
  imports: [DecimalPipe],
  templateUrl: './setup-overlay.html',
  styleUrl: './setup-overlay.css',
})
export class SetupOverlay {
  protected readonly setup = inject(LibrarySetup);
  protected readonly works = WORKS_FOLDER;
}
