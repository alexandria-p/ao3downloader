import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';
import { CUSTOM_FONT_KEY, FONT_KEY, PALETTE_KEY, applyAppearance } from './app/appearance';
import { safeGet } from './app/storage';

// before the first paint, so a chosen palette never flashes the default one first
applyAppearance(safeGet(PALETTE_KEY), safeGet(FONT_KEY), safeGet(CUSTOM_FONT_KEY));

bootstrapApplication(App, appConfig)
  .catch((err) => console.error(err));
