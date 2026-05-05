// Page-side recorder script.
//
// Attached to every navigation via `page.add_init_script` from the Python
// `Recorder`. For each user-driven event it builds an envelope matching the
// "Page -> Python capture payload" schema in `.claude/plans/data-capture.md`
// and forwards it to `window.__rpa_capture`, which Python exposes via
// `page.expose_function`.
//
// Constraints:
//   - dependency-free, idempotent (guarded by `window.__rpaInjected`)
//   - listeners attached in the capture phase so page handlers cannot
//     `stopPropagation` before we observe the event
//   - JS-side errors are swallowed; recording must never break the page

(() => {
  if (window.__rpaInjected) return;
  window.__rpaInjected = true;
  window.__rpaCaptureCount = 0;

  const TEXT_CAP = 200;
  const ATTR_CAP = 4096;

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

  function trimText(s) {
    if (!s) return null;
    const t = String(s).trim();
    if (!t) return null;
    return t.length > TEXT_CAP ? t.slice(0, TEXT_CAP) : t;
  }

  function accessibleName(el) {
    const aria = trimText(el.getAttribute("aria-label"));
    if (aria) return aria;
    const lblBy = el.getAttribute("aria-labelledby");
    if (lblBy) {
      const parts = lblBy
        .split(/\s+/)
        .map((id) => {
          const node = document.getElementById(id);
          return node ? trimText(node.innerText || node.textContent) : null;
        })
        .filter(Boolean);
      if (parts.length) return parts.join(" ");
    }
    const tag = el.tagName.toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") {
      if (el.id) {
        const lbl = document.querySelector("label[for=\"" + CSS.escape(el.id) + "\"]");
        if (lbl) {
          const t = trimText(lbl.innerText || lbl.textContent);
          if (t) return t;
        }
      }
      const wrap = el.closest("label");
      if (wrap) {
        const t = trimText(wrap.innerText || wrap.textContent);
        if (t) return t;
      }
      const ph = trimText(el.getAttribute("placeholder"));
      if (ph) return ph;
      const tt = trimText(el.getAttribute("title"));
      if (tt) return tt;
    }
    return trimText(el.innerText || el.textContent);
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
        const t = trimText(lbl.innerText || lbl.textContent);
        if (t) out.push(t);
      }
    }
    const wrap = el.closest("label");
    if (wrap) {
      const t = trimText(wrap.innerText || wrap.textContent);
      if (t && out.indexOf(t) === -1) out.push(t);
    }
    return out;
  }

  function targetSnapshot(el) {
    return {
      role: inferRole(el),
      accessible_name: accessibleName(el),
      test_id: el.getAttribute("data-testid"),
      tag: el.tagName.toLowerCase(),
      attributes: attrs(el),
      css: uniqueCss(el),
      xpath: xpathOf(el),
      visible_text: trimText(el.innerText || el.textContent),
      bounding_box: safeRect(el),
      is_visible: isVisible(el),
      is_enabled: !el.disabled,
      parent_form_id: (el.closest("form") && el.closest("form").id) || null,
      nearby_labels: nearbyLabels(el),
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
