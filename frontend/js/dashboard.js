/* ==========================================================================
   dashboard.js — role-aware dashboard shell.

   Routes:  ?view=overview | profile | availability | requests | reviews |
                     saved | account | users | tutors | moderation | subjects
   Tutor views, student views and admin views are all rendered from live API
   data.  Every action (accept, reject, complete, cancel, save, delete) writes
   to the database and refreshes the UI from the response.
   ========================================================================== */
(function () {
  "use strict";

  const { esc, money, el, stars, to12h, formatDate, formatDayDate, relativeDate, timeAgo,
          plural, toastSuccess, toastError, toastInfo, toastWarn, statusBadge,
          MODE_LABELS, DAYS, setLoading, donut, barList, sparkline } = UI;

  /* icon helper: ic("search") -> <i class="bi bi-search"></i> */
  const ic = (name) => '<i class="bi bi-' + name + '"></i>';
  /* meta line helper: icon + escaped text */
  const metaSpan = (iconName, text) => el("span", { html: ic(iconName) + " " + esc(text) });

  const viewHost = () => document.getElementById("viewHost");
  let ME = null;
  let CURRENT_VIEW = "overview";
  let TUTOR_PROFILE = null;
  let STUDENT_PROFILE = null;

  const VIEW_DEFS = {
    tutor: [
      { id: "overview", label: "Overview", icon: ic("bar-chart-fill") },
      { id: "requests", label: "Requests", icon: ic("envelope-fill") },
      { id: "availability", label: "Availability", icon: ic("calendar3") },
      { id: "profile", label: "My profile", icon: ic("mortarboard-fill") },
      { id: "reviews", label: "Reviews", icon: ic("star-fill") },
      { id: "account", label: "Account settings", icon: ic("gear-fill") }
    ],
    student: [
      { id: "overview", label: "Overview", icon: ic("bar-chart-fill") },
      { id: "requests", label: "My requests", icon: ic("envelope-fill") },
      { id: "saved", label: "Saved tutors", icon: ic("heart-fill") },
      { id: "browse", label: "Find tutors", icon: ic("search"), href: "tutors.html" },
      { id: "profile", label: "My profile", icon: ic("backpack-fill") },
      { id: "reviews", label: "My reviews", icon: ic("star-fill") },
      { id: "account", label: "Account settings", icon: ic("gear-fill") }
    ],
    admin: [
      { id: "overview", label: "Platform overview", icon: ic("bar-chart-fill") },
      { id: "users", label: "Users", icon: ic("people-fill") },
      { id: "tutors", label: "Tutors", icon: ic("mortarboard-fill") },
      { id: "requests", label: "Bookings", icon: ic("envelope-fill") },
      { id: "reviews", label: "Reviews", icon: ic("star-fill") },
      { id: "subjects", label: "Subjects", icon: ic("book-fill") },
      { id: "activity", label: "Activity log", icon: ic("clock-fill") },
      { id: "account", label: "Account settings", icon: ic("gear-fill") }
    ]
  };

  /* -------------------------------------------------------------- init --- */
  async function init() {
    const ok = await App.boot({ requireAuth: true });
    if (!ok) return;

    ME = await API.refreshMe();
    if (!ME) { location.replace("login.html"); return; }

    const params = UI.readQueryParams();
    const allowed = (VIEW_DEFS[ME.role] || []).map((v) => v.id);
    CURRENT_VIEW = allowed.indexOf(params.view) >= 0 ? params.view : "overview";

    renderHeader();
    renderSidebar();

    if (params.onboard === "1" && ME.role === "tutor") {
      toastInfo("Great start! Add the days and times you can teach so students can request you.", "Set your availability");
    }

    await route();
    window.addEventListener("popstate", async () => {
      const p = UI.readQueryParams();
      CURRENT_VIEW = allowed.indexOf(p.view) >= 0 ? p.view : "overview";
      renderSidebar();
      await route();
    });
  }

  function go(view, extra) {
    const params = Object.assign({ view }, extra || {});
    UI.writeQueryParams(params, false);
    CURRENT_VIEW = view;
    renderSidebar();
    route();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function route() {
    const host = viewHost();
    host.innerHTML = '<div class="stack"><div class="skeleton" style="height:120px;border-radius:18px"></div>' +
      '<div class="skeleton" style="height:280px;border-radius:18px"></div></div>';
    try {
      const key = ME.role + ":" + CURRENT_VIEW;
      const renderer = ROUTES[key] || ROUTES[ME.role + ":overview"];
      await renderer(host);
    } catch (err) {
      host.innerHTML = UI.errorState(err.message, "Retry");
      const retry = host.querySelector("[data-retry]");
      if (retry) retry.addEventListener("click", () => route());
      toastError(err.message);
    }
  }

  /* ---------------------------------------------------------- chrome ----- */
  function renderHeader() {
    const first = String(ME.full_name || "").split(" ")[0];
    const hour = new Date().getHours();
    const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
    document.getElementById("dashGreeting").textContent = greeting + ", " + first;
    document.getElementById("dashRole").textContent =
      ME.role === "student"
        ? (App.personaFor(ME) === "parent" ? "Parent workspace" : "Student workspace")
        : { tutor: "Tutor workspace", admin: "Administrator console" }[ME.role];

    const actions = document.getElementById("dashQuickActions");
    actions.innerHTML = "";
    if (ME.role === "student") {
      actions.appendChild(el("a", { class: "btn btn-primary btn-sm", href: "tutors.html", html: ic("search") + " Find tutors" }));
    }
    if (ME.role === "tutor") {
      const b = el("button", { class: "btn btn-glass btn-sm", type: "button", html: ic("calendar3") + " Manage availability" });
      b.addEventListener("click", () => go("availability"));
      actions.appendChild(b);
    }
    if (ME.role === "admin") {
      actions.appendChild(el("a", { class: "btn btn-glass btn-sm", href: "/docs", target: "_blank", rel: "noopener", html: ic("plug-fill") + " API docs" }));
    }
  }

  function renderSidebar() {
    const userBox = document.getElementById("sideUser");
    userBox.innerHTML = "";
    userBox.appendChild(el("div", { class: "side-user" }, [
      ME.avatar_url
        ? UI.image(ME.avatar_url, ME.full_name, "", ME.full_name)
        : el("div", { class: "avatar avatar-fallback", style: { width: "50px", height: "50px" }, text: UI.initials(ME.full_name) }),
      el("div", {}, [
        el("strong", { text: ME.full_name }),
        el("span", { text: App.roleLabel(ME.role, ME) })
      ])
    ]));

    const nav = document.getElementById("sideNav");
    nav.innerHTML = "";
    (VIEW_DEFS[ME.role] || []).forEach((item) => {
      if (item.href) {
        nav.appendChild(el("a", { href: item.href }, [el("span", { class: "ico", html: item.icon }), item.label]));
        return;
      }
      const btn = el("button", {
        type: "button", class: CURRENT_VIEW === item.id ? "active" : "",
        "data-view": item.id
      }, [el("span", { class: "ico", html: item.icon }), item.label]);
      btn.addEventListener("click", () => go(item.id));
      nav.appendChild(btn);
    });

    const tip = document.getElementById("sideTip");
    const bulb = ic("lightbulb-fill") + " ";
    const tips = {
      tutor: bulb + "Tutors with published availability receive up to 3× more requests. Keep your slots current.",
      student: bulb + "Send requests to 2–3 tutors to improve your chances of a fast confirmation.",
      admin: bulb + "Suspended tutors are hidden from search instantly. Activity is logged for every change."
    };
    tip.innerHTML = '<p class="small muted" style="margin:0">' + tips[ME.role] + "</p>";
    refreshNavCounts();
  }

  async function refreshNavCounts() {
    if (ME.role === "admin" || ME.role === "tutor") {
      try {
        const res = await API.requests({ status: "pending", page_size: 1 });
        const btn = document.querySelector('#sideNav [data-view="requests"]');
        if (btn && res.total) {
          const existing = btn.querySelector(".count");
          if (existing) existing.textContent = String(res.total);
          else btn.appendChild(el("span", { class: "count", text: String(res.total) }));
        }
      } catch (e) {}
    }
    if (ME.role === "student") {
      try {
        const stats = await API.studentStats();
        const btn = document.querySelector('#sideNav [data-view="requests"]');
        if (btn && stats.pending_requests) {
          btn.appendChild(el("span", { class: "count", text: String(stats.pending_requests) }));
        }
      } catch (e) {}
    }
  }

  /* ------------------------------------------------------- shared blocks -- */
  function card(title, bodyNodes, options) {
    options = options || {};
    const node = el("div", { class: "card" });
    if (title !== null) {
      node.appendChild(el("div", { class: "card-head" }, [
        el("h3", { text: title }),
        options.action || null
      ]));
    }
    const body = el("div", { class: "card-pad" });
    (Array.isArray(bodyNodes) ? bodyNodes : [bodyNodes]).filter(Boolean).forEach((n) => {
      if (typeof n === "string") body.innerHTML += n;
      else body.appendChild(n);
    });
    node.appendChild(body);
    return node;
  }

  function statCard(k, v, icon, tone) {
    return el("div", { class: "stat-card " + (tone || "") }, [
      el("div", { class: "ico", html: icon }),
      el("div", { class: "k", html: String(v) }),
      el("div", { class: "v", text: k })
    ]);
  }

  function sectionTitle(title, subtitle, action) {
    return el("div", { class: "dash-title" }, [
      el("div", {}, [el("h2", { text: title }), subtitle ? el("p", { text: subtitle }) : null]),
      action || null
    ]);
  }

  /* ===================================================================== */
  /* REQUEST ROW (shared by student + tutor + admin views)                 */
  /* ===================================================================== */
  function requestRow(req, options) {
    options = options || {};
    const isTutorView = options.as === "tutor";
    const other = isTutorView ? req.student : req.tutor;
    const row = el("div", { class: "list-item" });

    row.appendChild(UI.image(other.avatar_url, other.name, "thumb", other.name));

    const main = el("div", { class: "main" });
    main.appendChild(el("h4", { html:
      esc(req.subject_name) + " <span class='faint small'>with</span> " + esc(other.name) + " " + statusBadge(req.status) }));
    main.appendChild(el("div", { class: "meta" }, [
      metaSpan("calendar3", relativeDate(req.preferred_date) + " · " + formatDayDate(req.preferred_date)),
      metaSpan("clock-fill", to12h(req.preferred_time) + " · " + req.duration_minutes + " min"),
      metaSpan("cash-coin", money(req.budget)),
      metaSpan("laptop", MODE_LABELS[req.mode] || req.mode),
      isTutorView ? metaSpan("geo-alt-fill", req.tutor_city || "") : null,
      metaSpan("envelope-fill", timeAgo(req.created_at))
    ].filter(Boolean)));

    if (req.location_note) main.appendChild(el("div", { class: "note", html: ic("geo-alt-fill") + " " + esc(req.location_note) }));
    if (req.message) main.appendChild(el("div", { class: "note", html: ic("chat-dots-fill") + " " + esc(req.message) }));
    if (req.tutor_response_note) {
      main.appendChild(el("div", { class: "note " + (req.status === "rejected" ? "bad" : ""),
        html: ic("mortarboard-fill") + " Tutor: " + esc(req.tutor_response_note) }));
    }
    if (req.cancel_reason) main.appendChild(el("div", { class: "note warn", html: ic("slash-circle") + " " + esc(req.cancel_reason) }));

    const side = el("div", { class: "side" });
    side.appendChild(el("div", { class: "right" }, [
      el("div", { style: { fontWeight: "750", fontFamily: "var(--font-display)", fontSize: "1.05rem" }, text: money(req.budget) }),
      el("div", { class: "tiny faint", text: "#" + req.id })
    ]));

    const buttons = el("div", { class: "btn-group", style: { justifyContent: "flex-end" } });

    if (isTutorView) {
      if (req.status === "pending") {
        buttons.appendChild(actionButton("Accept", "btn-success btn-sm", () => decide(req, "accepted", buttons)));
        buttons.appendChild(actionButton("Reject", "btn-soft-danger btn-sm", () => decideWithNote(req, "rejected", buttons)));
      }
      if (req.status === "accepted") {
        buttons.appendChild(actionButton("Mark completed", "btn-primary btn-sm", () => decide(req, "completed", buttons)));
        buttons.appendChild(actionButton("Cancel", "btn-ghost btn-sm", () => cancelRequest(req, buttons)));
      }
    } else if (options.as === "student") {
      if (req.status === "pending") {
        buttons.appendChild(actionButton("Edit", "btn-outline btn-sm", () => editStudentRequest(req)));
        buttons.appendChild(actionButton("Cancel", "btn-soft-danger btn-sm", () => cancelRequest(req, buttons)));
      }
      if (req.status === "accepted") {
        buttons.appendChild(actionButton("Cancel session", "btn-soft-danger btn-sm", () => cancelRequest(req, buttons)));
      }
      if (req.can_review) {
        buttons.appendChild(actionButton("Leave a review", "btn-primary btn-sm", () => openReviewModal(req), "star-fill"));
      } else if (req.has_review) {
        buttons.appendChild(el("span", { class: "badge badge-completed", html: ic("check-circle-fill") + " Reviewed" }));
      }
      if (req.status === "rejected" || req.status === "cancelled") {
        buttons.appendChild(actionButton("Delete", "btn-ghost btn-sm", () => deleteRequestRow(req, buttons)));
      }
      buttons.appendChild(el("a", { class: "btn btn-ghost btn-sm", href: "tutor-profile.html?id=" + req.tutor.id }, "View tutor"));
    } else if (options.as === "admin") {
      if (req.status === "pending" || req.status === "accepted") {
        buttons.appendChild(actionButton("Cancel", "btn-soft-danger btn-sm", () => adminCancel(req)));
      }
      buttons.appendChild(actionButton("Delete", "btn-ghost btn-sm", () => adminDelete(req)));
      buttons.appendChild(el("a", { class: "btn btn-ghost btn-sm", href: "tutor-profile.html?id=" + req.tutor.id }, "Tutor"));
    }

    side.appendChild(buttons);
    row.appendChild(main);
    row.appendChild(side);
    return row;
  }

  function actionButton(label, cls, handler, iconName) {
    const btn = el("button", { class: "btn " + cls, type: "button" }, label);
    if (iconName) btn.innerHTML = ic(iconName) + " " + esc(label);
    btn.addEventListener("click", () => handler(btn));
    return btn;
  }

  async function decide(req, statusValue, buttons) {
    if (statusValue === "completed") {
      const ok = await UI.confirmDialog({
        title: "Mark this session as completed?",
        body: "The student will be able to leave a review, and the session counts towards your completed total.",
        confirmLabel: "Mark completed"
      });
      if (!ok) return;
    }
    try {
      setLoading(buttons, true);
      const res = await API.decideRequest(req.id, { status: statusValue });
      toastSuccess(res.detail);
      await route();
      App.syncNotificationBell();
    } catch (err) {
      setLoading(buttons, false);
      toastError(err.message);
    }
  }

  async function decideWithNote(req, statusValue, buttons) {
    const note = await UI.promptDialog({
      title: "Reject this request",
      label: "Reason (shared with the student)",
      placeholder: "e.g. My schedule is fully booked this term. I can offer a slot next month.",
      confirmLabel: "Reject request",
      required: false
    });
    if (note === null) return;
    try {
      setLoading(buttons, true);
      const res = await API.decideRequest(req.id, { status: statusValue, note: note || null });
      toastSuccess(res.detail);
      await route();
      App.syncNotificationBell();
    } catch (err) {
      setLoading(buttons, false);
      toastError(err.message);
    }
  }

  async function cancelRequest(req, buttons) {
    const reason = await UI.promptDialog({
      title: "Cancel this request?",
      label: "Reason (optional, shared with the other party)",
      placeholder: "e.g. Something came up at work — I'll rebook next week.",
      confirmLabel: "Cancel request",
      required: false
    });
    if (reason === null) return;
    try {
      setLoading(buttons, true);
      const res = await API.cancelRequest(req.id, { reason: reason || undefined });
      toastSuccess(res.detail);
      await route();
      App.syncNotificationBell();
    } catch (err) {
      setLoading(buttons, false);
      toastError(err.message);
    }
  }

  async function deleteRequestRow(req, buttons) {
    const ok = await UI.confirmDialog({
      title: "Delete this request?",
      body: "This permanently removes the record from your dashboard. It cannot be undone.",
      confirmLabel: "Delete", danger: true
    });
    if (!ok) return;
    try {
      setLoading(buttons, true);
      const res = await API.deleteRequest(req.id);
      toastSuccess(res.detail);
      await route();
    } catch (err) {
      setLoading(buttons, false);
      toastError(err.message);
    }
  }

  async function adminCancel(req) {
    const reason = await UI.promptDialog({
      title: "Cancel request #" + req.id,
      label: "Reason (sent to both parties)",
      value: "Cancelled by the platform administrator",
      confirmLabel: "Cancel request"
    });
    if (reason === null) return;
    try {
      const res = await API.adminCancelRequest(req.id, reason);
      toastSuccess(res.detail);
      await route();
    } catch (err) { toastError(err.message); }
  }

  async function adminDelete(req) {
    const ok = await UI.confirmDialog({
      title: "Delete request #" + req.id + "?",
      body: "This removes the booking and any attached review from the database permanently.",
      confirmLabel: "Delete permanently", danger: true
    });
    if (!ok) return;
    try {
      const res = await API.adminDeleteRequest(req.id);
      toastSuccess(res.detail);
      await route();
    } catch (err) { toastError(err.message); }
  }

  /* ------------------------------------------------- student edit request */
  function editStudentRequest(req) {
    const body = el("div", {});
    body.innerHTML =
      '<div id="editErr"></div>' +
      '<div class="field-row">' +
        '<label class="field"><span class="label">Preferred date</span>' +
          '<input class="input" type="date" id="ed-date" value="' + esc(req.preferred_date) + '" /></label>' +
        '<label class="field"><span class="label">Preferred time</span>' +
          '<input class="input" type="time" id="ed-time" step="900" value="' + esc(req.preferred_time) + '" /></label>' +
      '</div>' +
      '<div class="field-row">' +
        '<label class="field"><span class="label">Duration</span>' +
          '<select class="select" id="ed-duration"></select></label>' +
        '<label class="field"><span class="label">Mode</span>' +
          '<select class="select" id="ed-mode">' +
            '<option value="hybrid">Online &amp; in person</option><option value="online">Online</option>' +
            '<option value="in_person">In person</option></select></label>' +
      '</div>' +
      '<label class="field"><span class="label">Budget (₦)</span>' +
        '<input class="input" type="number" id="ed-budget" min="0" step="100" value="' + esc(req.budget) + '" /></label>' +
      '<label class="field"><span class="label">Message</span>' +
        '<textarea class="textarea" id="ed-message" rows="3">' + esc(req.message || "") + "</textarea></label>" +
      '<label class="field"><span class="label">Location / meeting note</span>' +
        '<input class="input" id="ed-location" value="' + esc(req.location_note || "") + '" /></label>' +
      '<label class="check"><input type="checkbox" id="ed-ignore" />' +
        "<span>Allow a time outside the tutor's availability</span></label>";

    UI.modal({
      title: "Edit request #" + req.id,
      subtitle: req.subject_name + " with " + req.tutor.name,
      body,
      buttons: [
        { label: "Close", class: "btn-outline", onClick: (b, bb, close) => close() },
        {
          label: "Save changes", class: "btn-primary",
          onClick: async (btn, bb, close) => {
            const payload = {
              preferred_date: document.getElementById("ed-date").value,
              preferred_time: document.getElementById("ed-time").value,
              duration_minutes: Number(document.getElementById("ed-duration").value),
              mode: document.getElementById("ed-mode").value,
              budget: Number(document.getElementById("ed-budget").value),
              message: document.getElementById("ed-message").value.trim() || null,
              location_note: document.getElementById("ed-location").value.trim() || null,
              ignore_availability: document.getElementById("ed-ignore").checked
            };
            setLoading(btn, true, "Saving…");
            try {
              const res = await API.updateRequest(req.id, payload);
              close();
              toastSuccess(res.detail);
              await route();
            } catch (err) {
              setLoading(btn, false);
              document.getElementById("editErr").innerHTML =
                '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>' + esc(err.message) + "</div></div>";
            }
          }
        }
      ]
    });
    const dur = document.getElementById("ed-duration");
    [30, 45, 60, 90, 120].forEach((d) => dur.appendChild(el("option", { value: String(d) }, d + " minutes")));
    dur.value = String(req.duration_minutes);
    document.getElementById("ed-mode").value = req.mode;
  }

  /* ------------------------------------------------------------- reviews -- */
  function openReviewModal(req, existing) {
    let rating = existing ? existing.rating : 0;
    const body = el("div", {});
    body.innerHTML =
      '<div id="revErr"></div>' +
      '<div class="field"><span class="label">Your rating <span class="req">*</span></span>' +
        '<div class="star-input" id="rev-stars"></div></div>' +
      '<label class="field"><span class="label">Headline</span>' +
        '<input class="input" id="rev-title" maxlength="160" placeholder="e.g. Patient, structured and effective" /></label>' +
      '<label class="field"><span class="label">Your review</span>' +
        '<textarea class="textarea" id="rev-comment" rows="4" maxlength="2000" ' +
        'placeholder="What went well? What could improve? Other families read this."></textarea></label>';

    const host = body.querySelector("#rev-stars");
    const paint = () => {
      host.innerHTML = "";
      for (let i = 1; i <= 5; i++) {
        const b = el("button", { type: "button", class: i <= rating ? "on" : "", "aria-label": i + " star",
          html: i <= rating ? ic("star-fill") : ic("star") });
        b.addEventListener("click", () => { rating = i; paint(); });
        b.addEventListener("mouseenter", () => {
          host.querySelectorAll("button").forEach((x, idx) => x.classList.toggle("on", idx < i));
        });
        host.appendChild(b);
      }
    };
    paint();
    host.addEventListener("mouseleave", paint);

    UI.modal({
      title: existing ? "Edit your review" : "Review your session",
      subtitle: req.subject_name + " with " + req.tutor.name + " · " + formatDayDate(req.preferred_date),
      body,
      buttons: [
        { label: "Cancel", class: "btn-outline", onClick: (b, bb, close) => close() },
        {
          label: existing ? "Update review" : "Publish review", class: "btn-primary",
          onClick: async (btn, bb, close) => {
            if (!rating) {
              document.getElementById("revErr").innerHTML =
                '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>Please choose a star rating first.</div></div>';
              return;
            }
            const payload = {
              rating,
              title: document.getElementById("rev-title").value.trim() || null,
              comment: document.getElementById("rev-comment").value.trim() || null
            };
            setLoading(btn, true, "Publishing…");
            try {
              const res = existing
                ? await API.updateReview(existing.id, payload)
                : await API.createReview(Object.assign({ booking_request_id: req.id }, payload));
              close();
              toastSuccess(res.detail);
              await route();
              App.syncNotificationBell();
            } catch (err) {
              setLoading(btn, false);
              document.getElementById("revErr").innerHTML =
                '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>' + esc(err.message) + "</div></div>";
            }
          }
        }
      ]
    });
  }

  /* ===================================================================== */
  /* ROUTES                                                                */
  /* ===================================================================== */
  const ROUTES = {};

  /* ------------------------------------------------------------ TUTOR ---- */
  ROUTES["tutor:overview"] = async (host) => {
    host.innerHTML = "";
    const [stats, profile, requestsRes] = await Promise.all([
      API.myTutorStats(), API.myTutorProfile(), API.requests({ page_size: 5 })
    ]);
    TUTOR_PROFILE = profile;

    if (stats.profile_completion < 100) {
      host.appendChild(el("div", { class: "card" }, [el("div", { class: "card-pad" }, [
        el("div", { class: "row-between" }, [
          el("div", {}, [
            el("h3", { style: { margin: 0 }, text: "Profile strength: " + stats.profile_completion + "%" }),
            el("p", { class: "muted small", style: { margin: "4px 0 0" },
              text: stats.profile_completion >= 80
                ? "Almost there — add a cover photo or languages to reach 100%."
                : "Complete your profile to rank higher in search results." })
          ]),
          (() => { const b = el("button", { class: "btn btn-primary btn-sm", type: "button" }, "Improve profile");
            b.addEventListener("click", () => go("profile")); return b; })()
        ]),
        el("div", { class: "progress", style: { marginTop: "14px" } }, [el("i", { style: { width: stats.profile_completion + "%" } })])
      ])]));
    }

    host.appendChild(el("div", { class: "stats-strip" }, [
      statCard("Pending requests", stats.pending_requests, ic("envelope-fill"), "amber"),
      statCard("Upcoming sessions", stats.upcoming_sessions, ic("calendar3"), "accent"),
      statCard("Completed", stats.completed_sessions, ic("check-circle-fill"), "green"),
      statCard("Rating", stats.review_count ? stats.rating.toFixed(1) + " " + ic("star-fill") : "–", ic("star-fill"), "")
    ]));

    host.appendChild(el("div", { class: "stats-strip" }, [
      statCard("Total requests", stats.total_requests, ic("bar-chart-fill")),
      statCard("Accepted", stats.accepted_requests, ic("check2-circle"), "green"),
      statCard("Weekly slots", stats.weekly_slots, ic("alarm-fill"), "accent"),
      statCard("Booked value", money(stats.total_earnings), ic("cash-coin"), "amber")
    ]));

    const list = el("div", { class: "list" });
    const pending = (requestsRes.items || []).filter((r) => r.status === "pending");
    if (pending.length) {
      pending.forEach((r) => list.appendChild(requestRow(r, { as: "tutor" })));
    } else {
      list.innerHTML = UI.emptyState({
        icon: ic("check-all"), title: "No pending requests",
        message: "You're all caught up. New requests from students will appear here instantly.",
        actionLabel: "View all requests", actionHref: "#"
      });
      const a = list.querySelector("a");
      if (a) a.addEventListener("click", (e) => { e.preventDefault(); go("requests"); });
    }
    host.appendChild(card("Requests needing your response", [list], {
      action: (() => { const b = el("button", { class: "btn btn-sm btn-outline", type: "button" }, "See all");
        b.addEventListener("click", () => go("requests")); return b; })()
    }));

    const upcoming = await API.upcoming(5);
    const upcomingList = el("div", { class: "list" });
    if (upcoming.length) {
      upcoming.forEach((r) => {
        upcomingList.appendChild(el("div", { class: "list-item" }, [
          UI.image(r.student.avatar_url, r.student.name, "thumb", r.student.name),
          el("div", { class: "main" }, [
            el("h4", { text: r.subject_name + " · " + r.student.name }),
            el("div", { class: "meta" }, [
              metaSpan("calendar3", formatDayDate(r.preferred_date)),
              metaSpan("clock-fill", to12h(r.preferred_time)),
              metaSpan("cash-coin", money(r.budget)),
              metaSpan("laptop", MODE_LABELS[r.mode] || r.mode)
            ])
          ]),
          el("div", { class: "side" }, [el("span", { class: "badge badge-accepted" }, relativeDate(r.preferred_date))])
        ]));
      });
    } else {
      upcomingList.innerHTML = UI.emptyState({ icon: ic("calendar3"), title: "No upcoming sessions",
        message: "Accepted requests will appear here with the date, time and student details." });
    }
    host.appendChild(card("Upcoming sessions", [upcomingList]));
  };

  ROUTES["tutor:requests"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("Requests & bookings", "Every request students have sent you, grouped by status."));

    const tabs = el("div", { class: "tabs" });
    const statuses = [
      { key: "", label: "All" }, { key: "pending", label: "Pending" }, { key: "accepted", label: "Accepted" },
      { key: "completed", label: "Completed" }, { key: "rejected", label: "Rejected" }, { key: "cancelled", label: "Cancelled" }
    ];
    const listHost = el("div", { class: "list" });
    host.appendChild(tabs);
    host.appendChild(el("div", { class: "card" }, [el("div", { class: "card-pad" }, [listHost])]));

    let activeStatus = UI.readQueryParams().status || "";
    async function load() {
      listHost.innerHTML = UI.skeletonRows(4);
      const res = await API.requests({ status: activeStatus || undefined, page_size: 50 });
      tabs.innerHTML = "";
      statuses.forEach((s) => {
        const count = s.key ? (res.counts[s.key] || 0) : res.total;
        const btn = el("button", { class: "tab" + (activeStatus === s.key ? " active" : ""), type: "button" },
          [document.createTextNode(s.label), el("span", { class: "pill", text: String(count) })]);
        btn.addEventListener("click", () => {
          activeStatus = s.key;
          UI.writeQueryParams(Object.assign(UI.readQueryParams(), { status: s.key || undefined }), true);
          load();
        });
        tabs.appendChild(btn);
      });

      listHost.innerHTML = "";
      if (!res.items.length) {
        listHost.innerHTML = UI.emptyState({
          icon: ic("inbox"), title: activeStatus ? "No " + activeStatus + " requests" : "No requests yet",
          message: activeStatus
            ? "Nothing in this status right now."
            : "Share your profile link with students, and keep your availability up to date to get discovered in search."
        });
        return;
      }
      const list = el("div", { class: "list" });
      res.items.forEach((r) => list.appendChild(requestRow(r, { as: "tutor" })));
      listHost.appendChild(list);
    }
    await load();
  };

  ROUTES["tutor:availability"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("Weekly availability",
      "Set the days and times you can teach. Students see these slots in real time when booking.",
      (() => { const b = el("button", { class: "btn btn-primary btn-sm", type: "button" }, "＋ Add slot");
        b.addEventListener("click", () => slotModal()); return b; })()));

    const data = await API.myAvailability();
    const grouped = {};
    DAYS.forEach((d) => { grouped[d] = []; });
    (data.items || []).forEach((s) => { (grouped[s.day_of_week] = grouped[s.day_of_week] || []).push(s); });

    const grid = el("div", { class: "avail-grid" });
    DAYS.forEach((day) => {
      const slots = grouped[day] || [];
      const row = el("div", { class: "avail-day" + (slots.length ? "" : " empty") }, [
        el("span", { class: "day", text: day }),
        el("div", { class: "slots" })
      ]);
      const slotHost = row.querySelector(".slots");
      if (!slots.length) slotHost.appendChild(el("span", { class: "small faint", text: "No slots — add one" }));
      slots.forEach((slot) => {
        const pill = el("span", { class: "slot-pill" + (slot.is_active ? "" : " off") }, [
          document.createTextNode(to12h(slot.start_time) + " – " + to12h(slot.end_time)),
          el("span", { class: "tiny", text: " · " + (MODE_LABELS[slot.mode] || "") }),
          el("span", { class: "actions" }, [
            (() => { const b = el("button", { title: "Edit", type: "button", html: ic("pencil-fill") });
              b.addEventListener("click", () => slotModal(slot)); return b; })(),
            (() => { const b = el("button", { title: slot.is_active ? "Pause" : "Resume", type: "button",
                html: slot.is_active ? ic("pause-fill") : ic("play-fill") });
              b.addEventListener("click", async () => {
                try { const res = await API.toggleAvailability(slot.id); toastSuccess(res.detail); route(); }
                catch (err) { toastError(err.message); }
              }); return b; })(),
            (() => { const b = el("button", { title: "Delete", type: "button", html: ic("trash-fill") });
              b.addEventListener("click", async () => {
                const ok = await UI.confirmDialog({
                  title: "Delete this slot?", body: day + " " + to12h(slot.start_time) + " – " + to12h(slot.end_time) +
                  " will be removed from your public availability.", confirmLabel: "Delete", danger: true
                });
                if (!ok) return;
                try { const res = await API.deleteAvailability(slot.id); toastSuccess(res.detail); route(); }
                catch (err) { toastError(err.message); }
              }); return b; })()
          ])
        ]);
        slotHost.appendChild(pill);
      });
      grid.appendChild(row);
    });

    host.appendChild(card(null, [grid]));

    /* exceptions */
    const exHost = el("div", {});
    const exceptions = data.exceptions || [];
    if (exceptions.length) {
      const list = el("div", { class: "list" });
      exceptions.forEach((exc) => {
        list.appendChild(el("div", { class: "list-item" }, [
          el("div", { class: "main" }, [
            el("h4", { text: formatDayDate(exc.date) + " · " + (exc.is_blocked ? "Blocked" : "Open") }),
            exc.reason ? el("p", { class: "small muted", style: { margin: 0 }, text: exc.reason }) : null
          ].filter(Boolean)),
          el("div", { class: "side" }, [
            (() => { const b = el("button", { class: "btn btn-ghost btn-sm", type: "button" }, "Remove");
              b.addEventListener("click", async () => {
                try { const res = await API.deleteException(exc.id); toastSuccess(res.detail); route(); }
                catch (err) { toastError(err.message); }
              }); return b; })()
          ])
        ]));
      });
      exHost.appendChild(list);
    } else {
      exHost.innerHTML = UI.emptyState({ icon: ic("calendar3"), title: "No date overrides",
        message: "Block a specific date (holiday, travel) or open an extra day without changing your weekly pattern." });
    }
    host.appendChild(card("Specific date overrides", [exHost], {
      action: (() => { const b = el("button", { class: "btn btn-sm btn-outline", type: "button" }, "＋ Add override");
        b.addEventListener("click", exceptionModal); return b; })()
    }));
  };

  function slotModal(slot) {
    const body = el("div", {});
    body.innerHTML =
      '<div id="slotErr"></div>' +
      '<div class="field"><span class="label">Day of week</span><select class="select" id="sl-day"></select></div>' +
      '<div class="field-row">' +
        '<label class="field"><span class="label">Start time</span><input class="input" type="time" id="sl-start" step="900" value="' +
          (slot ? esc(slot.start_time) : "16:00") + '" /></label>' +
        '<label class="field"><span class="label">End time</span><input class="input" type="time" id="sl-end" step="900" value="' +
          (slot ? esc(slot.end_time) : "19:00") + '" /></label>' +
      '</div>' +
      '<label class="field"><span class="label">Teaching mode for this slot</span>' +
        '<select class="select" id="sl-mode">' +
          '<option value="hybrid">Online &amp; in person</option><option value="online">Online</option>' +
          '<option value="in_person">In person</option></select></label>' +
      '<label class="check"><input type="checkbox" id="sl-active" checked /><span>Active (visible to students)</span></label>' +
      '<p class="hint" style="margin-top:12px">Slots shorter than 30 minutes or overlapping an existing slot will be rejected by the API.</p>';

    const daySelect = body.querySelector("#sl-day");
    DAYS.forEach((d) => daySelect.appendChild(el("option", { value: d }, d)));
    if (slot) { daySelect.value = slot.day_of_week; body.querySelector("#sl-mode").value = slot.mode; body.querySelector("#sl-active").checked = slot.is_active; }

    UI.modal({
      title: slot ? "Edit availability slot" : "Add availability slot",
      subtitle: slot ? "Changes apply to your public profile immediately." : "Students will see this slot when booking.",
      body,
      buttons: [
        { label: "Cancel", class: "btn-outline", onClick: (b, bb, close) => close() },
        {
          label: slot ? "Save changes" : "Add slot", class: "btn-primary",
          onClick: async (btn, bb, close) => {
            const payload = {
              day_of_week: daySelect.value,
              start_time: body.querySelector("#sl-start").value,
              end_time: body.querySelector("#sl-end").value,
              mode: body.querySelector("#sl-mode").value,
              is_active: body.querySelector("#sl-active").checked
            };
            if (!payload.start_time || !payload.end_time) {
              body.querySelector("#slotErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>Both start and end times are required.</div></div>';
              return;
            }
            setLoading(btn, true, "Saving…");
            try {
              const res = slot ? await API.updateAvailability(slot.id, payload) : await API.addAvailability(payload);
              close();
              toastSuccess(res.detail);
              route();
            } catch (err) {
              setLoading(btn, false);
              body.querySelector("#slotErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>' + esc(err.message) + "</div></div>";
            }
          }
        }
      ]
    });
  }

  function exceptionModal() {
    const body = el("div", {});
    const today = new Date().toISOString().slice(0, 10);
    body.innerHTML =
      '<div id="exErr"></div>' +
      '<label class="field"><span class="label">Date</span>' +
        '<input class="input" type="date" id="ex-date" min="' + today + '" /></label>' +
      '<label class="field"><span class="label">Setting</span>' +
        '<select class="select" id="ex-blocked">' +
          '<option value="true">Unavailable (block this date)</option>' +
          '<option value="false">Extra open (allow bookings)</option></select></label>' +
      '<label class="field"><span class="label">Reason <span class="tiny faint">(optional, private)</span></span>' +
        '<input class="input" id="ex-reason" maxlength="255" placeholder="e.g. Public holiday" /></label>';

    UI.modal({
      title: "Add a date override",
      subtitle: "Overrides apply to one specific date only.",
      body,
      buttons: [
        { label: "Cancel", class: "btn-outline", onClick: (b, bb, close) => close() },
        {
          label: "Save override", class: "btn-primary",
          onClick: async (btn, bb, close) => {
            const dateValue = body.querySelector("#ex-date").value;
            if (!dateValue) {
              body.querySelector("#exErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>Please choose a date.</div></div>';
              return;
            }
            setLoading(btn, true, "Saving…");
            try {
              const res = await API.addException({
                date: dateValue,
                is_blocked: body.querySelector("#ex-blocked").value === "true",
                reason: body.querySelector("#ex-reason").value.trim() || null
              });
              close(); toastSuccess(res.detail); route();
            } catch (err) {
              setLoading(btn, false);
              body.querySelector("#exErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>' + esc(err.message) + "</div></div>";
            }
          }
        }
      ]
    });
  }

  ROUTES["tutor:profile"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("My tutor profile", "Everything students see on your public page."));
    let profile;
    try { profile = await API.myTutorProfile(); }
    catch (err) {
      if (err.status === 404) {
        host.innerHTML = UI.emptyState({
          icon: ic("mortarboard-fill"), title: "Create your tutor profile",
          message: "You do not have a profile yet. Create one so students can find, filter and request you."
        });
        const b = el("button", { class: "btn btn-primary", type: "button", style: { marginTop: "14px" } }, "Create profile");
        b.addEventListener("click", () => tutorProfileForm(host, null));
        host.querySelector(".empty").appendChild(b);
        return;
      }
      throw err;
    }
    TUTOR_PROFILE = profile;
    tutorProfileForm(host, profile);
  };

  async function tutorProfileForm(host, profile) {
    const subjectsRes = await API.subjects({});
    const allSubjects = subjectsRes.items || [];
    const selected = new Set((profile && profile.subjects ? profile.subjects : []).map((s) => s.id));

    host.innerHTML = "";
    host.appendChild(sectionTitle(
      profile ? "Edit tutor profile" : "Create your tutor profile",
      profile ? "Changes are saved to the database and appear instantly in search." : "This is what students see on your public page."
    ));

    const body = el("div", {});
    body.innerHTML =
      '<div id="tpErr"></div>' +
      '<div class="field-row">' +
        '<label class="field"><span class="label">Profile photo URL</span>' +
          '<input class="input" id="tp-avatar" maxlength="600" placeholder="https://…" value="' + esc((ME && ME.avatar_url) || "") + '" />' +
          '<div class="hint">Square images look best.</div></label>' +
        '<label class="field"><span class="label">Cover photo URL</span>' +
          '<input class="input" id="tp-cover" maxlength="600" placeholder="https://…" value="' + esc((profile && profile.cover_image_url) || "") + '" /></label>' +
      '</div>' +
      '<label class="field"><span class="label">Professional headline <span class="req">*</span></span>' +
        '<select class="select" id="tp-headline"></select></label>' +
      '<label class="field"><span class="label">Bio <span class="req">*</span></span>' +
        '<textarea class="textarea" id="tp-bio" rows="5" maxlength="4000">' + esc((profile && profile.bio) || "") + "</textarea>" +
        '<div class="hint">Minimum 40 characters. Describe your teaching style and results.</div></label>' +
      '<div class="field-row-3">' +
        '<label class="field"><span class="label">Years experience</span><input class="input" type="number" id="tp-years" min="0" max="70" value="' + esc(profile ? profile.years_experience : "") + '" /></label>' +
        '<label class="field"><span class="label">Rate per session (₦)</span><input class="input" type="number" id="tp-rate" min="0" step="100" value="' + esc(profile ? profile.hourly_rate : "") + '" /></label>' +
        '<label class="field"><span class="label">Session length (min)</span><input class="input" type="number" id="tp-duration" min="15" max="480" step="15" value="' + esc(profile ? profile.session_duration_minutes : 60) + '" /></label>' +
      '</div>' +
      '<div class="field-row-3">' +
        '<label class="field"><span class="label">City <span class="req">*</span></span><input class="input" id="tp-city" maxlength="120" value="' + esc((profile && profile.city) || "") + '" /></label>' +
        '<label class="field"><span class="label">State <span class="req">*</span></span><select class="select" id="tp-state"></select></label>' +
        '<label class="field"><span class="label">Teaching mode</span><select class="select" id="tp-mode">' +
          '<option value="hybrid">Online &amp; in person</option><option value="online">Online</option><option value="in_person">In person</option></select></label>' +
      '</div>' +
      '<label class="field"><span class="label">Qualifications</span><select class="select" id="tp-quals"></select></label>' +
      '<label class="field"><span class="label">Languages</span><input class="input" id="tp-languages" maxlength="255" value="' + esc((profile && profile.languages) || "") + '" placeholder="English, Igbo" /></label>' +
      '<div class="field"><span class="label">Subjects you teach <span class="req">*</span></span>' +
        '<select class="select" id="tp-subjectSelect"><option value="">Select a subject to add…</option></select>' +
        '<div id="tp-subjects" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:10px"></div></div>' +
      '<div class="field-row">' +
        '<label class="check"><input type="checkbox" id="tp-online" ' + (!profile || profile.accepts_online ? "checked" : "") + " /><span>Accepts online sessions</span></label>" +
        '<label class="check"><input type="checkbox" id="tp-inperson" ' + (!profile || profile.accepts_in_person ? "checked" : "") + " /><span>Accepts in-person sessions</span></label>" +
      '</div>' +
      '<label class="check"><input type="checkbox" id="tp-visible" ' + (!profile || profile.is_visible ? "checked" : "") + " /><span>Profile visible in search results</span></label>";

    const picker = body.querySelector("#tp-subjects");
    UI.fillSelect(body.querySelector("#tp-headline"), UI.TUTOR_HEADLINES, "Select your professional headline…", (profile && profile.headline) || "");
    UI.fillSelect(body.querySelector("#tp-state"), UI.NG_STATES, "Select your state…", (profile && profile.state) || "");
    UI.fillSelect(body.querySelector("#tp-quals"), UI.QUALIFICATION_OPTIONS, "Select your qualification (optional)…", (profile && profile.qualifications) || "");
    UI.subjectDropdown(body.querySelector("#tp-subjectSelect"), picker, allSubjects, Array.from(selected), null);
    if (profile) body.querySelector("#tp-mode").value = profile.teaching_mode;

    const actions = el("div", { class: "btn-group", style: { marginTop: "18px" } });
    const save = el("button", { class: "btn btn-primary", type: "button" }, profile ? "Save changes" : "Create profile");
    save.addEventListener("click", async () => {
      const subjectIds = Array.from(picker.querySelectorAll("input:checked")).map((i) => Number(i.value));
      const payload = {
        headline: body.querySelector("#tp-headline").value.trim(),
        bio: body.querySelector("#tp-bio").value.trim(),
        years_experience: Number(body.querySelector("#tp-years").value || 0),
        hourly_rate: Number(body.querySelector("#tp-rate").value || 0),
        session_duration_minutes: Number(body.querySelector("#tp-duration").value || 60),
        city: body.querySelector("#tp-city").value.trim(),
        state: body.querySelector("#tp-state").value.trim(),
        teaching_mode: body.querySelector("#tp-mode").value,
        qualifications: body.querySelector("#tp-quals").value.trim() || null,
        languages: body.querySelector("#tp-languages").value.trim() || null,
        cover_image_url: body.querySelector("#tp-cover").value.trim() || null,
        accepts_online: body.querySelector("#tp-online").checked,
        accepts_in_person: body.querySelector("#tp-inperson").checked,
        is_visible: body.querySelector("#tp-visible").checked,
        subject_ids: subjectIds
      };
      setLoading(save, true, "Saving…");
      try {
        const avatar = body.querySelector("#tp-avatar").value.trim() || null;
        if (avatar !== (ME.avatar_url || null)) await API.updateMe({ avatar_url: avatar });
        const res = profile ? await API.updateMyTutorProfile(payload) : await API.createTutorProfile(payload);
        ME = await API.refreshMe();
        toastSuccess(profile ? "Profile updated — search results now show your new details." : "Tutor profile created!");
        renderHeader(); renderSidebar();
        go(profile ? "profile" : "availability");
      } catch (err) {
        setLoading(save, false);
        body.querySelector("#tpErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div><strong>' +
          esc(err.message) + "</strong>" + (err.errors && err.errors.length
            ? "<ul>" + err.errors.map((e) => "<li>" + esc(e.field) + ": " + esc(e.message) + "</li>").join("") + "</ul>" : "") + "</div></div>";
        body.querySelector("#tpErr").scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
    actions.appendChild(save);

    if (profile) {
      const view = el("a", { class: "btn btn-outline", href: "tutor-profile.html?id=" + profile.id, target: "_blank",
        html: ic("eye-fill") + " View public page" });
      actions.appendChild(view);
      const del = el("button", { class: "btn btn-soft-danger", type: "button" }, "Delete profile");
      del.addEventListener("click", async () => {
        const ok = await UI.confirmDialog({
          title: "Delete your tutor profile?",
          body: "Your subjects, availability, requests and reviews will be removed. This cannot be undone.",
          confirmLabel: "Delete profile", danger: true
        });
        if (!ok) return;
        try { const res = await API.deleteMyTutorProfile(); toastSuccess(res.detail); go("overview"); }
        catch (err) { toastError(err.message); }
      });
      actions.appendChild(del);
    }

    host.appendChild(card(null, [body, actions]));
  }

  ROUTES["tutor:reviews"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("Reviews & ratings", "Only students with a completed session can review you."));
    const profile = await API.myTutorProfile();
    const data = await API.tutorReviews(profile.id, 50);

    host.appendChild(el("div", { class: "stats-strip" }, [
      statCard("Average rating", data.review_count ? Number(data.rating).toFixed(2) + " " + ic("star-fill") : "–", ic("star-fill"), "amber"),
      statCard("Total reviews", data.review_count, ic("pencil-square")),
      statCard("5-star reviews", (data.breakdown.find((b) => b.star === 5) || {}).count || 0, ic("stars"), "green"),
      statCard("Completed sessions", profile.completed_sessions, ic("check-circle-fill"), "accent")
    ]));

    const breakdown = el("div", {});
    breakdown.innerHTML = '<div class="rating-summary">' +
      '<div class="rating-big"><div class="n">' + (data.review_count ? Number(data.rating).toFixed(1) : "–") + "</div>" +
      stars(data.rating, null, false) + '<div class="small faint">' + plural(data.review_count, "review") + "</div></div>" +
      '<div class="breakdown">' + data.breakdown.map((row) =>
        '<div class="row-b"><span>' + row.star + " " + ic("star-fill") + "</span><span class='track'><i style='width:" + row.percentage + "%'></i></span>" +
        '<span class="right">' + row.count + "</span></div>").join("") + "</div></div>";
    host.appendChild(card("Rating breakdown", [breakdown]));

    const list = el("div", {});
    if (!(data.items || []).length) {
      list.innerHTML = UI.emptyState({ icon: ic("star-fill"), title: "No reviews yet",
        message: "Complete a session and ask your student to leave honest feedback — reviews lift you in search results." });
    } else {
      data.items.forEach((review) => {
        list.appendChild(el("div", { class: "review-item" }, [
          el("div", { class: "review-head" }, [
            UI.image(review.student_avatar_url, review.student_name, "", review.student_name),
            el("div", { class: "grow" }, [
              el("strong", { text: review.student_name }),
              el("div", { class: "when", text: formatDate(review.created_at) + (review.subject_name ? " · " + review.subject_name : "") })
            ]),
            el("div", { html: stars(review.rating, null, false) })
          ]),
          review.title ? el("h4", { text: review.title }) : null,
          review.comment ? el("p", { text: review.comment }) : null
        ].filter(Boolean)));
      });
    }
    host.appendChild(card("What students say", [list]));
  };

  /* ---------------------------------------------------------- STUDENT ---- */
  ROUTES["student:overview"] = async (host) => {
    host.innerHTML = "";
    const [stats, requestsRes, upcoming] = await Promise.all([
      API.studentStats(), API.requests({ page_size: 6 }), API.upcoming(5)
    ]);

    host.appendChild(el("div", { class: "stats-strip" }, [
      statCard("Pending requests", stats.pending_requests, ic("envelope-fill"), "amber"),
      statCard("Upcoming sessions", stats.upcoming_sessions, ic("calendar3"), "accent"),
      statCard("Completed", stats.completed_sessions, ic("check-circle-fill"), "green"),
      statCard("Saved tutors", stats.favorites, ic("heart-fill"), "rose")
    ]));

    host.appendChild(el("div", { class: "stats-strip" }, [
      statCard("Tutors contacted", stats.tutors_contacted, ic("people-fill")),
      statCard("Reviews written", stats.reviews_written, ic("star-fill"), "amber"),
      statCard("Accepted", stats.accepted_requests, ic("hand-thumbs-up-fill"), "green"),
      statCard("Total spent", money(stats.total_spent), ic("cash-coin"), "accent")
    ]));

    const list = el("div", { class: "list" });
    if (upcoming.length) {
      upcoming.forEach((r) => list.appendChild(requestRow(r, { as: "student" })));
    } else {
      list.innerHTML = UI.emptyState({
        icon: ic("search"), title: "No upcoming sessions",
        message: "Search tutors by subject, location and budget, then send your first booking request.",
        actionLabel: "Find a tutor", actionHref: "tutors.html"
      });
    }
    host.appendChild(card("Upcoming sessions", [list], {
      action: (() => { const b = el("button", { class: "btn btn-sm btn-outline", type: "button" }, "All requests");
        b.addEventListener("click", () => go("requests")); return b; })()
    }));

    const recent = el("div", { class: "list" });
    const items = (requestsRes.items || []).slice(0, 5);
    if (items.length) items.forEach((r) => recent.appendChild(requestRow(r, { as: "student" })));
    else recent.innerHTML = UI.emptyState({ icon: ic("inbox"), title: "No requests yet",
      message: "Your requests and their live statuses will appear here." });
    host.appendChild(card("Recent activity", [recent]));
  };

  ROUTES["student:requests"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("My requests & bookings", "Live statuses — as soon as a tutor responds, this list updates.",
      el("a", { class: "btn btn-primary btn-sm", href: "tutors.html", html: ic("search") + " Find more tutors" })));

    const tabs = el("div", { class: "tabs" });
    const statuses = [
      { key: "", label: "All" }, { key: "pending", label: "Pending" }, { key: "accepted", label: "Accepted" },
      { key: "completed", label: "Completed" }, { key: "rejected", label: "Rejected" }, { key: "cancelled", label: "Cancelled" }
    ];
    const listHost = el("div", {});
    host.appendChild(tabs);
    host.appendChild(el("div", { class: "card" }, [el("div", { class: "card-pad" }, [listHost])]));

    let active = UI.readQueryParams().status || "";
    async function load() {
      listHost.innerHTML = UI.skeletonRows(4);
      const res = await API.requests({ status: active || undefined, page_size: 50 });
      tabs.innerHTML = "";
      statuses.forEach((s) => {
        const count = s.key ? (res.counts[s.key] || 0) : res.total;
        const btn = el("button", { class: "tab" + (active === s.key ? " active" : ""), type: "button" },
          [document.createTextNode(s.label), el("span", { class: "pill", text: String(count) })]);
        btn.addEventListener("click", () => { active = s.key; load(); });
        tabs.appendChild(btn);
      });

      listHost.innerHTML = "";
      if (!res.items.length) {
        listHost.innerHTML = UI.emptyState({
          icon: ic("envelope-open"),
          title: active ? "No " + active + " requests" : "You haven't sent any requests yet",
          message: active ? "Nothing in this status right now."
            : "Find a tutor whose subject, location and budget fit, then send a request for one of their open slots.",
          actionLabel: "Browse tutors", actionHref: "tutors.html"
        });
        return;
      }
      const list = el("div", { class: "list" });
      res.items.forEach((r) => list.appendChild(requestRow(r, { as: "student" })));
      listHost.appendChild(list);
    }
    await load();
  };

  ROUTES["student:saved"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("Saved tutors", "Tutors you shortlisted. Tap the heart on any card to add or remove."));
    const items = await API.favorites();
    if (!items.length) {
      host.innerHTML += UI.emptyState({
        icon: ic("heart"), title: "No saved tutors yet",
        message: "Browse tutors and tap the heart icon to build your shortlist.",
        actionLabel: "Find tutors", actionHref: "tutors.html"
      });
      return;
    }
    const gridHost = el("div", {});
    App.renderTutorGrid(gridHost, items, {
      onFavoriteChange: () => setTimeout(() => route(), 600)
    });
    host.appendChild(gridHost);
  };

  ROUTES["student:profile"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("My profile", "Tutors see your name and city when you send a request."));

    let profile = {};
    try { profile = await API.get("/students/me"); }
    catch (err) { profile = {}; }

    const body = el("div", {});
    body.innerHTML =
      '<div id="spErr"></div>' +
      '<div class="field-row">' +
        '<label class="field"><span class="label">Full name</span><input class="input" id="sp-name" value="' + esc(ME.full_name) + '" /></label>' +
        '<label class="field"><span class="label">Phone</span><input class="input" id="sp-phone" value="' + esc(ME.phone || "") + '" /></label>' +
      '</div>' +
      '<label class="field"><span class="label">Profile photo URL</span><input class="input" id="sp-avatar" value="' + esc(ME.avatar_url || "") + '" placeholder="https://…" /></label>' +
      '<div class="field-row">' +
        '<label class="field"><span class="label">City</span><input class="input" id="sp-city" value="' + esc(profile.city || "") + '" /></label>' +
        '<label class="field"><span class="label">State</span><input class="input" id="sp-state" value="' + esc(profile.state || "") + '" /></label>' +
      '</div>' +
      '<div class="field-row">' +
        '<label class="field"><span class="label">Education level</span><input class="input" id="sp-level" value="' + esc(profile.education_level || "") + '" placeholder="e.g. SS2" /></label>' +
        '<label class="field"><span class="label">Guardian name</span><input class="input" id="sp-guardian" value="' + esc(profile.guardian_name || "") + '" /></label>' +
      '</div>' +
      '<div class="field-row">' +
        '<label class="field"><span class="label">Preferred mode</span><select class="select" id="sp-mode">' +
          '<option value="">No preference</option><option value="hybrid">Online &amp; in person</option>' +
          '<option value="online">Online</option><option value="in_person">In person</option></select></label>' +
        '<label class="field"><span class="label">Max budget per session (₦)</span><input class="input" type="number" id="sp-budget" min="0" step="500" value="' + esc(profile.max_budget || "") + '" /></label>' +
      '</div>' +
      '<label class="field"><span class="label">Learning goals</span><textarea class="textarea" id="sp-goals" rows="3">' + esc(profile.learning_goals || "") + "</textarea></label>";

    if (profile.preferred_mode) body.querySelector("#sp-mode").value = profile.preferred_mode;

    const actions = el("div", { class: "btn-group", style: { marginTop: "6px" } });
    const save = el("button", { class: "btn btn-primary", type: "button" }, "Save profile");
    save.addEventListener("click", async () => {
      setLoading(save, true, "Saving…");
      try {
        await API.updateMe({
          full_name: body.querySelector("#sp-name").value.trim(),
          phone: body.querySelector("#sp-phone").value.trim() || null,
          avatar_url: body.querySelector("#sp-avatar").value.trim() || null
        });
        await API.put("/students/me", {
          city: body.querySelector("#sp-city").value.trim() || null,
          state: body.querySelector("#sp-state").value.trim() || null,
          education_level: body.querySelector("#sp-level").value.trim() || null,
          guardian_name: body.querySelector("#sp-guardian").value.trim() || null,
          preferred_mode: body.querySelector("#sp-mode").value || null,
          max_budget: body.querySelector("#sp-budget").value ? Number(body.querySelector("#sp-budget").value) : null,
          learning_goals: body.querySelector("#sp-goals").value.trim() || null
        });
        ME = await API.refreshMe();
        toastSuccess("Profile saved.");
        renderHeader(); renderSidebar(); route();
      } catch (err) {
        setLoading(save, false);
        body.querySelector("#spErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>' + esc(err.message) + "</div></div>";
      }
    });
    actions.appendChild(save);
    host.appendChild(card(null, [body, actions]));
  };

  ROUTES["student:reviews"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("My reviews", "Reviews you have written after completed sessions."));
    const items = await API.myReviews();
    if (!items.length) {
      host.innerHTML += UI.emptyState({ icon: ic("star-fill"), title: "No reviews written yet",
        message: "After a session is marked complete, you can rate the tutor 1–5 stars and share feedback." });
      return;
    }
    const list = el("div", { class: "list" });
    items.forEach((review) => {
      list.appendChild(el("div", { class: "list-item" }, [
        el("div", { class: "main" }, [
          el("h4", { html: esc(review.title || "Review") + " " + stars(review.rating, null, false) }),
          el("div", { class: "meta" }, [
            review.subject_name ? metaSpan("book-fill", review.subject_name) : null,
            metaSpan("calendar3", formatDate(review.created_at))
          ].filter(Boolean)),
          review.comment ? el("p", { class: "small muted", style: { margin: "8px 0 0" }, text: review.comment }) : null
        ].filter(Boolean)),
        el("div", { class: "side" }, [
          (() => { const b = el("button", { class: "btn btn-soft-danger btn-sm", type: "button" }, "Delete");
            b.addEventListener("click", async () => {
              const ok = await UI.confirmDialog({ title: "Delete this review?", body: "The tutor's rating will be recalculated immediately.", confirmLabel: "Delete", danger: true });
              if (!ok) return;
              try { const res = await API.deleteReview(review.id); toastSuccess(res.detail); route(); }
              catch (err) { toastError(err.message); }
            }); return b; })()
        ])
      ]));
    });
    host.appendChild(card(null, [list]));
  };

  /* ------------------------------------------------------------ ADMIN ---- */
  ROUTES["admin:overview"] = async (host) => {
    host.innerHTML = "";
    const stats = await API.adminStats(14);
    host.appendChild(sectionTitle("Platform overview", "Every figure below is computed live from the database."));

    host.appendChild(el("div", { class: "stats-strip" }, [
      statCard("Total users", stats.total_users, ic("people-fill")),
      statCard("Tutors", stats.total_tutors, ic("mortarboard-fill"), "accent"),
      statCard("Students", stats.total_students, ic("backpack-fill"), "green"),
      statCard("Pending approvals", stats.pending_tutor_approvals, ic("hourglass-split"), "amber")
    ]));
    host.appendChild(el("div", { class: "stats-strip" }, [
      statCard("Booking requests", stats.total_requests, ic("envelope-fill")),
      statCard("Pending requests", stats.pending_requests, ic("hourglass-bottom"), "amber"),
      statCard("Completed sessions", stats.completed_requests, ic("check-circle-fill"), "green"),
      statCard("Session value", money(stats.gross_session_value), ic("cash-coin"), "rose")
    ]));

    const charts = el("div", { class: "chart-row" });
    const donutCard = card("Requests by status", [el("div", { html: donut(stats.requests_by_status, stats.total_requests, "requests") })]);
    charts.appendChild(donutCard);
    charts.appendChild(card("Signups (last 14 days)", [el("div", { html: sparkline(stats.signups_by_day) })]));
    charts.appendChild(card("Requests (last 14 days)", [el("div", { html: sparkline(stats.requests_by_day) })]));
    host.appendChild(charts);

    const charts2 = el("div", { class: "chart-row" });
    charts2.appendChild(card("Top subjects by tutor supply", [el("div", { html: barList(stats.top_subjects) })]));
    charts2.appendChild(card("Tutors by state", [el("div", { html: barList(stats.tutors_by_state) })]));
    charts2.appendChild(card("Platform health", [
      el("div", { class: "info-grid" }, [
        infoTileSmall("Subjects", stats.total_subjects),
        infoTileSmall("Availability slots", stats.total_availability_slots),
        infoTileSmall("Reviews", stats.total_reviews),
        infoTileSmall("Hidden reviews", stats.hidden_reviews),
        infoTileSmall("Average rating", stats.average_rating ? stats.average_rating.toFixed(2) + " " + ic("star-fill") : "–"),
        infoTileSmall("Active users", stats.active_users),
        infoTileSmall("New users (7d)", "+" + stats.new_users_last_7_days),
        infoTileSmall("Requests (7d)", "+" + stats.requests_last_7_days)
      ])
    ]));
    host.appendChild(charts2);

    const activity = await API.adminActivity(12);
    const list = el("div", { class: "list" });
    if (!activity.length) list.innerHTML = '<p class="muted small">No activity recorded yet.</p>';
    activity.forEach((item) => {
      list.appendChild(el("div", { class: "list-item", style: { padding: "12px 14px" } }, [
        el("div", { class: "notif-icon", html: activityIcon(item.action) }),
        el("div", { class: "main" }, [
          el("h4", { style: { fontSize: "0.92rem" }, text: item.description }),
          el("div", { class: "meta" }, [
            metaSpan("person-fill", item.actor_name || "System"),
            metaSpan("clock-fill", timeAgo(item.created_at)),
            el("span", { class: "badge badge-outline", text: item.action.replace(/_/g, " ") })
          ])
        ])
      ]));
    });
    host.appendChild(card("Recent activity", [list], {
      action: (() => { const b = el("button", { class: "btn btn-sm btn-outline", type: "button" }, "Full log");
        b.addEventListener("click", () => go("activity")); return b; })()
    }));
  };

  function infoTileSmall(k, v) {
    return el("div", { class: "info-tile" }, [el("div", { class: "k", text: k }), el("div", { class: "v", html: String(v) })]);
  }

  function activityIcon(action) {
    const map = {
      user_registered: ic("person-fill"), tutor_profile_created: ic("mortarboard-fill"), tutor_profile_updated: ic("pencil-fill"),
      tutor_approved: ic("check-circle-fill"), tutor_suspended: ic("slash-circle"), availability_added: ic("calendar3"),
      availability_removed: ic("trash-fill"), request_created: ic("envelope-fill"), request_accepted: ic("check2-circle"),
      request_rejected: ic("x-circle-fill"), request_cancelled: ic("slash-circle"), request_completed: ic("flag-fill"),
      review_created: ic("star-fill"), review_deleted: ic("eraser-fill"), user_deactivated: ic("lock-fill"), user_activated: ic("unlock-fill")
    };
    return map[action] || "•";
  }

  ROUTES["admin:users"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("Users", "Manage every account on the platform."));

    const controls = el("div", { class: "toolbar" }, [
      (() => { const w = el("div", { class: "search-input-wrap grow", style: { minWidth: "220px" } });
        w.innerHTML = '<span class="search-icon"><i class="bi bi-search"></i></span><input class="input" type="search" id="au-q" placeholder="Search by name or email…" />';
        return w; })(),
      (() => { const s = el("select", { class: "select", id: "au-role", style: { minWidth: "170px" } });
        s.innerHTML = '<option value="">All roles</option><option value="tutor">Tutors</option>' +
          '<option value="student">Students</option><option value="admin">Admins</option>';
        return s; })(),
      (() => { const b = el("button", { class: "btn btn-primary btn-sm", type: "button" }, "＋ Create user");
        b.addEventListener("click", createUserModal); return b; })()
    ]);
    host.appendChild(controls);

    const tableHost = el("div", {});
    host.appendChild(tableHost);

    async function load() {
      tableHost.innerHTML = '<div class="card"><div class="card-pad">' + UI.skeletonRows(5) + "</div></div>";
      const users = await API.adminUsers({
        q: document.getElementById("au-q").value.trim(),
        role: document.getElementById("au-role").value,
        page_size: 50
      });
      tableHost.innerHTML = "";
      if (!users.length) {
        tableHost.innerHTML = UI.emptyState({ icon: ic("people-fill"), title: "No users match", message: "Try a different search or role filter." });
        return;
      }
      const rows = users.map((u) =>
        "<tr>" +
          '<td><div class="cell-user">' + (u.avatar_url
            ? '<img src="' + esc(u.avatar_url) + '" alt="" onerror="this.style.display=\'none\'" />'
            : '<div class="avatar avatar-sm avatar-fallback">' + esc(UI.initials(u.full_name)) + "</div>") +
            "<div><strong>" + esc(u.full_name) + "</strong><div class='tiny faint'>" + esc(u.email) + "</div></div></div></td>" +
          "<td><span class='badge badge-primary'>" + esc(App.roleLabel(u.role, u)) + "</span></td>" +
          "<td>" + esc(u.city || "–") + "<div class='tiny faint'>" + esc(u.state || "") + "</div></td>" +
          "<td>" + (u.role === "tutor" ? (u.approval_status ? "<span class='badge badge-" +
            (u.approval_status === "approved" ? "accepted" : u.approval_status === "pending" ? "pending" : "rejected") + "'>" +
            esc(u.approval_status) + "</span>" : "–") : "–") + "</td>" +
          "<td>" + esc(u.requests_count) + "</td>" +
          "<td>" + (u.is_active ? "<span class='badge badge-accepted'>Active</span>" : "<span class='badge badge-cancelled'>Suspended</span>") + "</td>" +
          "<td class='tiny faint'>" + esc(u.last_login_at ? timeAgo(u.last_login_at) : "never") + "</td>" +
          '<td><div class="btn-group" data-id="' + u.id + '"></div></td>' +
        "</tr>").join("");

      tableHost.innerHTML = '<div class="table-wrap"><table class="data"><thead><tr>' +
        "<th>User</th><th>Role</th><th>Location</th><th>Approval</th><th>Requests</th><th>Status</th><th>Last login</th><th>Actions</th>" +
        "</tr></thead><tbody>" + rows + "</tbody></table></div>";

      tableHost.querySelectorAll("tbody tr").forEach((tr, index) => {
        const user = users[index];
        const group = tr.querySelector(".btn-group");
        const toggle = el("button", { class: "btn btn-sm " + (user.is_active ? "btn-soft-danger" : "btn-success"), type: "button" },
          user.is_active ? "Suspend" : "Restore");
        toggle.addEventListener("click", async () => {
          try { const res = await API.adminToggleUser(user.id); toastSuccess("Account " + (user.is_active ? "suspended" : "restored") + "."); load(); }
          catch (err) { toastError(err.message); }
        });
        const del = el("button", { class: "btn btn-sm btn-ghost", type: "button" }, "Delete");
        del.addEventListener("click", async () => {
          const ok = await UI.confirmDialog({
            title: "Delete " + user.full_name + "?",
            body: "This permanently removes the account and all related profiles, requests and reviews.",
            confirmLabel: "Delete user", danger: true
          });
          if (!ok) return;
          try { const res = await API.adminDeleteUser(user.id); toastSuccess(res.detail); load(); }
          catch (err) { toastError(err.message); }
        });
        group.appendChild(toggle);
        group.appendChild(del);
      });
    }

    const debounced = UI.debounce(load, 350);
    document.getElementById("au-q").addEventListener("input", debounced);
    document.getElementById("au-role").addEventListener("change", load);
    await load();
  };

  function createUserModal() {
    const body = el("div", {});
    body.innerHTML =
      '<div id="cuErr"></div>' +
      '<label class="field"><span class="label">Full name</span><input class="input" id="cu-name" /></label>' +
      '<label class="field"><span class="label">Email</span><input class="input" type="email" id="cu-email" /></label>' +
      '<label class="field"><span class="label">Temporary password</span><input class="input" type="text" id="cu-pass" placeholder="At least 8 characters with a number" /></label>' +
      '<label class="field"><span class="label">Role</span><select class="select" id="cu-role">' +
        '<option value="student">Student</option><option value="parent">Parent</option>' +
        '<option value="tutor">Tutor</option><option value="admin">Administrator</option></select></label>' +
      '<p class="hint">Parent accounts manage a child’s learning (family dashboard). Tutor accounts created here still need a profile before they appear in search.</p>';

    UI.modal({
      title: "Create a user account",
      subtitle: "Useful for adding another administrator or onboarding a tutor manually.",
      body,
      buttons: [
        { label: "Cancel", class: "btn-outline", onClick: (b, bb, close) => close() },
        {
          label: "Create account", class: "btn-primary",
          onClick: async (btn, bb, close) => {
            setLoading(btn, true, "Creating…");
            try {
              const chosenRole = body.querySelector("#cu-role").value;
              const newUserEmail = body.querySelector("#cu-email").value.trim();
              if (chosenRole === "parent") {
                // remember the parent persona locally (same store the auth portal uses)
                try {
                  const all = JSON.parse(localStorage.getItem("tm_personas") || "{}");
                  all[String(newUserEmail).toLowerCase()] = { persona: "parent" };
                  localStorage.setItem("tm_personas", JSON.stringify(all));
                } catch (e) { /* best effort */ }
              }
              await API.adminCreateUser({
                full_name: body.querySelector("#cu-name").value.trim(),
                email: newUserEmail,
                password: body.querySelector("#cu-pass").value,
                role: chosenRole === "parent" ? "student" : chosenRole
              });
              close(); toastSuccess("Account created."); route();
            } catch (err) {
              setLoading(btn, false);
              body.querySelector("#cuErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>' + esc(err.message) + "</div></div>";
            }
          }
        }
      ]
    });
  }

  ROUTES["admin:tutors"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("Tutors & approvals", "Approve, verify, suspend or remove tutor profiles."));

    const tabs = el("div", { class: "pill-tabs" });
    const listHost = el("div", {});
    host.appendChild(tabs);
    host.appendChild(listHost);
    let active = "";

    async function load() {
      listHost.innerHTML = '<div class="card"><div class="card-pad">' + UI.skeletonRows(4) + "</div></div>";
      const res = await API.adminTutors({ approval_status: active || undefined, page_size: 30 });
      const counts = { "": res.total, pending: 0, approved: 0, suspended: 0 };
      (res.items || []).forEach((t) => { counts[t.approval_status] = (counts[t.approval_status] || 0) + 1; });

      tabs.innerHTML = "";
      [["", "All"], ["approved", "Approved"], ["pending", "Pending"], ["suspended", "Suspended"]].forEach(([key, label]) => {
        const btn = el("button", { class: "pill-tab" + (active === key ? " active" : ""), type: "button" },
          label + (counts[key] ? " (" + counts[key] + ")" : ""));
        btn.addEventListener("click", () => { active = key; load(); });
        tabs.appendChild(btn);
      });

      listHost.innerHTML = "";
      if (!res.items.length) {
        listHost.innerHTML = UI.emptyState({ icon: ic("mortarboard-fill"), title: "No tutors in this view", message: "Try another status filter." });
        return;
      }
      const list = el("div", { class: "list" });
      res.items.forEach((t) => {
        const row = el("div", { class: "list-item" }, [
          UI.image(t.avatar_url, t.full_name, "thumb", t.full_name),
          el("div", { class: "main" }, [
            el("h4", { html: esc(t.full_name) + " " +
              (t.verified ? '<span class="badge badge-verified"><i class="bi bi-patch-check-fill"></i> Verified</span>' : "") + " " +
              '<span class="badge badge-' + (t.approval_status === "approved" ? "accepted" : t.approval_status === "pending" ? "pending" : "rejected") + '">' +
              esc(t.approval_status) + "</span>" }),
            el("p", { class: "small muted", style: { margin: "3px 0 0" }, text: t.headline }),
            el("div", { class: "meta" }, [
              metaSpan("geo-alt-fill", t.city + ", " + t.state),
              metaSpan("cash-coin", money(t.hourly_rate)),
              metaSpan("mortarboard-fill", t.years_experience + " yrs"),
              metaSpan("star-fill", t.review_count ? t.rating.toFixed(1) + " (" + t.review_count + ")" : "no reviews"),
              metaSpan("calendar3", t.availability.length + " slots"),
              metaSpan("check-circle-fill", t.completed_sessions + " completed")
            ])
          ]),
          el("div", { class: "side" })
        ]);
        const side = row.querySelector(".side");
        side.appendChild(el("a", { class: "btn btn-ghost btn-sm", href: "tutor-profile.html?id=" + t.id, target: "_blank" }, "View"));

        if (t.approval_status !== "approved") {
          const approve = el("button", { class: "btn btn-success btn-sm", type: "button" }, "Approve");
          approve.addEventListener("click", async () => {
            try { await API.setTutorStatus(t.id, { approval_status: "approved", verified: true }); toastSuccess(t.full_name + " approved and verified."); load(); }
            catch (err) { toastError(err.message); }
          });
          side.appendChild(approve);
        } else {
          const suspend = el("button", { class: "btn btn-soft-danger btn-sm", type: "button" }, "Suspend");
          suspend.addEventListener("click", async () => {
            const reason = await UI.promptDialog({ title: "Suspend " + t.full_name, label: "Reason (shared with the tutor)", confirmLabel: "Suspend profile" });
            if (reason === null) return;
            try { await API.setTutorStatus(t.id, { approval_status: "suspended", reason: reason || undefined }); toastSuccess(t.full_name + " suspended."); load(); }
            catch (err) { toastError(err.message); }
          });
          side.appendChild(suspend);
        }
        const verify = el("button", { class: "btn btn-outline btn-sm", type: "button" }, t.verified ? "Unverify" : "Verify");
        verify.addEventListener("click", async () => {
          try { await API.setTutorStatus(t.id, { approval_status: t.approval_status, verified: !t.verified }); toastSuccess("Verification updated."); load(); }
          catch (err) { toastError(err.message); }
        });
        side.appendChild(verify);

        const del = el("button", { class: "btn btn-ghost btn-sm", type: "button" }, "Delete");
        del.addEventListener("click", async () => {
          const ok = await UI.confirmDialog({ title: "Delete this tutor profile?",
            body: "Removes the profile, subjects, availability and reviews. The user account stays active.", confirmLabel: "Delete", danger: true });
          if (!ok) return;
          try { const res = await API.del("/tutors/" + t.id); toastSuccess(res.detail); load(); }
          catch (err) { toastError(err.message); }
        });
        side.appendChild(del);
        list.appendChild(row);
      });
      listHost.appendChild(list);
    }
    await load();
  };

  ROUTES["admin:requests"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("All booking requests", "Monitor and moderate every request across the platform."));

    const tabs = el("div", { class: "pill-tabs" });
    const listHost = el("div", {});
    host.appendChild(tabs);
    host.appendChild(el("div", { class: "card" }, [el("div", { class: "card-pad" }, [listHost])]));
    let active = "";

    async function load() {
      listHost.innerHTML = UI.skeletonRows(5);
      const res = await API.adminRequests({ status: active || undefined, page_size: 50 });
      tabs.innerHTML = "";
      [["", "All"], ["pending", "Pending"], ["accepted", "Accepted"], ["completed", "Completed"], ["rejected", "Rejected"], ["cancelled", "Cancelled"]]
        .forEach(([key, label]) => {
          const btn = el("button", { class: "pill-tab" + (active === key ? " active" : ""), type: "button" }, label);
          btn.addEventListener("click", () => { active = key; load(); });
          tabs.appendChild(btn);
        });

      listHost.innerHTML = "";
      if (!res.items.length) { listHost.innerHTML = UI.emptyState({ icon: ic("inbox"), title: "No requests", message: "Nothing in this status." }); return; }
      const head = el("p", { class: "small muted" }, plural(res.total, "request") + " total");
      listHost.appendChild(head);
      const list = el("div", { class: "list" });
      res.items.forEach((r) => {
        const row = requestRow(r, { as: "admin" });
        const meta = row.querySelector(".meta");
        meta.appendChild(metaSpan("mortarboard-fill", r.tutor.name));
        meta.appendChild(metaSpan("backpack-fill", r.student.name));
        list.appendChild(row);
      });
      listHost.appendChild(list);
    }
    await load();
  };

  ROUTES["admin:reviews"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("Reviews moderation", "Hide inappropriate content — ratings recalculate automatically."));

    const controls = el("div", { class: "toolbar" }, [
      (() => { const l = el("label", { class: "check" });
        l.innerHTML = '<input type="checkbox" id="ar-hidden" /><span>Include hidden reviews</span>'; return l; })()
    ]);
    host.appendChild(controls);
    const listHost = el("div", {});
    host.appendChild(listHost);

    async function load() {
      listHost.innerHTML = '<div class="card"><div class="card-pad">' + UI.skeletonRows(4) + "</div></div>";
      const res = await API.adminReviews({ include_hidden: document.getElementById("ar-hidden").checked, page_size: 50 });
      listHost.innerHTML = "";
      if (!res.items.length) { listHost.innerHTML = UI.emptyState({ icon: ic("star-fill"), title: "No reviews", message: "Reviews appear after completed sessions." }); return; }
      const list = el("div", { class: "list" });
      res.items.forEach((review) => {
        list.appendChild(el("div", { class: "list-item" }, [
          el("div", { class: "main" }, [
            el("h4", { html: esc(review.title || "Review") + " " + stars(review.rating, null, false) +
              (review.is_deleted ? ' <span class="badge badge-rejected">Hidden</span>' : "") }),
            el("div", { class: "meta" }, [
              metaSpan("backpack-fill", review.student.name),
              metaSpan("mortarboard-fill", review.tutor.name),
              metaSpan("clock-fill", timeAgo(review.created_at))
            ]),
            review.comment ? el("p", { class: "small muted", style: { margin: "8px 0 0" }, text: review.comment }) : null,
            review.deleted_reason ? el("div", { class: "note warn" }, "Reason: " + esc(review.deleted_reason)) : null
          ].filter(Boolean)),
          el("div", { class: "side" }, [
            review.is_deleted
              ? (() => { const b = el("button", { class: "btn btn-success btn-sm", type: "button" }, "Restore");
                  b.addEventListener("click", async () => {
                    try { const res = await API.adminRestoreReview(review.id); toastSuccess(res.detail); load(); }
                    catch (err) { toastError(err.message); }
                  }); return b; })()
              : (() => { const b = el("button", { class: "btn btn-soft-danger btn-sm", type: "button" }, "Hide");
                  b.addEventListener("click", async () => {
                    const reason = await UI.promptDialog({ title: "Hide this review", label: "Reason", value: "Violates community guidelines", confirmLabel: "Hide review" });
                    if (reason === null) return;
                    try { const res = await API.adminHideReview(review.id, reason); toastSuccess(res.detail); load(); }
                    catch (err) { toastError(err.message); }
                  }); return b; })()
          ])
        ]));
      });
      listHost.appendChild(card(plural(res.total, "review"), [list]));
    }
    document.getElementById("ar-hidden").addEventListener("change", load);
    await load();
  };

  ROUTES["admin:subjects"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("Subjects", "Control the vocabulary tutors can select from.",
      (() => { const b = el("button", { class: "btn btn-primary btn-sm", type: "button" }, "＋ Add subject");
        b.addEventListener("click", () => subjectModal()); return b; })()));

    const res = await API.subjects({});
    const items = res.items || [];
    if (!items.length) { host.innerHTML += UI.emptyState({ icon: ic("book-fill"), title: "No subjects", message: "Add subjects so tutors can list them." }); return; }

    /* subject emojis (s.icon) are kept on purpose */
    const rows = items.map((s) =>
      "<tr><td><strong>" + UI.subjectIcon(s.icon) + " " + esc(s.name) + "</strong></td><td>" + esc(s.category || "–") +
      "</td><td>" + esc(s.tutor_count) + "</td><td><div class='btn-group' data-id='" + s.id + "'></div></td></tr>").join("");
    const tableHost = el("div", {});
    tableHost.innerHTML = '<div class="table-wrap"><table class="data"><thead><tr><th>Subject</th><th>Category</th><th>Tutors</th><th>Actions</th></tr></thead><tbody>' + rows + "</tbody></table></div>";
    host.appendChild(tableHost);

    tableHost.querySelectorAll("tbody tr").forEach((tr, index) => {
      const subject = items[index];
      const group = tr.querySelector(".btn-group");
      const edit = el("button", { class: "btn btn-sm btn-outline", type: "button" }, "Edit");
      edit.addEventListener("click", () => subjectModal(subject));
      const del = el("button", { class: "btn btn-sm btn-ghost", type: "button" }, "Remove");
      del.addEventListener("click", async () => {
        const ok = await UI.confirmDialog({ title: "Remove " + subject.name + "?",
          body: subject.tutor_count ? "This subject is used by " + subject.tutor_count + " tutor(s), so it will be hidden instead of deleted."
            : "This permanently deletes the subject.", confirmLabel: "Remove", danger: true });
        if (!ok) return;
        try { const r = await API.deleteSubject(subject.id); toastSuccess(r.detail); route(); }
        catch (err) { toastError(err.message); }
      });
      group.appendChild(edit);
      group.appendChild(del);
    });
  };

  function subjectModal(subject) {
    const body = el("div", {});
    body.innerHTML =
      '<div id="sjErr"></div>' +
      '<label class="field"><span class="label">Subject name</span><input class="input" id="sj-name" value="' + esc(subject ? subject.name : "") + '" /></label>' +
      '<div class="field-row">' +
        '<label class="field"><span class="label">Category</span><input class="input" id="sj-category" value="' + esc(subject ? (subject.category || "") : "") + '" placeholder="e.g. STEM" /></label>' +
        '<label class="field"><span class="label">Icon name</span><input class="input" id="sj-icon" maxlength="40" value="' + esc(subject ? (subject.icon || "") : "") + '" placeholder="bi-book" />' +
          '<div class="hint">Example: bi-calculator. Find names at icons.getbootstrap.com</div></label>' +
      '</div>';

    UI.modal({
      title: subject ? "Edit subject" : "Add subject",
      body,
      buttons: [
        { label: "Cancel", class: "btn-outline", onClick: (b, bb, close) => close() },
        {
          label: subject ? "Save" : "Add", class: "btn-primary",
          onClick: async (btn, bb, close) => {
            const payload = {
              name: body.querySelector("#sj-name").value.trim(),
              category: body.querySelector("#sj-category").value.trim() || null,
              icon: body.querySelector("#sj-icon").value.trim() || null
            };
            if (!payload.name) { body.querySelector("#sjErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>Name is required.</div></div>'; return; }
            setLoading(btn, true, "Saving…");
            try {
              const res = subject ? await API.updateSubject(subject.id, payload) : await API.createSubject(payload);
              close(); toastSuccess(res.detail); route();
            } catch (err) {
              setLoading(btn, false);
              body.querySelector("#sjErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>' + esc(err.message) + "</div></div>";
            }
          }
        }
      ]
    });
  }

  ROUTES["admin:activity"] = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("Activity log", "A complete audit trail of platform events."));
    const items = await API.adminActivity(120);
    if (!items.length) { host.innerHTML += UI.emptyState({ icon: ic("clock-fill"), title: "No activity", message: "Actions will appear here as users interact with the platform." }); return; }
    const list = el("div", { class: "list" });
    items.forEach((item) => {
      list.appendChild(el("div", { class: "list-item" }, [
        el("div", { class: "notif-icon", html: activityIcon(item.action) }),
        el("div", { class: "main" }, [
          el("h4", { style: { fontSize: "0.93rem" }, text: item.description }),
          el("div", { class: "meta" }, [
            metaSpan("person-fill", item.actor_name || "System"),
            metaSpan("clock-fill", formatDate(item.created_at) + " " + timeAgo(item.created_at)),
            item.entity_type ? el("span", { class: "badge badge-outline", text: item.entity_type + (item.entity_id ? " #" + item.entity_id : "") }) : null
          ].filter(Boolean))
        ])
      ]));
    });
    host.appendChild(card(plural(items.length, "event"), [list]));
  };

  /* ------------------------------------------------- shared: account ----- */
  const accountView = async (host) => {
    host.innerHTML = "";
    host.appendChild(sectionTitle("Account settings", "Update your credentials and personal details."));

    const body = el("div", {});
    body.innerHTML =
      '<div id="acErr"></div>' +
      '<div class="field-row">' +
        '<label class="field"><span class="label">Full name</span><input class="input" id="ac-name" value="' + esc(ME.full_name) + '" /></label>' +
        '<label class="field"><span class="label">Phone</span><input class="input" id="ac-phone" value="' + esc(ME.phone || "") + '" /></label>' +
      '</div>' +
      '<label class="field"><span class="label">Email <span class="tiny faint">(cannot be changed)</span></span>' +
        '<input class="input" value="' + esc(ME.email) + '" disabled /></label>' +
      '<div class="field"><span class="label">Profile photo</span><div id="ac-photo"></div></div>' +
      '<div class="info-box" style="margin-bottom:18px">Role: <strong>' + esc(App.roleLabel(ME.role, ME)) + '</strong> · Member since ' + esc(formatDate(ME.created_at)) +
        (ME.last_login_at ? " · Last login " + esc(timeAgo(ME.last_login_at)) : "") + "</div>";

    // upload from device, replace (edit) or delete the saved photo — no URL typing
    const photoField = UI.photoPicker({
      currentUrl: ME.avatar_url || "",
      currentName: ME.full_name,
      onSelect: async (dataUrl) => {
        const res = await API.uploadAvatar(dataUrl);
        ME.avatar_url = (res.data && res.data.avatar_url) || null;
        API.store.user = ME;
        photoField.setCurrent(ME.avatar_url || "");
        UI.buildNav(); renderHeader();
        toastSuccess("Profile photo updated.");
      },
      onRemove: async () => {
        await API.deleteAvatar();
        ME.avatar_url = null;
        API.store.user = ME;
        UI.buildNav(); renderHeader();
        toastSuccess("Profile photo removed.");
      }
    });
    body.querySelector("#ac-photo").appendChild(photoField.el);

    const save = el("button", { class: "btn btn-primary", type: "button" }, "Save changes");
    save.addEventListener("click", async () => {
      setLoading(save, true, "Saving…");
      try {
        await API.updateMe({
          full_name: body.querySelector("#ac-name").value.trim(),
          phone: body.querySelector("#ac-phone").value.trim() || null
        });
        ME = await API.refreshMe();
        toastSuccess("Account updated.");
        UI.buildNav();
        renderHeader(); renderSidebar();
        route();
      } catch (err) {
        setLoading(save, false);
        body.querySelector("#acErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>' + esc(err.message) + "</div></div>";
      }
    });
    host.appendChild(card("Personal details", [body, save]));

    /* password */
    const pw = el("div", {});
    pw.innerHTML =
      '<div id="pwErr"></div>' +
      '<label class="field"><span class="label">Current password</span><input class="input" type="password" id="pw-current" autocomplete="current-password" /></label>' +
      '<label class="field"><span class="label">New password</span><input class="input" type="password" id="pw-new" autocomplete="new-password" minlength="8" />' +
        '<div class="strength" id="pw-strength" data-score="0"><i></i><i></i><i></i><i></i></div>' +
        '<div class="strength-text" id="pw-strength-text">8+ characters with letters and numbers.</div></label>' +
      '<label class="field"><span class="label">Confirm new password</span><input class="input" type="password" id="pw-confirm" autocomplete="new-password" /></label>';
    UI.addPasswordToggles(pw);   // eye buttons on all three password fields
    const pwSave = el("button", { class: "btn btn-dark", type: "button" }, "Update password");
    pwSave.addEventListener("click", async () => {
      const current = pw.querySelector("#pw-current").value;
      const next = pw.querySelector("#pw-new").value;
      const confirm = pw.querySelector("#pw-confirm").value;
      if (next !== confirm) { pw.querySelector("#pwErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>New passwords do not match.</div></div>'; return; }
      setLoading(pwSave, true, "Updating…");
      try {
        const res = await API.changePassword({ current_password: current, new_password: next });
        toastSuccess(res.detail);
        pw.querySelectorAll("input").forEach((i) => { i.value = ""; });
        pw.querySelector("#pwErr").innerHTML = "";
      } catch (err) {
        pw.querySelector("#pwErr").innerHTML = '<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle-fill"></i></span><div>' + esc(err.message) + "</div></div>";
      } finally { setLoading(pwSave, false); }
    });
    pw.querySelector("#pw-new").addEventListener("input", (e) => {
      const s = UI.passwordStrength(e.target.value);
      pw.querySelector("#pw-strength").dataset.score = String(s.score);
      pw.querySelector("#pw-strength-text").textContent = e.target.value ? "Strength: " + s.label : "8+ characters with letters and numbers.";
    });
    host.appendChild(card("Password", [pw, pwSave]));

    /* danger zone */
    const danger = el("div", {});
    danger.innerHTML = '<p class="muted small">Deactivating hides your account and prevents sign-in. An administrator can restore it.</p>';
    const dangerBtn = el("button", { class: "btn btn-soft-danger", type: "button" }, "Deactivate my account");
    dangerBtn.addEventListener("click", async () => {
      const ok = await UI.confirmDialog({
        title: "Deactivate your account?",
        body: "You will be signed out immediately and will not be able to sign back in without an administrator.",
        confirmLabel: "Deactivate", danger: true
      });
      if (!ok) return;
      try { await API.del("/auth/me"); await API.logout(); location.href = "index.html"; }
      catch (err) { toastError(err.message); }
    });
    danger.appendChild(dangerBtn);
    host.appendChild(card("Danger zone", [danger]));
  };

  ROUTES["tutor:account"] = accountView;
  ROUTES["student:account"] = accountView;
  ROUTES["admin:account"] = accountView;

  ROUTES["student:browse"] = () => { location.href = "tutors.html"; };

  document.addEventListener("DOMContentLoaded", init);
})();