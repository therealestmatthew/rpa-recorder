// In-page locator healing helper — stub.
//
// Future work (M10): given a stale selector, walk the DOM looking for the
// closest match (label / role / nearby text) and return a candidate
// selector for the Python side to retry against. Stub today.

(() => {
  if (window.__rpaReplayLocatorHealingLoaded) return;
  window.__rpaReplayLocatorHealingLoaded = true;
  window.__rpa = window.__rpa || {};
  window.__rpa.replay = window.__rpa.replay || {};
  window.__rpa.replay.locatorHealing = {
    suggest: function () {
      return null;
    },
  };
})();
