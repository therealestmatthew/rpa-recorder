// Accessibility tree dump helper — stub.
//
// Future work (M11.5): walk the accessibility tree from `document` and
// return a JSON envelope. Today the executor uses Playwright's
// `page.accessibility.snapshot` from the Python side; this in-page variant
// is reserved for capture-time use during recording.

(() => {
  if (window.__rpaRecorderA11yTreeLoaded) return;
  window.__rpaRecorderA11yTreeLoaded = true;
  window.__rpa = window.__rpa || {};
  window.__rpa.recorder = window.__rpa.recorder || {};
  window.__rpa.recorder.a11yTree = function () {
    return null;
  };
})();
