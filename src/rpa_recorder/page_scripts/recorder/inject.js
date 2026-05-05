// Page-side recorder script.
//
// Attached to every navigation via `page.add_init_script` from the Python
// `Recorder`. For each user-driven event it builds an envelope and forwards
// it to `window.__rpa_capture`, exposed by Python via `page.expose_function`.
//
// Depends on `window.__rpa.shared.text` and `window.__rpa.shared.selectors`,
// which the Python loader bundles ahead of this file.
//
// Constraints:
//   - dependency-free at file scope (uses only `window.__rpa.shared.*` and
//     browser-native APIs)
//   - idempotent (guarded by `window.__rpaInjected`)
//   - listeners attached in the capture phase so page handlers cannot
//     `stopPropagation` before we observe the event
//   - JS-side errors are swallowed; recording must never break the page

(() => {
  if (window.__rpaInjected) return;
  window.__rpaInjected = true;
  window.__rpaCaptureCount = 0;

  const sel = (window.__rpa && window.__rpa.shared && window.__rpa.shared.selectors) || {};
  const txt = (window.__rpa && window.__rpa.shared && window.__rpa.shared.text) || {};

  function targetSnapshot(el) {
    return {
      role: sel.inferRole ? sel.inferRole(el) : null,
      accessible_name: txt.accessibleName ? txt.accessibleName(el) : null,
      test_id: el.getAttribute("data-testid"),
      tag: el.tagName.toLowerCase(),
      attributes: sel.attrs ? sel.attrs(el) : {},
      css: sel.uniqueCss ? sel.uniqueCss(el) : null,
      xpath: sel.xpathOf ? sel.xpathOf(el) : null,
      visible_text: txt.trim ? txt.trim(el.innerText || el.textContent) : null,
      bounding_box: sel.safeRect ? sel.safeRect(el) : null,
      is_visible: sel.isVisible ? sel.isVisible(el) : true,
      is_enabled: !el.disabled,
      parent_form_id: (el.closest("form") && el.closest("form").id) || null,
      nearby_labels: sel.nearbyLabels ? sel.nearbyLabels(el) : [],
    };
  }

  function envelope(eventType, target, payload) {
    return {
      event_type: eventType,
      target: target,
      payload: payload,
      frame_url: location.href,
      page_title: document.title,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      timestamp_ms: Date.now(),
    };
  }

  async function send(env) {
    try {
      const fn = window.__rpa_capture;
      if (typeof fn !== "function") return;
      await fn(env);
      window.__rpaCaptureCount = (window.__rpaCaptureCount || 0) + 1;
    } catch (_) {
      // never let recording break the page
    }
  }

  document.addEventListener(
    "click",
    (ev) => {
      const el = ev.target instanceof Element ? ev.target : null;
      if (!el) return;
      const buttons = ["left", "middle", "right"];
      const button = buttons[ev.button] || "left";
      const modifiers = [];
      if (ev.altKey) modifiers.push("Alt");
      if (ev.ctrlKey) modifiers.push("Control");
      if (ev.metaKey) modifiers.push("Meta");
      if (ev.shiftKey) modifiers.push("Shift");
      void send(envelope("click", targetSnapshot(el), { button: button, modifiers: modifiers }));
    },
    true,
  );

  document.addEventListener(
    "input",
    (ev) => {
      const el = ev.target;
      if (!(el instanceof Element)) return;
      const tag = el.tagName.toLowerCase();
      if (tag !== "input" && tag !== "textarea") return;
      const type = (el.getAttribute("type") || "").toLowerCase();
      const isSensitive = type === "password";
      void send(
        envelope("input", targetSnapshot(el), {
          value: el.value,
          is_sensitive: isSensitive,
          clear_first: true,
        }),
      );
    },
    true,
  );

  document.addEventListener(
    "change",
    (ev) => {
      const el = ev.target;
      if (!(el instanceof Element)) return;
      const tag = el.tagName.toLowerCase();
      if (tag === "select") {
        const values = Array.from(el.selectedOptions || []).map((o) => o.value);
        void send(envelope("change", targetSnapshot(el), { values: values }));
        return;
      }
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (tag === "input" && (type === "checkbox" || type === "radio")) {
        void send(
          envelope("change", targetSnapshot(el), {
            value: el.checked ? "on" : "off",
            is_sensitive: false,
            clear_first: false,
          }),
        );
      }
    },
    true,
  );

  document.addEventListener(
    "keydown",
    (ev) => {
      if (ev.key !== "Enter") return;
      const el = ev.target instanceof Element ? ev.target : null;
      if (!el) return;
      void send(envelope("keydown", targetSnapshot(el), { key: "Enter" }));
    },
    true,
  );
})();
