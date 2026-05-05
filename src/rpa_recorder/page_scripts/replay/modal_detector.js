// Unexpected-modal detector — stub.
//
// Future work (M10): detect modal overlays that arrive between expected
// actions (cookie banners, "are you still there" prompts) and surface them
// to the recovery engine. Stub today.

(() => {
  if (window.__rpaReplayModalDetectorLoaded) return;
  window.__rpaReplayModalDetectorLoaded = true;
  window.__rpa = window.__rpa || {};
  window.__rpa.replay = window.__rpa.replay || {};
  window.__rpa.replay.modalDetector = {
    pending: function () {
      return [];
    },
  };
})();
