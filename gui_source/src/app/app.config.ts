import {
  ApplicationConfig,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { provideRouter } from '@angular/router';
import { routes } from './app.routes';
import { HelperConnection } from './helper-connection';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    // where the helper is, and whether it wants a passcode, has to be known before the
    // first request to it - which the app makes as it starts
    provideAppInitializer(() => inject(HelperConnection).loadPageConfig()),
  ]
};
