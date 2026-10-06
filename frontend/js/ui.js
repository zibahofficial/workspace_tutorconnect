/* ==========================================================================
   ui.js — reusable UI primitives: toasts, modals, formatting, images,
   skeletons, empty states, pagination, navbar, footer, charts.
   ========================================================================== */
(function (global) {
  "use strict";

  /* load Bootstrap Icons on every page (only once) */
  if (!document.getElementById("bi-icons-css")) {
    const link = document.createElement("link");
    link.id = "bi-icons-css";
    link.rel = "stylesheet";
    link.href = "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css";
    document.head.appendChild(link);
  }

  /* ------------------------------------------------------------- format -- */
  let CFG = { currency_symbol: "₦", currency: "NGN", app_name: "TutorConnect" };

  /* icon helper: ic("search") -> <i class="bi bi-search"></i> */
    const ic = (name) => '<i class="bi bi-' + name + '"></i>';

  /* subject icon helper: "bi-calculator" -> icon, old emoji -> emoji, empty -> "" */
  const subjectIcon = (icon) => {
    if (!icon) return "";
    return String(icon).indexOf("bi-") === 0
      ? '<i class="bi ' + esc(icon) + '"></i>'
      : esc(icon);
  };
  const money = (value, compact) => {
    const n = Number(value || 0);
    const s = n.toLocaleString("en-NG", { maximumFractionDigits: 0 });
    return CFG.currency_symbol + s + (compact ? "" : "");
  };

  const MODE_LABELS = { in_person: "In person", online: "Online", hybrid: "Online & in person" };
  const STATUS_LABELS = {
    pending: "Pending", accepted: "Accepted", rejected: "Rejected",
    cancelled: "Cancelled", completed: "Completed"
  };
  const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

  const initials = (name) =>
    String(name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

  function to12h(value) {
    if (!value) return "";
    const [h, m] = String(value).split(":").map(Number);
    const suffix = h >= 12 ? "PM" : "AM";
    const hour = h % 12 === 0 ? 12 : h % 12;
    return hour + ":" + String(m || 0).padStart(2, "0") + " " + suffix;
  }

  function formatDate(value, opts) {
    if (!value) return "";
    const d = new Date(String(value).length <= 10 ? value + "T00:00:00" : value);
    if (isNaN(d)) return String(value);
    return d.toLocaleDateString("en-GB", Object.assign({ day: "numeric", month: "short", year: "numeric" }, opts || {}));
  }

  function formatDayDate(value) {
    const d = new Date(String(value).length <= 10 ? value + "T00:00:00" : value);
    if (isNaN(d)) return String(value);
    return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  }

  function relativeDate(value) {
    if (!value) return "";
    const target = new Date(String(value).length <= 10 ? value + "T00:00:00" : value);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const diff = Math.round((target - today) / 86400000);
    if (diff === 0) return "Today";
    if (diff === 1) return "Tomorrow";
    if (diff === -1) return "Yesterday";
    if (diff > 1 && diff < 7) return "In " + diff + " days";
    if (diff < -1 && diff > -7) return Math.abs(diff) + " days ago";
    return formatDayDate(value);
  }

  function timeAgo(value) {
    if (!value) return "";
    const then = new Date(value.endsWith("Z") || value.includes("+") ? value : value.replace(" ", "T"));
    const secs = Math.round((Date.now() - then.getTime()) / 1000);
    if (isNaN(secs)) return "";
    if (secs < 60) return "just now";
    const mins = Math.round(secs / 60);
    if (mins < 60) return mins + "m ago";
    const hours = Math.round(mins / 60);
    if (hours < 24) return hours + "h ago";
    const days = Math.round(hours / 24);
    if (days < 7) return days + "d ago";
    if (days < 30) return Math.round(days / 7) + "w ago";
    return formatDate(value);
  }

  const plural = (n, word, pluralWord) => n + " " + (n === 1 ? word : (pluralWord || word + "s"));

  /* --------------------------------------------------------------- html -- */
  function esc(value) {
    return String(value === undefined || value === null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.keys(attrs || {}).forEach((key) => {
      const value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === "class") node.className = value;
      else if (key === "html") node.innerHTML = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
      else node.setAttribute(key, value === true ? "" : value);
    });
    (Array.isArray(children) ? children : children ? [children] : []).forEach((child) => {
      if (child === null || child === undefined || child === false) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  /* -------------------------------------------------------------- images -- */
  const COVER_FALLBACKS = [
    "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1524178232363-1fb2b075b655?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1571260899304-425eee4c7efc?auto=format&fit=crop&w=900&q=80"
  ];

  /**
   * <img> with an automatic initials fallback if the remote photo fails.
   */
  function image(src, alt, cls, fallbackName) {
    const img = el("img", {
      src: src || "", alt: alt || "", class: cls || "", loading: "lazy", decoding: "async",
      referrerpolicy: "no-referrer"
    });
    const replace = () => {
      const box = el("div", { class: (cls || "") + " avatar-fallback img-fallback", "aria-label": alt || "" },
        [document.createTextNode(initials(fallbackName || alt || "TC"))]);
      if (img.parentNode) img.parentNode.replaceChild(box, img);
    };
    if (!src) { setTimeout(replace, 0); return img; }
    let tries = 0;
    img.addEventListener("error", () => {
      const next = COVER_FALLBACKS[tries++];
      if (next && tries <= COVER_FALLBACKS.length && !src.includes("images.unsplash.com")) {
        img.src = next;
      } else if (next && tries <= COVER_FALLBACKS.length) {
        replace();
      } else {
        replace();
      }
    });
    return img;
  }

  /** Decorative photo with graceful gradient fallback (never a broken icon). */
  function photo(src, alt, cls) {
    const wrap = el("div", { class: cls || "" });
    const img = el("img", { src: src || "", alt: alt || "", loading: "lazy", decoding: "async", referrerpolicy: "no-referrer" });
    img.addEventListener("error", () => {
      wrap.classList.add("img-fallback");
      img.remove();
    });
    wrap.appendChild(img);
    return wrap;
  }

  /* -------------------------------------------------------------- toasts -- */
  let toastWrap = null;
  function ensureToastWrap() {
    if (!toastWrap) {
      toastWrap = el("div", { class: "toast-wrap", role: "status", "aria-live": "polite" });
      document.body.appendChild(toastWrap);
    }
    return toastWrap;
  }

  const TOAST_ICONS = {
    success: ic("check-circle-fill"),
    error: ic("exclamation-triangle-fill"),
    warn: ic("exclamation-circle-fill"),
    info: ic("info-circle-fill")
  };

  function toast(message, options) {
    options = options || {};
    const type = options.type || "info";
    const node = el("div", { class: "toast " + type }, [
      el("span", { class: "ico", html: options.icon || TOAST_ICONS[type] || TOAST_ICONS.info }),
      el("div", { class: "body" }, [
        options.title ? el("strong", { text: options.title }) : null,
        el("p", { text: message })
      ]),
      el("button", { class: "close", "aria-label": "Dismiss", onclick: () => dismiss(node) }, "×")
    ]);
    ensureToastWrap().appendChild(node);
    const timer = setTimeout(() => dismiss(node), options.duration || (type === "error" ? 7000 : 4200));
    function dismiss(n) {
      clearTimeout(timer);
      if (!n || !n.parentNode) return;
      n.classList.add("out");
      setTimeout(() => n.parentNode && n.parentNode.removeChild(n), 220);
    }
    return node;
  }

  const toastSuccess = (m, t) => toast(m, { type: "success", title: t || "Success" });
  const toastError = (m, t) => toast(m, { type: "error", title: t || "Something went wrong" });
  const toastInfo = (m, t) => toast(m, { type: "info", title: t });
  const toastWarn = (m, t) => toast(m, { type: "warn", title: t || "Heads up" });

  /* -------------------------------------------------------------- modals -- */
  function closeModal(node) {
    if (!node) return;
    document.body.style.overflow = "";
    if (node.parentNode) node.parentNode.removeChild(node);
    document.removeEventListener("keydown", node._escHandler);
  }

  function modal(options) {
    options = options || {};
    const backdrop = el("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true" });
    const box = el("div", { class: "modal" + (options.wide ? " wide" : "") });

    const closeBtn = el("button", { class: "modal-close", "aria-label": "Close dialog" }, "×");
    closeBtn.addEventListener("click", () => { closeModal(backdrop); options.onClose && options.onClose(); });

    box.appendChild(el("div", { class: "modal-head" }, [
      el("div", {}, [
        el("h3", { text: options.title || "" }),
        options.subtitle ? el("p", { text: options.subtitle }) : null
      ]),
      closeBtn
    ]));

    const body = el("div", { class: "modal-body" });
    if (typeof options.body === "string") body.innerHTML = options.body;
    else if (options.body) body.appendChild(options.body);
    box.appendChild(body);

    if (options.footer !== false) {
      const foot = el("div", { class: "modal-foot" });
      (options.buttons || []).forEach((btn) => {
        const node = el("button", { class: "btn " + (btn.class || "btn-outline"), type: btn.type || "button" }, btn.label);
        node.addEventListener("click", () => btn.onClick && btn.onClick(node, body, () => closeModal(backdrop)));
        foot.appendChild(node);
      });
      box.appendChild(foot);
    }

    backdrop.appendChild(box);
    backdrop.addEventListener("mousedown", (e) => {
      if (e.target === backdrop && options.dismissable !== false) { closeModal(backdrop); options.onClose && options.onClose(); }
    });
    backdrop._escHandler = (e) => {
      if (e.key === "Escape" && options.dismissable !== false) { closeModal(backdrop); options.onClose && options.onClose(); }
    };
    document.addEventListener("keydown", backdrop._escHandler);
    document.body.appendChild(backdrop);
    document.body.style.overflow = "hidden";

    const focusTarget = box.querySelector("input, select, textarea, button.btn-primary");
    if (focusTarget) setTimeout(() => focusTarget.focus(), 60);
    return { node: backdrop, body, close: () => closeModal(backdrop) };
  }

  function confirmDialog(options) {
    return new Promise((resolve) => {
      let settled = false;
      const done = (value) => { if (!settled) { settled = true; resolve(value); } };
      const m = modal({
        title: options.title || "Are you sure?",
        subtitle: options.subtitle,
        body: options.body ? "<p class='muted'>" + esc(options.body) + "</p>" : "",
        onClose: () => done(false),
        buttons: [
          { label: options.cancelLabel || "Cancel", class: "btn-outline", onClick: (b, body, close) => { close(); done(false); } },
          {
            label: options.confirmLabel || "Confirm",
            class: options.danger ? "btn-danger" : "btn-primary",
            onClick: (b, body, close) => {
              b.disabled = true;
              b.innerHTML = '<span class="spinner"></span> Working...';
              Promise.resolve(options.onConfirm ? options.onConfirm() : true)
                .then(() => { close(); done(true); })
                .catch((err) => {
                  b.disabled = false;
                  b.textContent = options.confirmLabel || "Confirm";
                  toastError(err && err.message ? err.message : "Action failed.");
                  done(false);
                });
            }
          }
        ]
      });
    });
  }

  function promptDialog(options) {
    return new Promise((resolve) => {
      let settled = false;
      const done = (v) => { if (!settled) { settled = true; resolve(v); } };
      const input = el("textarea", {
        class: "textarea", rows: 3, placeholder: options.placeholder || "Type here..."
      });
      if (options.value) input.value = options.value;
      const wrap = el("div", {}, [
        options.label ? el("label", { class: "label", text: options.label }) : null,
        input
      ]);
      modal({
        title: options.title || "Please confirm",
        subtitle: options.subtitle,
        body: wrap,
        onClose: () => done(null),
        buttons: [
          { label: "Cancel", class: "btn-outline", onClick: (b, body, close) => { close(); done(null); } },
          {
            label: options.confirmLabel || "Save", class: "btn-primary",
            onClick: (b, body, close) => {
              const value = input.value.trim();
              if (options.required && !value) { toastWarn("This field is required."); input.focus(); return; }
              close(); done(value);
            }
          }
        ]
      });
      setTimeout(() => input.focus(), 80);
    });
  }

  /* ----------------------------------------------------------- components */
  function badge(text, kind) { return '<span class="badge badge-' + (kind || "outline") + '">' + esc(text) + "</span>"; }

  function statusBadge(statusValue) {
    return '<span class="badge badge-dot badge-' + esc(statusValue) + '">' +
      esc(STATUS_LABELS[statusValue] || statusValue) + "</span>";
  }

  function stars(rating, count, showNumber) {
    const value = Number(rating || 0);
    const full = Math.round(value);
    let html = '<span class="stars" title="' + value.toFixed(1) + ' out of 5">';
    if (showNumber !== false) html += '<span class="num">' + (value ? value.toFixed(1) : "–") + "</span>";
    for (let i = 1; i <= 5; i++) html += '<span aria-hidden="true">' + (i <= full ? ic("star-fill") : ic("star")) + "</span>";
    if (count !== undefined && count !== null) html += '<span class="count">(' + count + ")</span>";
    return html + "</span>";
  }

  function skeletonTutorCards(count) {
    let html = "";
    for (let i = 0; i < (count || 6); i++) {
      html += '<div class="sk-card"><div class="skeleton sk-media"></div><div class="sk-body">' +
        '<div class="skeleton sk-line" style="width:55%;height:16px"></div>' +
        '<div class="skeleton sk-line" style="width:80%"></div>' +
        '<div class="skeleton sk-line" style="width:65%"></div>' +
        '<div class="skeleton sk-line" style="width:40%;height:34px;border-radius:999px"></div>' +
        "</div></div>";
    }
    return html;
  }

  function skeletonRows(count, cols) {
    let html = "";
    for (let i = 0; i < (count || 4); i++) {
      html += '<div class="list-item">';
      html += '<div class="skeleton" style="width:52px;height:52px;border-radius:14px"></div>';
      html += '<div class="main stack" style="gap:8px;flex:1">';
      for (let c = 0; c < (cols || 3); c++) {
        html += '<div class="skeleton sk-line" style="width:' + (c === 0 ? 45 : 70 - c * 12) + '%"></div>';
      }
      html += "</div></div>";
    }
    return html;
  }

  function emptyState(options) {
    options = options || {};
    return '<div class="empty"><div class="ico">' + (options.icon || ic("search")) + "</div>" +
      "<h3>" + esc(options.title || "Nothing here yet") + "</h3>" +
      "<p>" + esc(options.message || "") + "</p>" +
      (options.actionLabel ? '<a class="btn btn-primary" href="' + esc(options.actionHref || "#") + '">' +
        esc(options.actionLabel) + "</a>" : "") +
      "</div>";
  }

  function errorState(message, retryLabel) {
    return '<div class="empty"><div class="ico">' + ic("exclamation-triangle-fill") + '</div>' +
      "<h3>We could not load this</h3><p>" + esc(message || "Unexpected error.") + "</p>" +
      (retryLabel ? '<button class="btn btn-primary" data-retry>' + esc(retryLabel) + "</button>" : "") +
      "</div>";
  }

  function pagination(page, pages, onChange) {
    if (pages <= 1) return null;
    const wrap = el("div", { class: "pagination" });
    const mk = (label, target, opts) => {
      opts = opts || {};
      const btn = el("button", {
        class: "page-btn" + (opts.active ? " active" : ""),
        disabled: opts.disabled || false, "aria-label": label
      }, label);
      if (!opts.disabled && !opts.active) btn.addEventListener("click", () => onChange(target));
      return btn;
    };
    wrap.appendChild(mk("‹", page - 1, { disabled: page <= 1 }));
    const windowSize = 5;
    let start = Math.max(1, page - Math.floor(windowSize / 2));
    let end = Math.min(pages, start + windowSize - 1);
    start = Math.max(1, end - windowSize + 1);
    if (start > 1) {
      wrap.appendChild(mk("1", 1));
      if (start > 2) wrap.appendChild(el("span", { class: "page-btn", style: { border: "0", background: "none" } }, "…"));
    }
    for (let i = start; i <= end; i++) wrap.appendChild(mk(String(i), i, { active: i === page }));
    if (end < pages) {
      if (end < pages - 1) wrap.appendChild(el("span", { class: "page-btn", style: { border: "0", background: "none" } }, "…"));
      wrap.appendChild(mk(String(pages), pages));
    }
    wrap.appendChild(mk("›", page + 1, { disabled: page >= pages }));
    return wrap;
  }

  /* ---------------------------------------------------------------- nav --- */
  const NAV_LINKS = [
    { href: "index.html", label: "Home", match: ["index.html", ""] },
    { href: "tutors.html", label: "Find Tutors", match: ["tutors.html", "tutor-profile.html"] },
    { href: "dashboard.html", label: "Dashboard", match: ["dashboard.html"], auth: true }
  ];

  function buildNav() {
    const mount = document.getElementById("nav");
    if (!mount || mount.dataset.built === "1") return;
    mount.dataset.built = "1";

    const user = API.user;
    const page = (location.pathname.split("/").pop() || "index.html").toLowerCase();

    const links = NAV_LINKS.filter((l) => !l.auth || API.isAuthenticated());
    const navLinks = el("div", { class: "nav-links" });
    links.forEach((link) => {
      const active = link.match.some((m) => m === page);
      navLinks.appendChild(el("a", { href: link.href, class: "nav-link" + (active ? " active" : ""), text: link.label }));
    });

    const actions = el("div", { class: "nav-actions" });

    if (user) {
      // notification bell
      const bellWrap = el("div", { class: "dropdown", style: { position: "relative" } });
      const bell = el("button", { class: "bell", "aria-label": "Notifications", title: "Notifications" },
        [el("span", { html: ic("bell-fill") })]);
      const dot = el("span", { class: "bell-dot hide", text: "0" });
      bell.appendChild(dot);
      bellWrap.appendChild(bell);
      actions.appendChild(bellWrap);

      let panel = null;
      bell.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (panel) { panel.remove(); panel = null; return; }
        panel = el("div", { class: "notif-panel" });
        panel.innerHTML = '<div class="notif-head"><strong>Notifications</strong></div>' +
          '<div class="notif-list"><div style="padding:26px" class="center muted small">Loading…</div></div>';
        bellWrap.appendChild(panel);
        panel.addEventListener("click", (ev) => ev.stopPropagation());
        try {
          const data = await API.notifications({ limit: 15 });
          renderNotifications(panel, data);
        } catch (err) {
          panel.innerHTML = '<div class="notif-head"><strong>Notifications</strong></div>' +
            '<div class="notif-list"><div class="empty" style="border:0;padding:26px"><p>' + esc(err.message) + "</p></div></div>";
        }
      });

      async function refreshBell() {
        if (!API.isAuthenticated()) return;
        try {
          const data = await API.unreadCount();
          dot.textContent = data.unread_count > 99 ? "99+" : String(data.unread_count);
          dot.classList.toggle("hide", !data.unread_count);
        } catch (e) { dot.classList.add("hide"); }
      }
      refreshBell();
      global._tmRefreshBell = refreshBell;

      // avatar menu
      const menuWrap = el("div", { class: "dropdown" });
      const first = String(user.full_name || "U").split(" ")[0];
      const avatarBtn = el("button", { class: "avatar-btn", "aria-label": "Account menu" });
      if (user.avatar_url) {
        const img = el("img", { src: user.avatar_url, alt: "", style: { width: "32px", height: "32px", borderRadius: "10px", objectFit: "cover" } });
        img.addEventListener("error", () => img.replaceWith(el("div", { class: "avatar avatar-sm avatar-fallback", text: initials(user.full_name) })));
        avatarBtn.appendChild(img);
      } else {
        avatarBtn.appendChild(el("div", { class: "avatar avatar-sm avatar-fallback", text: initials(user.full_name) }));
      }
      avatarBtn.appendChild(el("span", { class: "name hide-sm", text: first }));
      avatarBtn.appendChild(el("span", { class: "tiny faint", html: ic("chevron-down") }));
      menuWrap.appendChild(avatarBtn);

      const menu = el("div", { class: "dropdown-menu hide" });
      menu.appendChild(el("div", { class: "dropdown-head" }, [
        el("strong", { text: user.full_name }),
        el("span", { text: user.email })
      ]));
      const linksForRole = [
        { href: "dashboard.html", label: "Dashboard", icon: ic("bar-chart-fill") },
        user.role === "tutor" ? { href: "dashboard.html?view=profile", label: "My tutor profile", icon: ic("mortarboard-fill") } : null,
        user.role === "student" ? { href: "dashboard.html?view=requests", label: "My requests", icon: ic("envelope-fill") } : null,
        user.role === "student" ? { href: "dashboard.html?view=saved", label: "Saved tutors", icon: ic("heart-fill") } : null,
        user.role === "admin" ? { href: "dashboard.html?view=users", label: "Manage users", icon: ic("people-fill") } : null,
        { href: "dashboard.html?view=account", label: "Account settings", icon: ic("gear-fill") }
      ].filter(Boolean);
      linksForRole.forEach((l) => menu.appendChild(el("a", { href: l.href }, [el("span", { html: l.icon }), l.label])));
      menu.appendChild(el("div", { class: "dropdown-sep" }));
      const logoutBtn = el("button", { class: "danger", type: "button" }, [el("span", { html: ic("box-arrow-right") }), "Sign out"]);
      logoutBtn.addEventListener("click", async () => {
        logoutBtn.disabled = true;
        await API.logout();
        toastInfo("You have been signed out.");
        location.href = "index.html";
      });
      menu.appendChild(logoutBtn);
      menuWrap.appendChild(menu);

      avatarBtn.addEventListener("click", (e) => { e.stopPropagation(); menu.classList.toggle("hide"); closePanel(); });
      document.addEventListener("click", () => { menu.classList.add("hide"); });
      function closePanel() { if (panel) { panel.remove(); panel = null; } }
      actions.appendChild(menuWrap);
    } else {
      actions.appendChild(el("a", { href: "login.html", class: "btn btn-ghost hide-sm" }, "Sign in"));
      actions.appendChild(el("a", { href: "register.html", class: "btn btn-primary btn-sm" }, "Get started"));
    }

    const toggle = el("button", { class: "nav-toggle", "aria-label": "Open menu", "aria-expanded": "false" }, [el("span")]);
    const mobile = el("div", { class: "mobile-menu", id: "mobileMenu" });
    links.forEach((link) => mobile.appendChild(el("a", { href: link.href, text: link.label })));
    if (!user) {
      mobile.appendChild(el("a", { href: "login.html", text: "Sign in" }));
      mobile.appendChild(el("a", { href: "register.html", text: "Create account" }));
    }
    toggle.addEventListener("click", () => {
      const open = mobile.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });

    mount.innerHTML = "";
    const inner = el("div", { class: "container nav-inner" });
    inner.appendChild(el("a", { href: "index.html", class: "brand" }, [
      el("span", { class: "brand-mark", text: "TC" }),
      el("span", {}, [document.createTextNode(CFG.app_name)])
    ]));
    inner.appendChild(navLinks);
    inner.appendChild(actions);
    inner.appendChild(toggle);
    mount.appendChild(inner);
    mount.appendChild(mobile);
  }

  function renderNotifications(panel, data) {
    const items = (data && data.items) || [];
    const head = el("div", { class: "notif-head" }, [
      el("strong", {}, [document.createTextNode("Notifications "), el("span", { class: "badge badge-primary", text: String(data.unread_count || 0) + " unread" })]),
      data.unread_count ? el("button", { class: "btn btn-sm btn-ghost", type: "button", text: "Mark all read" }) : null
    ]);
    const markAll = head.querySelector("button");
    if (markAll) {
      markAll.addEventListener("click", async () => {
        try {
          await API.readAllNotifications();
          toastSuccess("All notifications marked as read.");
          const fresh = await API.notifications({ limit: 15 });
          panel.innerHTML = "";
          renderNotifications(panel, fresh);
          global._tmRefreshBell && global._tmRefreshBell();
        } catch (err) { toastError(err.message); }
      });
    }

    const list = el("div", { class: "notif-list" });
    if (!items.length) {
      list.appendChild(el("div", { class: "center muted small", style: { padding: "30px 18px" } },
        [el("div", { style: { fontSize: "1.6rem", marginBottom: "8px" }, html: ic("bell-slash") }), "You're all caught up."]));
    }
    items.forEach((note) => {
      const row = el("a", {
        href: note.link || "#", class: "notif-item" + (note.is_read ? "" : " unread"),
        style: { color: "inherit", display: "flex" }
      }, [
        el("span", { class: "notif-icon", html: iconFor(note.type) }),
        el("div", { class: "notif-body" }, [
          el("strong", { text: note.title }),
          note.body ? el("p", { text: note.body }) : null,
          el("div", { class: "notif-time", text: timeAgo(note.created_at) })
        ])
      ]);
      row.addEventListener("click", async () => {
        if (!note.is_read) { try { await API.readNotification(note.id); } catch (e) {} }
      });
      list.appendChild(row);
    });

    panel.innerHTML = "";
    panel.appendChild(head);
    panel.appendChild(list);
  }

  function iconFor(type) {
    const map = {
      request_new: ic("envelope-fill"), request_accepted: ic("check-circle-fill"), request_rejected: ic("x-circle-fill"),
      request_cancelled: ic("slash-circle"), request_completed: ic("flag-fill"), review_new: ic("star-fill"),
      profile_approved: ic("patch-check-fill"), profile_suspended: ic("lock-fill"), account: ic("person-fill")
    };
    return map[type] || ic("bell-fill");
  }

  /* ------------------------------------------------------------- footer --- */
  function buildFooter() {
    const mount = document.getElementById("footer");
    if (!mount || mount.dataset.built === "1") return;
    mount.dataset.built = "1";
    const year = new Date().getFullYear();
    mount.innerHTML =
      '<div class="container">' +
        '<div class="footer-grid">' +
          "<div>" +
            '<a class="brand" href="index.html"><span class="brand-mark">TC</span>' +
            "<span>" + esc(CFG.app_name) + "</span></a>" +
            "<p>" + esc(CFG.tagline || "Find the right tutor. Learn with confidence.") +
            " Match with verified tutors by subject, location, experience, availability and budget — then request a session in minutes.</p>" +
            '<div class="row" style="gap:8px;margin-top:6px">' +
              '<span class="badge badge-glass" style="background:rgba(255,255,255,.1);color:#fff">' + ic("lock-fill") + ' JWT secured</span>' +
              '<span class="badge" style="background:rgba(255,255,255,.1);color:#fff">' + ic("database-fill") + ' Live database</span>' +
            "</div>" +
          "</div>" +
          "<div><h4>For students &amp; parents</h4><ul>" +
            '<li><a href="tutors.html">Browse tutors</a></li>' +
            '<li><a href="tutors.html?mode=online">Online tutoring</a></li>' +
            '<li><a href="register.html?role=student">Create an account</a></li>' +
            '<li><a href="dashboard.html">Track requests</a></li>' +
          "</ul></div>" +
          "<div><h4>For tutors</h4><ul>" +
            '<li><a href="register.html?role=tutor">Become a tutor</a></li>' +
            '<li><a href="dashboard.html?view=availability">Set availability</a></li>' +
            '<li><a href="dashboard.html?view=requests">Manage requests</a></li>' +
            '<li><a href="dashboard.html?view=reviews">Your reviews</a></li>' +
          "</ul></div>" +
          "<div><h4>Platform</h4><ul>" +
            '<li><a href="/docs" target="_blank" rel="noopener">API documentation</a></li>' +
            '<li><a href="/api/health" target="_blank" rel="noopener">System status</a></li>' +
            '<li><a href="login.html">Admin sign in</a></li>' +
            '<li><a href="index.html#how">How it works</a></li>' +
          "</ul></div>" +
        "</div>" +
        '<div class="footer-bottom">' +
          "<span>© " + year + " " + esc(CFG.app_name) + ". Built as a full-stack MVP — FastAPI + SQLAlchemy + PostgreSQL/SQLite.</span>" +
        "</div>" +
      "</div>";
  }

  /* -------------------------------------------------------------- charts -- */
  const DONUT_COLORS = ["#4f46e5", "#0ea5a4", "#f59e0b", "#e11d48", "#8b5cf6", "#22c55e"];

  function donut(items, centerValue, centerLabel) {
    const total = items.reduce((sum, i) => sum + Number(i.value || 0), 0);
    const radius = 62, circumference = 2 * Math.PI * radius;
    let offset = 0;
    let circles = "";
    let legend = "";
    items.forEach((item, index) => {
      const value = Number(item.value || 0);
      const pct = total ? value / total : 0;
      const dash = pct * circumference;
      circles += '<circle cx="79" cy="79" r="' + radius + '" fill="none" stroke="' + DONUT_COLORS[index % DONUT_COLORS.length] +
        '" stroke-width="18" stroke-dasharray="' + dash.toFixed(2) + " " + (circumference - dash).toFixed(2) +
        '" stroke-dashoffset="' + (-offset).toFixed(2) + '" stroke-linecap="butt"><title>' +
        esc(item.label) + ": " + value + "</title></circle>";
      offset += dash;
      legend += '<div><span class="swatch" style="background:' + DONUT_COLORS[index % DONUT_COLORS.length] + '"></span>' +
        esc(item.label) + '<span class="n">' + value + "</span></div>";
    });
    return '<div class="donut-wrap"><div class="donut">' +
      '<svg width="158" height="158" viewBox="0 0 158 158" role="img" aria-label="Distribution chart">' +
      '<circle cx="79" cy="79" r="' + radius + '" fill="none" stroke="#eef1f8" stroke-width="18"></circle>' +
      circles + "</svg>" +
      '<div class="center-label"><div><strong>' + (centerValue !== undefined ? centerValue : total) + "</strong><span>" +
      esc(centerLabel || "total") + "</span></div></div></div>" +
      '<div class="legend">' + (legend || "<div class='muted small'>No data yet.</div>") + "</div></div>";
  }

  function barList(items, options) {
    options = options || {};
    if (!items || !items.length) return '<p class="muted small">No data yet.</p>';
    const max = Math.max.apply(null, items.map((i) => Number(i.value || 0)).concat([1]));
    return '<div class="bars">' + items.map((item) => {
      const pct = Math.max(2, Math.round((Number(item.value || 0) / max) * 100));
      const label = options.formatter ? options.formatter(item.value) : item.value;
      return '<div class="bar-item"><span class="lbl" title="' + esc(item.label) + '">' + esc(item.label) + "</span>" +
        '<span class="track"><i style="width:' + pct + '%"></i></span>' +
        '<span class="val">' + esc(label) + "</span></div>";
    }).join("") + "</div>";
  }

  function sparkline(items, options) {
    options = options || {};
    if (!items || !items.length) return '<p class="muted small">No data yet.</p>';
    const max = Math.max.apply(null, items.map((i) => Number(i.value || 0)).concat([1]));
    const cols = items.map((item) => {
      const pct = Math.max(4, Math.round((Number(item.value || 0) / max) * 100));
      return '<span class="col" style="height:' + pct + '%" data-label="' + esc(item.label) + '" data-value="' +
        esc(options.valueFormatter ? options.valueFormatter(item.value) : item.value) + '"></span>';
    }).join("");
    const labels = items.map((item, i) =>
      "<span>" + (i % Math.ceil(items.length / 7) === 0 ? esc(item.label) : "") + "</span>").join("");
    return '<div class="spark">' + cols + '</div><div class="spark-labels">' + labels + "</div>";
  }

  /* --------------------------------------------------------------- misc --- */
  function setLoading(button, loading, label) {
    if (!button) return;
    if (loading) {
      button.dataset.originalHtml = button.innerHTML;
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      button.innerHTML = '<span class="spinner"></span> ' + esc(label || "Working...");
    } else {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
    }
  }

  function showFieldErrors(form, errors) {
    if (!form) return;
    form.querySelectorAll(".field").forEach((f) => f.classList.remove("invalid"));
    (errors || []).forEach((err) => {
      const input = form.querySelector('[name="' + CSS.escape(err.field) + '"]');
      if (!input) return;
      const field = input.closest(".field");
      if (!field) return;
      field.classList.add("invalid");
      const slot = field.querySelector(".field-error");
      if (slot) slot.textContent = err.message;
    });
  }

  function passwordStrength(value) {
    let score = 0;
    if (!value) return { score: 0, label: "" };
    if (value.length >= 8) score++;
    if (value.length >= 12) score++;
    if (/[A-Z]/.test(value) && /[a-z]/.test(value)) score++;
    if (/\d/.test(value)) score++;
    if (/[^A-Za-z0-9]/.test(value)) score++;
    score = Math.min(4, Math.max(1, Math.ceil(score * 0.8)));
    const labels = ["", "Weak", "Fair", "Good", "Strong"];
    return { score, label: labels[score] };
  }

  function debounce(fn, wait) {
    let timer;
    return function () {
      const args = arguments, ctx = this;
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(ctx, args), wait || 300);
    };
  }

  function readQueryParams() {
    const params = new URLSearchParams(location.search);
    const out = {};
    params.forEach((value, key) => { out[key] = value; });
    return out;
  }

  function writeQueryParams(params, replace) {
    const usp = new URLSearchParams();
    Object.keys(params || {}).forEach((key) => {
      const value = params[key];
      if (value === undefined || value === null || value === "") return;
      usp.set(key, value);
    });
    const search = usp.toString();
    const url = location.pathname + (search ? "?" + search : "");
    if (replace) history.replaceState({}, "", url);
    else history.pushState({}, "", url);
  }

  async function loadConfig() {
    try {
      const cfg = await API.config();
      Object.assign(CFG, cfg);
      document.documentElement.style.setProperty("--currency", CFG.currency_symbol);
    } catch (e) { /* keep defaults */ }
    return CFG;
  }

  /* --------------------------------------------- device photo handling --- */
  const MAX_IMAGE_BYTES = 3 * 1024 * 1024;
  const OK_IMAGE_TYPES = ["image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"];

  /** Read a File chosen from the user's device into a data URL (with validation). */
  function readImageFile(file) {
    return new Promise((resolve, reject) => {
      if (!file) { reject(new Error("Choose an image file first.")); return; }
      const type = String(file.type || "").toLowerCase();
      if (OK_IMAGE_TYPES.indexOf(type) === -1) {
        reject(new Error("That file type isn't supported. Use PNG, JPG, GIF or WebP."));
        return;
      }
      if (file.size > MAX_IMAGE_BYTES) {
        reject(new Error("That image is too large (max 3 MB). Please pick a smaller one."));
        return;
      }
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error("Could not read that file. Please try another image."));
      reader.readAsDataURL(file);
    });
  }

  /**
   * Photo picker widget: upload from device, preview, replace (edit) and remove.
   * options:
   *   currentUrl   — existing photo to preview (remote or local)
   *   currentName  — name used for the initials fallback
   *   onSelect(dataUrl, file) — async; called after a valid file is chosen.
   *                             Throw to signal failure (error shows in the widget).
   *   onRemove()   — async; called when an already-saved photo is removed.
   */
  function photoPicker(options) {
    const opts = Object.assign({ currentUrl: "", currentName: "", onSelect: null, onRemove: null }, options || {});
    let pending = null;                     // { file, dataUrl } chosen but not yet saved
    let currentUrl = opts.currentUrl || "";
    let busy = false;

    const root = el("div", { class: "photo-picker" });
    const preview = el("div", { class: "photo-preview" });
    const controls = el("div", { class: "photo-controls" });
    const buttons = el("div", { class: "photo-buttons" });
    const fileInput = el("input", {
      type: "file", accept: "image/png,image/jpeg,image/gif,image/webp",
      style: "display:none", "aria-label": "Choose a photo from your device"
    });
    const pickBtn = el("button", { class: "btn btn-outline btn-sm", type: "button" });
    const removeBtn = el("button", { class: "btn btn-soft-danger btn-sm hide", type: "button", html: ic("trash-fill") + " Remove photo" });
    const hint = el("span", { class: "hint" }, "Upload from your device — PNG, JPG, GIF or WebP, up to 3 MB. You can change or remove it anytime.");
    const errSlot = el("span", { class: "field-error" });

    buttons.appendChild(pickBtn);
    buttons.appendChild(removeBtn);
    controls.appendChild(buttons);
    controls.appendChild(hint);
    root.appendChild(preview);
    root.appendChild(controls);
    root.appendChild(fileInput);
    root.appendChild(errSlot);

    function paint() {
      preview.innerHTML = "";
      pickBtn.innerHTML = ic("camera-fill") + ((pending || currentUrl) ? " Change photo" : " Upload photo");
      removeBtn.classList.toggle("hide", !pending && !currentUrl);
      if (pending) {
        preview.appendChild(el("img", { src: pending.dataUrl, alt: "Profile photo preview" }));
      } else if (currentUrl) {
        preview.appendChild(image(currentUrl, "Profile photo", "", opts.currentName || "You"));
      } else {
        preview.appendChild(el("div", { class: "photo-placeholder", "aria-hidden": "true", html: ic("person-fill") }));
      }
    }

    fileInput.addEventListener("change", async () => {
      const file = fileInput.files && fileInput.files[0];
      fileInput.value = "";                    // allow re-picking the same file later
      if (!file || busy) return;
      errSlot.textContent = "";
      let dataUrl;
      try { dataUrl = await readImageFile(file); }
      catch (err) { errSlot.textContent = err.message; return; }
      pending = { file: file, dataUrl: dataUrl };
      paint();
      if (opts.onSelect) {
        busy = true; pickBtn.disabled = true; removeBtn.disabled = true;
        try { await opts.onSelect(dataUrl, file); }
        catch (err) { errSlot.textContent = err.message || "Upload failed. Please try again."; pending = null; paint(); }
        finally { busy = false; pickBtn.disabled = false; removeBtn.disabled = false; }
      }
    });

    removeBtn.addEventListener("click", async () => {
      if (busy) return;
      errSlot.textContent = "";
      if (pending) { pending = null; paint(); return; }        // discard the new choice
      if (currentUrl && opts.onRemove) {
        busy = true; removeBtn.disabled = true;
        try { await opts.onRemove(); currentUrl = ""; paint(); }
        catch (err) { errSlot.textContent = err.message || "Could not remove the photo."; }
        finally { busy = false; removeBtn.disabled = false; }
      }
    });

    pickBtn.addEventListener("click", () => { if (!busy) fileInput.click(); });

    paint();
    return {
      el: root,
      pending: () => pending,
      clearPending() { pending = null; paint(); },
      setCurrent(url) { currentUrl = url || ""; pending = null; paint(); },
      setError(msg) { errSlot.textContent = msg || ""; }
    };
  }

  /* -------------------------------------------------- password eye toggle -- */
  /** Wrap every password input in `scope` with a show/hide (eye) button. */
  function addPasswordToggles(scope) {
    const root = scope || document;
    root.querySelectorAll('input[type="password"]').forEach((input) => {
      if (input.dataset.pwToggle === "wired") return;
      input.dataset.pwToggle = "wired";
      let wrap = input.closest(".pw-wrap");
      if (!wrap) {
        wrap = el("span", { class: "pw-wrap" });
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);
      }
      const btn = el("button", {
        class: "pw-toggle", type: "button",
        "aria-label": "Show password", title: "Show password",
        html: ic("eye-fill")
      });
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.innerHTML = show ? ic("eye-slash-fill") : ic("eye-fill");
        btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
        btn.title = show ? "Hide password" : "Show password";
      });
      wrap.appendChild(btn);
    });
  }

  /* ------------------------------------------- dropdown option libraries -- */
  /* Curated pick-lists shared by the registration form and the tutor profile
     editor so both surfaces offer identical, valid choices. */
  const NG_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue",
    "Borno", "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu", "Gombe",
    "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi", "Kwara",
    "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau",
    "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara",
    "Federal Capital Territory (Abuja)"
  ];

  const TUTOR_HEADLINES = [
    "Mathematics & Further Mathematics tutor (WAEC, NECO, JAMB)",
    "English & Literature tutor (WAEC, NECO, JAMB)",
    "Physics, Chemistry & Biology tutor (senior secondary)",
    "Chemistry & Biology tutor for senior secondary students",
    "Primary school tutor (all subjects, Grades 1-6)",
    "ICT, Computer Science & Coding tutor",
    "Economics, Government & Commerce tutor",
    "Accounting & Business Studies tutor",
    "Geography & Environmental Science tutor",
    "History & Social Studies tutor",
    "Music, Piano & Voice tutor",
    "French & Foreign Languages tutor",
    "JAMB / UTME & Post-UTME coaching specialist",
    "IGCSE, SAT & IELTS preparation specialist",
    "Special-needs & home-schooling tutor",
    "University admission & essay-writing coach"
  ];

  const QUALIFICATION_OPTIONS = [
    "B.Sc. / B.A. / B.Eng. (Bachelor's degree)",
    "B.Sc. / B.A. (First Class Honours)",
    "Master's degree (M.Sc. / M.A. / M.Eng.)",
    "Doctorate (PhD / EdD)",
    "MBBS / BDS (Medical degree)",
    "NCE (Nigeria Certificate in Education)",
    "PGDE / Postgraduate Diploma in Education",
    "HND / Diploma",
    "Professional certification (ICAN, CIBN, CISCO, TRCN)",
    "WAEC / NECO certificate + verifiable teaching experience"
  ];

  /* Fill a <select> with a placeholder + options. If `current` holds a value
     that is not in the list (e.g. an older free-text profile), it is kept as
     the first real option so editing never loses existing data. */
  function fillSelect(sel, options, placeholder, current) {
    if (!sel) return;
    sel.innerHTML = "";
    sel.appendChild(el("option", { value: "" }, placeholder || "Select…"));
    (options || []).forEach((o) => sel.appendChild(el("option", { value: o }, o)));
    if (current) {
      const has = Array.from(sel.options).some((op) => op.value === current);
      if (!has && sel.options[1]) sel.insertBefore(el("option", { value: current }, current), sel.options[1]);
      else if (!has) sel.appendChild(el("option", { value: current }, current));
      sel.value = current;
    }
  }

  /* V-shaped subject picker: a single <select> adds subjects as removable
     chips. Each chip carries a hidden checked checkbox, so any existing code
     that collects `input:checked` inside the chip host keeps working.
     Subject emojis (s.icon) are kept on purpose. */
  function subjectDropdown(selectEl, chipHost, subjects, selectedIds, onChange) {
    if (!selectEl || !chipHost) return { getIds: () => [] };
    const subs = subjects || [];
    const picked = new Set((selectedIds || []).map(Number));

    function chip(id) {
      const s = subs.find((x) => x.id === id);
      const box = el("input", { type: "checkbox", name: "subject_ids", value: String(id), style: { display: "none" } });
      box.checked = true;
      const wrap = el("span", {
        style: {
          display: "inline-flex", alignItems: "center", gap: "8px", padding: "6px 12px",
          border: "1.5px solid var(--border-strong)", borderRadius: "999px",
          background: "var(--bg-soft, #f4f1ff)", fontSize: "13px", fontWeight: "600"
        }
            }, [box, el("span", { html: (s && s.icon ? subjectIcon(s.icon) + " " : "") + esc(s ? s.name : "Subject #" + id) })]);
      const x = el("button", {
        type: "button", title: "Remove subject",
        style: { border: "0", background: "none", cursor: "pointer", fontSize: "15px", lineHeight: "1", color: "inherit", padding: "0 2px" }
      }, "×");
      x.addEventListener("click", () => { picked.delete(id); render(); if (onChange) onChange(); });
      wrap.appendChild(x);
      return wrap;
    }

    function render() {
      chipHost.innerHTML = "";
      picked.forEach((id) => chipHost.appendChild(chip(id)));
      if (!picked.size) {
        chipHost.appendChild(el("p", { class: "muted small", style: { margin: "2px 0 0" } },
          "No subjects added yet — pick one from the list above."));
      }
      selectEl.innerHTML = "";
      selectEl.appendChild(el("option", { value: "" }, picked.size ? "Add another subject…" : "Select a subject to add…"));
      subs.forEach((s) => {
                if (!picked.has(s.id)) selectEl.appendChild(el("option", { value: String(s.id) }, (s.icon && String(s.icon).indexOf("bi-") !== 0 ? s.icon + " " : "") + s.name));
      });
    }

    selectEl.addEventListener("change", () => {
      const id = Number(selectEl.value);
      if (id && !picked.has(id)) { picked.add(id); render(); if (onChange) onChange(); }
      selectEl.value = "";
    });
    render();
    return { getIds: () => Array.from(picked) };
  }

  global.UI = {
    CFG, money, esc, el, image, photo, initials, to12h, formatDate, formatDayDate, relativeDate,
    timeAgo, plural, toast, toastSuccess, toastError, toastInfo, toastWarn,
    modal, closeModal, confirmDialog, promptDialog,
    badge, statusBadge, stars, skeletonTutorCards, skeletonRows, emptyState, errorState,
    pagination, buildNav, buildFooter, donut, barList, sparkline, setLoading, showFieldErrors,
    passwordStrength, debounce, readQueryParams, writeQueryParams, loadConfig,
    readImageFile, photoPicker, addPasswordToggles,
    MODE_LABELS, STATUS_LABELS, DAYS,
        NG_STATES, TUTOR_HEADLINES, QUALIFICATION_OPTIONS, fillSelect, subjectDropdown, subjectIcon
  };
  
})(window);