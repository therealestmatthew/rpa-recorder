// Shared text helpers: trim and accessibleName.
//
// Exposes `window.__rpa.shared.text` once. Other scripts call:
//   window.__rpa.shared.text.trim(s)
//   window.__rpa.shared.text.accessibleName(el)

(() => {
  if (window.__rpaSharedTextLoaded) return;
  window.__rpaSharedTextLoaded = true;
  window.__rpa = window.__rpa || {};
  window.__rpa.shared = window.__rpa.shared || {};

  const TEXT_CAP = 200;

  function trim(s) {
    if (!s) return null;
    const t = String(s).trim();
    if (!t) return null;
    return t.length > TEXT_CAP ? t.slice(0, TEXT_CAP) : t;
  }

  function accessibleName(el) {
    const aria = trim(el.getAttribute("aria-label"));
    if (aria) return aria;
    const lblBy = el.getAttribute("aria-labelledby");
    if (lblBy) {
      const parts = lblBy
        .split(/\s+/)
        .map((id) => {
          const node = document.getElementById(id);
          return node ? trim(node.innerText || node.textContent) : null;
        })
        .filter(Boolean);
      if (parts.length) return parts.join(" ");
    }
    const tag = el.tagName.toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") {
      if (el.id) {
        const lbl = document.querySelector("label[for=\"" + CSS.escape(el.id) + "\"]");
        if (lbl) {
          const t = trim(lbl.innerText || lbl.textContent);
          if (t) return t;
        }
      }
      const wrap = el.closest("label");
      if (wrap) {
        const t = trim(wrap.innerText || wrap.textContent);
        if (t) return t;
      }
      const ph = trim(el.getAttribute("placeholder"));
      if (ph) return ph;
      const tt = trim(el.getAttribute("title"));
      if (tt) return tt;
    }
    return trim(el.innerText || el.textContent);
  }

  window.__rpa.shared.text = { trim: trim, accessibleName: accessibleName };
})();
