// Shared selector / element helpers.
//
// Exposes `window.__rpa.shared.selectors` once with:
//   inferRole(el), uniqueCss(el), xpathOf(el), safeRect(el),
//   isVisible(el), nearbyLabels(el), attrs(el)
//
// Depends on `window.__rpa.shared.text.trim` (load shared/text_utils first).

(() => {
  if (window.__rpaSharedSelectorsLoaded) return;
  window.__rpaSharedSelectorsLoaded = true;
  window.__rpa = window.__rpa || {};
  window.__rpa.shared = window.__rpa.shared || {};

  const ATTR_CAP = 4096;
  const text = (window.__rpa.shared.text || {});
  const trim = text.trim || ((s) => (s ? String(s).trim() || null : null));

  function safeRect(el) {
    try {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height };
    } catch (_) {
      return null;
    }
  }

  function isVisible(el) {
    try {
      if (!el.isConnected) return false;
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") return false;
      if (parseFloat(cs.opacity || "1") === 0) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 || r.height > 0;
    } catch (_) {
      return false;
    }
  }

  function inferRole(el) {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (tag === "button") return "button";
    if (tag === "a" && el.hasAttribute("href")) return "link";
    if (tag === "input") {
      if (type === "button" || type === "submit" || type === "reset") return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "range") return "slider";
      if (type === "search") return "searchbox";
      return "textbox";
    }
    if (tag === "textarea") return "textbox";
    if (tag === "select") return "combobox";
    if (["h1", "h2", "h3", "h4", "h5", "h6"].indexOf(tag) !== -1) return "heading";
    if (tag === "img") return "img";
    if (tag === "ul" || tag === "ol") return "list";
    if (tag === "li") return "listitem";
    return null;
  }

  function uniqueCss(el) {
    if (!el || el.nodeType !== 1) return null;
    if (el.id) return "#" + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.documentElement) {
      let part = node.tagName.toLowerCase();
      if (node.classList && node.classList.length) {
        const classes = Array.from(node.classList).map((c) => CSS.escape(c));
        part += "." + classes.join(".");
      }
      const parent = node.parentElement;
      if (parent) {
        const sibs = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
        if (sibs.length > 1) {
          const idx = sibs.indexOf(node) + 1;
          part += ":nth-of-type(" + idx + ")";
        }
      }
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(" > ") || null;
  }

  function xpathOf(el) {
    if (!el || el.nodeType !== 1) return null;
    if (el.id) return "//*[@id=\"" + el.id + "\"]";
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.documentElement) {
      const tag = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (!parent) {
        parts.unshift(tag);
        break;
      }
      const sibs = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
      const idx = sibs.indexOf(node) + 1;
      parts.unshift(tag + "[" + idx + "]");
      node = parent;
    }
    return "/" + parts.join("/");
  }

  function attrs(el) {
    const out = {};
    let total = 0;
    const list = el.attributes;
    for (let i = 0; i < list.length; i++) {
      const a = list[i];
      total += a.name.length + (a.value ? a.value.length : 0);
      if (total > ATTR_CAP) break;
      out[a.name] = a.value;
    }
    return out;
  }

  function nearbyLabels(el) {
    const out = [];
    if (el.id) {
      const lbl = document.querySelector("label[for=\"" + CSS.escape(el.id) + "\"]");
      if (lbl) {
        const t = trim(lbl.innerText || lbl.textContent);
        if (t) out.push(t);
      }
    }
    const wrap = el.closest("label");
    if (wrap) {
      const t = trim(wrap.innerText || wrap.textContent);
      if (t && out.indexOf(t) === -1) out.push(t);
    }
    return out;
  }

  window.__rpa.shared.selectors = {
    inferRole: inferRole,
    uniqueCss: uniqueCss,
    xpathOf: xpathOf,
    safeRect: safeRect,
    isVisible: isVisible,
    nearbyLabels: nearbyLabels,
    attrs: attrs,
  };
})();
