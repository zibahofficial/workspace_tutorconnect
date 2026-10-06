/* ==========================================================================
   tutor-profile.js — one tutor, fully rendered from GET /api/tutors/{id}
   plus real open-slot computation for the booking modal.
   ========================================================================== */
(function () {
  "use strict";

  const { esc, money, el, stars, to12h, formatDayDate, relativeDate, formatDate,
          MODE_LABELS, toastSuccess, toastError, toastInfo, plural } = UI;

  /* icon helper: ic("search") -> <i class="bi bi-search"></i> */
  const ic = (name) => '<i class="bi bi-' + name + '"></i>';
  const WARN = '<i class="bi bi-exclamation-triangle-fill"></i>';

  let tutor = null;
  let openSlotsCache = {};
  let selectedDate = null;
  let selectedTime = null;
  let bookingModal = null;

  /* -------------------------------------------------------------- init --- */
  async function init() {
    const ok = await App.boot();
    if (!ok) return;

    const params = UI.readQueryParams();
    const id = params.id;
    const host = document.getElementById("profileHost");

    if (!id) {
      showFatal("No tutor selected", "Open a tutor from the search results to see their full profile.");
      return;
    }

    try {
      tutor = await API.tutor(id);
    } catch (err) {
      if (err.status === 404) showFatal("Tutor not found", err.message, "Browse tutors", "tutors.html");
      else showFatal("Could not load this profile", err.message, "Try again", null, () => init());
      return;
    }

    document.getElementById("loadingHost").classList.add("hide");
    host.classList.remove("hide");
    document.title = tutor.full_name + " — " + tutor.headline + " | TutorConnect";
    render(host);

    if (params.book === "1") openBookingModal();
  }

  function showFatal(title, message, actionLabel, actionHref, onRetry) {
    document.getElementById("loadingHost").classList.add("hide");
    const host = document.getElementById("profileHost");
    host.classList.remove("hide");
    host.innerHTML = '<div class="container" style="padding-block:60px">' +
      UI.errorState(message, onRetry ? "Try again" : null) + "</div>";
    const empty = host.querySelector(".empty");
    empty.querySelector("h3").textContent = title;
    if (actionLabel) {
      empty.appendChild(el("div", { style: { marginTop: "10px" } }, [
        el("a", { class: "btn btn-outline", href: actionHref || "tutors.html" }, actionLabel)
      ]));
    }
    if (onRetry) {
      const btn = empty.querySelector("[data-retry]");
      if (btn) btn.addEventListener("click", onRetry);
    }
  }

  /* ------------------------------------------------------------ render --- */
  function render(host) {
    host.innerHTML = "";

    /* ---- hero ---- */
    const hero = el("section", { class: "profile-hero" });
    const bg = el("div", { class: "bg" });
    bg.appendChild(UI.image(tutor.cover_image_url ||
      "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=1600&q=80",
      tutor.full_name, "", tutor.full_name));
    hero.appendChild(bg);

    const facts = [
      ic("geo-alt-fill") + " " + esc(tutor.city) + ", " + esc(tutor.state),
      ic("mortarboard-fill") + " " + plural(tutor.years_experience || 0, "year") + " experience",
      ic("laptop") + " " + esc(MODE_LABELS[tutor.teaching_mode] || "Hybrid"),
      ic("calendar3") + " " + (tutor.availability || []).filter((s) => s.is_active).length + " weekly slots"
    ];
    hero.appendChild(el("div", { class: "container" }, [
      el("div", { class: "profile-id" }, [
        UI.image(tutor.avatar_url, tutor.full_name, "avatar avatar-xl", tutor.full_name),
        el("div", { class: "grow" }, [
          el("h1", { html: esc(tutor.full_name) + (tutor.verified ? ' <span class="badge badge-verified">' + ic("patch-check-fill") + ' Verified</span>' : "") }),
          el("p", { class: "headline", text: tutor.headline }),
          el("div", { class: "facts" }, facts.map((f) => el("span", { html: f })))
        ]),
        el("div", { class: "stack", style: { gap: "10px", alignItems: "flex-end" } }, [
          el("div", { html: stars(tutor.rating, tutor.review_count) + '<div class="tiny" style="color:rgba(255,255,255,.7)">' +
            (tutor.review_count ? plural(tutor.review_count, "review") + " from completed sessions" : "No reviews yet") + "</div>" }),
          el("div", { class: "row", style: { gap: "8px" } }, [
            (() => {
              const btn = el("button", { class: "btn btn-primary btn-lg", type: "button", html: ic("envelope-fill") + " Request a session" });
              btn.addEventListener("click", openBookingModal);
              return btn;
            })(),
            (() => {
              const fav = el("button", {
                class: "btn btn-glass", type: "button",
                html: (tutor.is_favorite ? '<i class="bi bi-heart-fill"></i> Saved' : '<i class="bi bi-heart"></i> Save')
              });
              fav.addEventListener("click", async () => {
                if (!API.isAuthenticated()) { location.href = "login.html?next=" + encodeURIComponent("tutor-profile.html?id=" + tutor.id); return; }
                if (API.role() !== "student") { toastInfo("Only students and parents can save tutors."); return; }
                try {
                  const res = await API.toggleFavorite(tutor.id);
                  tutor.is_favorite = res.data.is_favorite;
                  fav.innerHTML = tutor.is_favorite ? '<i class="bi bi-heart-fill"></i>' : '<i class="bi bi-heart"></i>';
                  fav.title = tutor.is_favorite ? "Saved" : "Save tutor";
                  toastSuccess(res.detail);
                } catch (err) { toastError(err.message); }
              });
              return fav;
            })()
          ])
        ])
      ])
    ]));
    host.appendChild(hero);

    /* ---- layout ---- */
    const layout = el("div", { class: "container profile-layout" });
    const left = el("div", { class: "stack" });
    const right = el("div", { class: "sticky-col" });
    layout.appendChild(left);
    layout.appendChild(right);
    host.appendChild(layout);

    /* ---- about ---- */
    left.appendChild(card("About " + tutor.full_name.split(" ")[0], ic("person-fill"), [
      el("p", { style: { whiteSpace: "pre-line", color: "var(--ink-600)" }, text: tutor.bio }),
      tutor.qualifications ? el("div", { style: { marginTop: "16px" } }, [
        el("span", { class: "label", text: "Qualifications" }),
        el("p", { class: "muted", style: { margin: 0, whiteSpace: "pre-line" }, text: tutor.qualifications })
      ]) : null,
      tutor.languages ? el("div", { style: { marginTop: "14px" } }, [
        el("span", { class: "label", text: "Languages" }),
        el("div", { class: "row-wrap" }, tutor.languages.split(",").map((l) => el("span", { class: "tag", text: l.trim() })))
      ]) : null
    ]));

    /* ---- subjects (subject emojis are kept on purpose) ---- */
    const subjectBody = el("div", {});
    if ((tutor.subjects || []).length) {
      const grid = el("div", { class: "subject-grid" });
      tutor.subjects.forEach((s) => {
        grid.appendChild(el("a", { class: "subject-tile", href: "tutors.html?subject_id=" + s.id }, [
          el("span", { class: "emoji", html: s.icon ? UI.subjectIcon(s.icon) : ic("book") }),
          el("span", {}, [
            el("strong", { text: s.name }),
            el("span", { text: s.proficiency + (s.levels ? " · " + s.levels : "") })
          ])
        ]));
      });
      subjectBody.appendChild(grid);
    } else {
      subjectBody.innerHTML = UI.emptyState({ icon: ic("book"), title: "No subjects listed", message: "This tutor has not published subjects yet." });
    }
    left.appendChild(card("Subjects taught", ic("book-fill"), [subjectBody]));

    /* ---- availability ---- */
    const availBody = el("div", {});
    const grouped = {};
    UI.DAYS.forEach((d) => { grouped[d] = []; });
    (tutor.availability || []).forEach((slot) => {
      if (!grouped[slot.day_of_week]) grouped[slot.day_of_week] = [];
      grouped[slot.day_of_week].push(slot);
    });
    const hasAny = (tutor.availability || []).some((s) => s.is_active);
    if (hasAny) {
      const grid = el("div", { class: "avail-grid" });
      UI.DAYS.forEach((day) => {
        const slots = (grouped[day] || []).filter((s) => s.is_active);
        const row = el("div", { class: "avail-day" + (slots.length ? "" : " empty") }, [
          el("span", { class: "day", text: day }),
          el("div", { class: "slots" }, slots.length
            ? slots.map((s) => el("span", { class: "slot-pill" }, to12h(s.start_time) + " – " + to12h(s.end_time)))
            : [el("span", { class: "small faint", text: "Not available" })])
        ]);
        grid.appendChild(row);
      });
      availBody.appendChild(grid);
      availBody.appendChild(el("p", { class: "hint", style: { marginTop: "12px" } },
        "Session length: " + (tutor.session_duration_minutes || 60) + " minutes. Booked times disappear automatically from the picker below."));
    } else {
      availBody.innerHTML = UI.emptyState({
        icon: ic("calendar3"), title: "No availability published",
        message: "This tutor has not set weekly availability yet. You can still send a request and propose a time."
      });
    }
    left.appendChild(card("Weekly availability", ic("calendar3"), [availBody]));

    /* ---- live open slots (next 7 days) ---- */
    const slotsCard = card("Next 7 days — pick a real open slot", ic("lightning-charge-fill"), [
      el("div", { id: "openSlotsHost" }, [el("p", { class: "muted small" }, "Loading live availability…")])
    ]);
    left.appendChild(slotsCard);
    loadOpenSlots(document.getElementById("openSlotsHost"), 7, (day, time) => openBookingModal(day, time));

    /* ---- reviews ---- */
    const reviewsCard = card("Reviews", ic("star-fill"), [el("div", { id: "reviewsHost" })]);
    left.appendChild(reviewsCard);
    renderReviews(document.getElementById("reviewsHost"));

    /* ---- right column ---- */
    right.appendChild(el("div", { class: "card" }, [
      el("div", { class: "card-pad" }, [
        el("div", { class: "row-between", style: { marginBottom: "14px" } }, [
          el("div", {}, [
            el("div", { style: { fontSize: "1.85rem", fontWeight: "800", fontFamily: "var(--font-display)", letterSpacing: "-0.03em" }, text: money(tutor.hourly_rate) }),
            el("div", { class: "small muted", text: "per " + (tutor.session_duration_minutes || 60) + "-minute session" })
          ]),
          el("div", { class: "right" }, [
            el("div", { style: { fontSize: "1.3rem", fontWeight: "750", fontFamily: "var(--font-display)" }, text: tutor.rating ? tutor.rating.toFixed(1) : "–" }),
            el("div", { class: "small faint", text: plural(tutor.review_count || 0, "review") })
          ])
        ]),
        (() => {
          const btn = el("button", { class: "btn btn-primary btn-block btn-lg", type: "button", html: ic("envelope-fill") + " Request a session" });
          btn.addEventListener("click", () => openBookingModal());
          return btn;
        })(),
        el("div", { class: "info-grid", style: { marginTop: "18px" } }, [
          infoTile("Experience", (tutor.years_experience || 0) + " yrs"),
          infoTile("Sessions done", String(tutor.completed_sessions || 0)),
          infoTile("Students taught", String(tutor.total_students || 0)),
          infoTile("Mode", MODE_LABELS[tutor.teaching_mode] || "Hybrid"),
          infoTile("Online", tutor.accepts_online ? "Yes" : "No"),
          infoTile("In person", tutor.accepts_in_person ? "Yes" : "No")
        ]),
        tutor.email ? el("div", { class: "info-box", style: { marginTop: "16px" },
          html: ic("envelope-fill") + " Contact on file: " + esc(tutor.email) + " — visible because you are signed in." }) : null
      ])
    ]));

    right.appendChild(card("Location", ic("geo-alt-fill"), [
      el("p", { style: { margin: 0 }, text: tutor.city + ", " + tutor.state + ", " + (tutor.country || "Nigeria") }),
      el("a", {
        class: "btn btn-outline btn-sm", style: { marginTop: "12px" },
        href: "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(tutor.city + ", " + tutor.state),
        target: "_blank", rel: "noopener noreferrer",
        html: "Open in Google Maps " + ic("box-arrow-up-right")
      }),
      el("div", { style: { marginTop: "14px" } }, [
        el("a", { href: "tutors.html?location=" + encodeURIComponent(tutor.state), class: "small",
          html: "See more tutors in " + esc(tutor.state) + " " + ic("arrow-right") })
      ])
    ]));

    const similar = el("div", { class: "card" }, [
      el("div", { class: "card-head" }, [el("h4", { text: "Similar tutors" })]),
      el("div", { class: "card-pad", id: "similarHost" }, [el("p", { class: "muted small" }, "Loading…")])
    ]);
    right.appendChild(similar);
    loadSimilar(document.getElementById("similarHost"));

    right.appendChild(el("div", { class: "card" }, [
      el("div", { class: "card-pad" }, [
        el("h4", { text: "Not the right fit?" }),
        el("p", { class: "muted small" }, "Filter by subject, budget and the days you are free — matches update instantly from the database."),
        el("a", { class: "btn btn-outline btn-sm btn-block", href: "tutors.html" }, "Browse all tutors")
      ])
    ]));
  }

  function card(title, icon, bodyNodes) {
    const body = el("div", { class: "card-pad" });
    bodyNodes.filter(Boolean).forEach((n) => body.appendChild(n));
    return el("div", { class: "card" }, [
      el("div", { class: "card-head" }, [el("h3", { html: (icon ? icon + " " : "") + esc(title) })]),
      body
    ]);
  }

  function infoTile(key, value) {
    return el("div", { class: "info-tile" }, [
      el("div", { class: "k", text: key }),
      el("div", { class: "v", text: value })
    ]);
  }

  /* --------------------------------------------------------- open slots -- */
  async function loadOpenSlots(host, days, onPick) {
    try {
      const data = await API.openSlots(tutor.id, { days: days });
      host.innerHTML = "";
      if (!data.total_open_slots) {
        host.innerHTML = UI.emptyState({
          icon: ic("calendar3"), title: "No open slots in the next " + days + " days",
          message: "This tutor is fully booked or has not published availability. Send a request and propose a time instead."
        });
        return;
      }
      const strip = el("div", { class: "date-strip" });
      const slotHost = el("div", { class: "row-wrap", style: { marginTop: "14px", gap: "8px" } });
      host.appendChild(strip);
      host.appendChild(slotHost);

      const renderDay = (dayData) => {
        strip.querySelectorAll(".date-chip").forEach((c) => c.classList.toggle("active", c.dataset.date === dayData.date));
        slotHost.innerHTML = "";
        if (!dayData.slots.length) {
          slotHost.appendChild(el("p", { class: "muted small", text: "No free slots on " + formatDayDate(dayData.date) + "." }));
          return;
        }
        dayData.slots.forEach((slot) => {
          const btn = el("button", {
            class: "slot-pill open" + (slot.held ? " held" : ""), type: "button",
            title: slot.mode_label + " · " + slot.duration_minutes + " minutes" +
              (slot.held ? " · already requested by another student" : "")
          }, slot.label);
          btn.addEventListener("click", () => onPick && onPick(dayData.date, slot.start_time));
          slotHost.appendChild(btn);
        });
      };

      data.days.forEach((dayData) => {
        const d = new Date(dayData.date + "T00:00:00");
        const chip = el("button", {
          class: "date-chip", type: "button", "data-date": dayData.date,
          disabled: dayData.slots.length === 0,
          title: dayData.slots.length + " open slot(s)"
        }, [
          el("div", { class: "dow", text: dayData.day_of_week.slice(0, 3) }),
          el("div", { class: "d", text: String(d.getDate()) }),
          el("div", { class: "m", text: d.toLocaleDateString("en-GB", { month: "short" }) }),
          el("div", { class: "tiny", style: { marginTop: "3px", color: dayData.slots.length ? "var(--green)" : "var(--text-faint)" },
            text: dayData.slots.length ? dayData.slots.length + " free" : "full" })
        ]);
        chip.addEventListener("click", () => renderDay(dayData));
        strip.appendChild(chip);
      });

      const firstOpen = data.days.find((d) => d.slots.length);
      if (firstOpen) renderDay(firstOpen);
    } catch (err) {
      host.innerHTML = UI.errorState(err.message);
    }
  }

  /* ----------------------------------------------------------- reviews --- */
  function renderReviews(host) {
    const reviews = tutor.reviews || [];
    host.innerHTML = "";
    const total = tutor.review_count || 0;

    const summary = el("div", { class: "rating-summary" }, [
      el("div", { class: "rating-big" }, [
        el("div", { class: "n", text: total ? Number(tutor.rating).toFixed(1) : "–" }),
        el("div", { html: stars(tutor.rating, null, false) }),
        el("div", { class: "small faint", text: plural(total, "review") })
      ])
    ]);
    const breakdown = el("div", { class: "breakdown" });
    (tutor.rating_breakdown || []).forEach((row) => {
      breakdown.appendChild(el("div", { class: "row-b" }, [
        el("span", { html: row.star + " " + ic("star-fill") }),
        el("span", { class: "track" }, [el("i", { style: { width: (row.percentage || 0) + "%" } })]),
        el("span", { class: "right", text: String(row.count) })
      ]));
    });
    summary.appendChild(breakdown);
    host.appendChild(summary);

    if (!reviews.length) {
      host.appendChild(el("div", { style: { paddingTop: "18px" } , html:
        UI.emptyState({ icon: ic("star-fill"), title: "No reviews yet",
          message: "Students can review this tutor after their first completed session." }) }));
      return;
    }

    reviews.forEach((review) => {
      const head = el("div", { class: "review-head" }, [
        UI.image(review.student_avatar_url, review.student_name, "", review.student_name),
        el("div", { class: "grow" }, [
          el("strong", { text: review.student_name }),
          el("div", { class: "when", text: formatDate(review.created_at) + (review.subject_name ? " · " + review.subject_name : "") })
        ]),
        el("div", { html: stars(review.rating, null, false) })
      ]);
      host.appendChild(el("div", { class: "review-item" }, [
        head,
        review.title ? el("h4", { text: review.title }) : null,
        review.comment ? el("p", { text: review.comment }) : null
      ].filter(Boolean)));
    });
  }

  /* ----------------------------------------------------------- similar --- */
  async function loadSimilar(host) {
    try {
      const subject = (tutor.subjects || [])[0];
      const params = { page_size: 4, sort: "rating" };
      if (subject) params.subject_id = subject.id;
      else params.location = tutor.state;
      const res = await API.tutors(params);
      const others = (res.items || []).filter((t) => t.id !== tutor.id).slice(0, 3);
      host.innerHTML = "";
      if (!others.length) {
        host.innerHTML = '<p class="muted small">No similar tutors found yet.</p>';
        return;
      }
      others.forEach((other) => {
        const row = el("a", { href: "tutor-profile.html?id=" + other.id, class: "list-item", style: { padding: "11px", color: "inherit", display: "flex" } }, [
          UI.image(other.avatar_url, other.full_name, "thumb", other.full_name),
          el("div", { class: "main" }, [
            el("h4", { text: other.full_name }),
            el("div", { class: "meta" }, [
              el("span", { html: ic("geo-alt-fill") + " " + esc(other.city) + ", " + esc(other.state) }),
              el("span", { text: money(other.hourly_rate) }),
              el("span", { html: stars(other.rating, null, false) })
            ])
          ])
        ]);
        host.appendChild(row);
      });
    } catch (e) {
      host.innerHTML = '<p class="muted small">Could not load similar tutors.</p>';
    }
  }

  /* ------------------------------------------------------ booking modal -- */
  async function openBookingModal(presetDate, presetTime) {
    if (!API.isAuthenticated()) {
      location.href = "login.html?next=" + encodeURIComponent("tutor-profile.html?id=" + tutor.id + "&book=1");
      return;
    }
    if (API.role() === "tutor") {
      toastInfo("Sign in with a student or parent account to request sessions.", "Student account needed");
      return;
    }
    if (API.role() === "admin") {
      toastInfo("Admin accounts cannot send booking requests.", "Not available");
      return;
    }
    if (tutor.approval_status !== "approved" || !tutor.is_visible) {
      toastError("This tutor is not accepting requests right now.");
      return;
    }

    const subjects = tutor.subjects || [];
    if (!subjects.length) {
      toastError("This tutor has not published any subjects, so a request cannot be created.");
      return;
    }

    const body = el("div", {});
    body.innerHTML =
      '<div id="bookError"></div>' +
      '<label class="field"><span class="label">Subject <span class="req">*</span></span>' +
        '<select class="select" name="subject_id" id="bk-subject"></select><span class="field-error"></span></label>' +
      '<div class="field"><span class="label">Choose a date <span class="req">*</span></span>' +
        '<div class="date-strip" id="bk-dates"></div><span class="field-error"></span></div>' +
      '<div class="field"><span class="label">Choose a start time <span class="req">*</span></span>' +
        '<div class="row-wrap" id="bk-times"></div>' +
        '<div class="hint" id="bk-times-hint">Select a date to see real open slots.</div><span class="field-error"></span></div>' +
      '<div class="field-row">' +
        '<label class="field"><span class="label">Session length</span>' +
          '<select class="select" name="duration_minutes" id="bk-duration"></select></label>' +
        '<label class="field"><span class="label">Teaching mode <span class="req">*</span></span>' +
          '<select class="select" name="mode" id="bk-mode"></select></label>' +
      '</div>' +
      '<label class="field"><span class="label">Your budget for this session (₦) <span class="req">*</span></span>' +
        '<input class="input" type="number" name="budget" id="bk-budget" min="0" step="100" />' +
        '<div class="hint" id="bk-budget-hint"></div><span class="field-error"></span></label>' +
      '<label class="field"><span class="label">Message to the tutor</span>' +
        '<textarea class="textarea" name="message" id="bk-message" rows="3" maxlength="1500" ' +
        'placeholder="Introduce yourself, the class/level, and what you want to achieve."></textarea></label>' +
      '<label class="field"><span class="label">Location / meeting note</span>' +
        '<input class="input" type="text" name="location_note" id="bk-location" maxlength="255" placeholder="e.g. Online via Google Meet, or my home in Yaba" /></label>' +
      '<label class="check"><input type="checkbox" id="bk-ignore" />' +
        '<span>Request a time outside the tutor’s listed availability (they can still decline)</span></label>';

    bookingModal = UI.modal({
      title: "Request a session with " + tutor.full_name,
      subtitle: money(tutor.hourly_rate) + " per " + (tutor.session_duration_minutes || 60) + " minutes · " + tutor.city + ", " + tutor.state,
      body, wide: true,
      buttons: [
        { label: "Cancel", class: "btn-outline", onClick: (b, bb, close) => close() },
        { label: "Send request", class: "btn-primary", onClick: (btn, bb, close) => submitBooking(btn, close) }
      ]
    });

    /* subjects (subject emojis are kept on purpose) */
    const subjectSelect = document.getElementById("bk-subject");
    subjects.forEach((s) => subjectSelect.appendChild(el("option", { value: String(s.id) }, (s.icon && String(s.icon).indexOf("bi-") !== 0 ? s.icon + " " : "") + s.name)));

    /* durations */
    const durationSelect = document.getElementById("bk-duration");
    const base = tutor.session_duration_minutes || 60;
    [30, 45, 60, 90, 120].filter((d) => d >= 15).forEach((d) =>
      durationSelect.appendChild(el("option", { value: String(d), selected: d === base }, d + " minutes")));
    durationSelect.value = String(base);
    durationSelect.addEventListener("change", () => { renderTimes(); updateBudgetHint(); });

    /* mode */
    const modeSelect = document.getElementById("bk-mode");
    if (tutor.accepts_in_person && tutor.accepts_online) {
      modeSelect.appendChild(el("option", { value: "hybrid" }, "Online & in person (tutor's choice)"));
      modeSelect.appendChild(el("option", { value: "online" }, "Online"));
      modeSelect.appendChild(el("option", { value: "in_person" }, "In person"));
    } else if (tutor.accepts_online) {
      modeSelect.appendChild(el("option", { value: "online" }, "Online"));
    } else {
      modeSelect.appendChild(el("option", { value: "in_person" }, "In person"));
    }

    /* budget */
    const budgetInput = document.getElementById("bk-budget");
    const setBudget = () => {
      const minutes = Number(durationSelect.value || base);
      budgetInput.value = String(Math.round((Number(tutor.hourly_rate) * minutes) / 60));
      updateBudgetHint();
    };
    function updateBudgetHint() {
      const minutes = Number(durationSelect.value || base);
      const suggested = Math.round((Number(tutor.hourly_rate) * minutes) / 60);
      document.getElementById("bk-budget-hint").textContent =
        "Tutor's rate suggests " + money(suggested) + " for " + minutes + " minutes.";
    }
    setBudget();

    /* dates + live open slots */
    openSlotsCache = {};
    selectedDate = null; selectedTime = null;
    try {
      const data = await API.openSlots(tutor.id, { days: 10 });
      const datesHost = document.getElementById("bk-dates");
      data.days.forEach((day) => {
        openSlotsCache[day.date] = day;
        const d = new Date(day.date + "T00:00:00");
        const chip = el("button", {
          class: "date-chip", type: "button", "data-date": day.date,
          title: day.slots.length + " open slot(s)"
        }, [
          el("div", { class: "dow", text: day.day_of_week.slice(0, 3) }),
          el("div", { class: "d", text: String(d.getDate()) }),
          el("div", { class: "m", text: d.toLocaleDateString("en-GB", { month: "short" }) }),
          el("div", { class: "tiny", style: { marginTop: "3px", color: day.slots.length ? "var(--green)" : "var(--text-faint)" },
            text: day.slots.length ? day.slots.length + " free" : "full" })
        ]);
        chip.addEventListener("click", () => {
          selectedDate = day.date; selectedTime = null;
          datesHost.querySelectorAll(".date-chip").forEach((c) => c.classList.toggle("active", c.dataset.date === day.date));
          renderTimes();
        });
        datesHost.appendChild(chip);
      });

      if (presetDate && openSlotsCache[presetDate]) {
        const chip = datesHost.querySelector('[data-date="' + presetDate + '"]');
        if (chip) chip.click();
        if (presetTime) {
          setTimeout(() => {
            const timeBtn = document.querySelector('#bk-times [data-time="' + presetTime + '"]');
            if (timeBtn) timeBtn.click();
          }, 60);
        }
      } else {
        const firstOpen = data.days.find((d) => d.slots.length);
        if (firstOpen) {
          const chip = datesHost.querySelector('[data-date="' + firstOpen.date + '"]');
          if (chip) chip.click();
        }
      }
    } catch (err) {
      document.getElementById("bk-times-hint").textContent = "Could not load live availability: " + err.message;
    }

    function renderTimes() {
      const host = document.getElementById("bk-times");
      const hint = document.getElementById("bk-times-hint");
      host.innerHTML = "";
      if (!selectedDate) { hint.textContent = "Select a date to see real open slots."; return; }
      const day = openSlotsCache[selectedDate];
      if (!day) { hint.textContent = "No availability data for that date."; return; }
      const ignore = document.getElementById("bk-ignore").checked;

      if (!day.slots.length && !ignore) {
        hint.textContent = "No open slots on " + formatDayDate(selectedDate) +
          ". Tick “request outside availability” below to propose your own time.";
        const manual = el("input", { class: "input", type: "time", step: "900", style: { maxWidth: "180px" }, "data-time": "manual" });
        manual.addEventListener("change", () => { selectedTime = manual.value || null; });
        host.appendChild(manual);
        return;
      }

      day.slots.forEach((slot) => {
        const btn = el("button", {
          class: "slot-pill open" + (slot.held ? " held" : ""),
          type: "button",
          "data-time": slot.start_time,
          title: slot.held ? "Another student already requested this time — the tutor may decline." : ""
        }, slot.label);
        btn.addEventListener("click", () => {
          selectedTime = slot.start_time;
          host.querySelectorAll(".slot-pill").forEach((b) => b.classList.toggle("booked", false));
          host.querySelectorAll(".slot-pill").forEach((b) => b.style.background = "");
          btn.classList.remove("open");
          btn.style.background = "var(--ink-900)";
          btn.style.color = "#fff";
          host.querySelectorAll(".slot-pill").forEach((b) => { if (b !== btn) { b.style.background = ""; b.style.color = ""; } });
          hint.textContent = "Selected " + slot.label + " on " + formatDayDate(selectedDate) + " · " + slot.mode_label;
        });
        host.appendChild(btn);
      });

      const manual = el("input", { class: "input", type: "time", step: "900", style: { maxWidth: "170px" }, title: "Or pick a custom time" });
      manual.addEventListener("change", () => {
        if (manual.value) {
          selectedTime = manual.value;
          host.querySelectorAll(".slot-pill").forEach((b) => { b.style.background = ""; b.style.color = ""; });
          hint.textContent = "Custom time selected: " + to12h(manual.value) + " — make sure “request outside availability” is ticked if it is not listed.";
        }
      });
      host.appendChild(manual);
      hint.textContent = day.slots.length
        ? day.slots.length + " real open slot(s) on " + formatDayDate(selectedDate) + ". Booked times are already removed."
        : hint.textContent;
    }

    document.getElementById("bk-ignore").addEventListener("change", () => renderTimes());
    window._bkRenderTimes = renderTimes;
  }

  async function submitBooking(button, close) {
    const errorHost = document.getElementById("bookError");
    errorHost.innerHTML = "";
    UI.showFieldErrors(button.closest(".modal").querySelector(".modal-body"), []);

    const subjectId = Number(document.getElementById("bk-subject").value);
    const duration = Number(document.getElementById("bk-duration").value);
    const mode = document.getElementById("bk-mode").value;
    const budget = Number(document.getElementById("bk-budget").value);
    const message = document.getElementById("bk-message").value.trim();
    const locationNote = document.getElementById("bk-location").value.trim();
    const ignore = document.getElementById("bk-ignore").checked;

    if (!selectedDate) {
      errorHost.innerHTML = '<div class="error-box"><span class="ico">' + WARN + '</span><div>Please choose a date for your session.</div></div>';
      return;
    }
    if (!selectedTime) {
      errorHost.innerHTML = '<div class="error-box"><span class="ico">' + WARN + '</span><div>Please choose a start time.</div></div>';
      return;
    }
    if (!budget || budget <= 0) {
      errorHost.innerHTML = '<div class="error-box"><span class="ico">' + WARN + '</span><div>Please enter your budget for this session.</div></div>';
      return;
    }

    UI.setLoading(button, true, "Sending request…");
    try {
      const res = await API.createRequest({
        tutor_id: tutor.id,
        subject_id: subjectId,
        preferred_date: selectedDate,
        preferred_time: selectedTime,
        duration_minutes: duration,
        mode, budget,
        message: message || null,
        location_note: locationNote || null,
        ignore_availability: ignore
      });
      close();
      toastSuccess(res.detail, "Request sent");
      setTimeout(() => { location.href = "dashboard.html?view=requests"; }, 1200);
    } catch (err) {
      UI.setLoading(button, false);
      const detail = '<div class="error-box"><span class="ico">' + WARN + '</span><div><strong>' +
        esc(err.message) + "</strong>" +
        (err.errors && err.errors.length
          ? "<ul>" + err.errors.map((e) => "<li>" + esc(e.field) + ": " + esc(e.message) + "</li>").join("") + "</ul>"
          : "") + "</div></div>";
      errorHost.innerHTML = detail;
      if (err.status === 409 && /not available/i.test(err.message)) {
        document.getElementById("bk-ignore").checked = true;
        window._bkRenderTimes && window._bkRenderTimes();
      }
      toastError(err.message, "Request not sent");
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();