/*
 * Applies the stored theme to <html> before the first paint so the page never
 * flashes the wrong theme. Loaded synchronously from <head>; kept in its own
 * file because the app ships a `script-src 'self'` CSP that forbids inline
 * scripts. Dark is the default.
 */
(function () {
  "use strict";

  var theme = "dark";
  try {
    if (localStorage.getItem("fin-theme") === "light") theme = "light";
  } catch (error) {
    /* storage unavailable (private mode, disabled cookies) — keep the default */
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
