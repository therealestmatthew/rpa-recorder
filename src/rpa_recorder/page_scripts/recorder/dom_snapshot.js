// DOM snapshot helper — stub.
//
// Future work (M11.5): expose a function that serializes the current DOM
// (including shadow roots) into a JSON envelope routable to bronze. For now
// it just registers an idempotent namespace so the loader has something to
// resolve.

(() => {
  if (window.__rpaRecorderDomSnapshotLoaded) return;
  window.__rpaRecorderDomSnapshotLoaded = true;
  window.__rpa = window.__rpa || {};
  window.__rpa.recorder = window.__rpa.recorder || {};
  window.__rpa.recorder.domSnapshot = function () {
    return null;
  };
})();
