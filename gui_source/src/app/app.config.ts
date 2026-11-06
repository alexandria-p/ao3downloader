import {
  ApplicationConfig,
  ErrorHandler,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { provideRouter } from '@angular/router';
import { routes } from './app.routes';
import { HelperConnection } from './helper-connection';
import { VisitErrorHandler } from './visit-log';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    // every error also goes into this visit's log, which a bug report can attach
    { provide: ErrorHandler, useClass: VisitErrorHandler },
    provideRouter(routes),
    // where the helper is, and whether it wants a passcode, has to be known before the
    // first request to it - which the app makes as it starts
    provideAppInitializer(() => inject(HelperConnection).loadPageConfig()),
  ]
};
