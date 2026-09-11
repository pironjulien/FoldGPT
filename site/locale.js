/* Select FoldGPT's language before rendering; the rest of the portfolio keeps its own routing. */
(() => {
  'use strict';
  const match = /^\/(en\/)?foldgpt(?:\/(?:index\.html)?)?$/.exec(location.pathname);
  if (!match) return;

  const preferred = navigator.languages?.[0] || navigator.language || 'en';
  const language = /^fr(?:-|$)/i.test(preferred) ? 'fr' : 'en';
  const current = match[1] ? 'en' : 'fr';
  if (language === current) return;

  const path = language === 'fr' ? '/foldgpt/' : '/en/foldgpt/';
  location.replace(path + location.search + location.hash);
})();
