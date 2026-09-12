import { Component } from '@angular/core';

/**
 * The things people ask, and the things they hit without asking.
 *
 * Deliberately static and free of any dependency on the helper: the most likely moment
 * someone wants this page is when a download did not come out how they expected, which is
 * also a moment the helper may not be running.
 */
@Component({
  selector: 'app-faq',
  templateUrl: './faq.html',
  styleUrl: './faq.css',
})
export class Faq {}
