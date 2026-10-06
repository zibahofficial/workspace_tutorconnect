/* ==========================================================================
   app.js — app shell: bootstrap, route guards, shared tutor card renderer.
   ========================================================================== */
(function (global) {
  "use strict";

  const { esc, money, stars, initials, image, el, toastInfo, toastSuccess, toastError,
          MODE_LABELS, relativeDate } = UI;

  /* icon helper: ic("search") -> <i class="bi bi-search"></i> */
  const ic = (name) => '<i class="bi bi-' + name + '"></i>';

  /* ------------------------------------------------------------- boot ---- */
  async function boot(options) {
    options = options || {};
    await UI.loadConfig();
    if (options.requireAuth) {
      if (!requireAuth(options.roles)) return false;
    }
    UI.buildNav();
    UI.buildFooter();
    syncNotificationBell();
    document.body.classList.remove("loading");
    return true;
  }

  function requireAuth(roles) {
    if (!API.isAuthenticated()) {
      const next = encodeURIComponent(location.pathname.split("/").pop() + location.search);
      location.replace("login.html?next=" + next);
      return false;
    }
    if (roles && roles.length && roles.indexOf(API.role()) === -1) {
      location.replace("dashboard.html");
      return false;
    }
    return true;
  }

  /** Keep the bell badge fresh while the user is on the page. */
  function syncNotificationBell() {
    if (!API.isAuthenticated()) return;
    global._tmRefreshBell && global._tmRefreshBell();
    if (global._tmBellTimer) clearInterval(global._tmBellTimer);
    global._tmBellTimer = setInterval(() => {
      global._tmRefreshBell && global._tmRefreshBell();
    }, 45000);
  }

  global.addEventListener("tm:unauthorized", () => {
    toastInfo("Your session expired. Please sign in again.", "Session ended");
    setTimeout(() => location.replace("login.html"), 1200);
  });

  /* -------------------------------------------------------- tutor card --- */
  /* subject emojis (s.icon) are kept on purpose */
  function subjectChips(tutor, limit) {
    const subjects = (tutor.subjects || []).slice(0, limit || 2);
    let html = subjects.map((s) => '<span class="tag">' + UI.subjectIcon(s.icon) + " " + esc(s.name) + "</span>").join("");
    const extra = (tutor.subjects || []).length - subjects.length;
    if (extra > 0) html += '<span class="tag tag-primary">+' + extra + " more</span>";
    return html || '<span class="tag">General</span>';
  }

  function availabilitySummary(tutor) {
    const slots = (tutor.availability || []).filter((s) => s.is_active);
    if (!slots.length) {
      return '<span class="dot off"></span> No availability published yet';
    }
    const days = [];
    slots.forEach((s) => { if (days.indexOf(s.day_of_week.slice(0, 3)) === -1) days.push(s.day_of_week.slice(0, 3)); });
    const label = days.length > 3 ? days.slice(0, 3).join(", ") + " +" + (days.length - 3) : days.join(", ");
    return '<span class="dot"></span> Available ' + esc(label) + " · " + slots.length + " slot" + (slots.length === 1 ? "" : "s");
  }

  function tutorCard(tutor, options) {
    options = options || {};
    const cover = tutor.cover_image_url ||
      "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=900&q=80";
    const ratingHtml = tutor.review_count
      ? stars(tutor.rating, tutor.review_count)
      : '<span class="badge badge-outline">New tutor</span>';

    const card = el("article", { class: "tutor-card" });
    card.innerHTML =
      '<div class="tutor-media">' +
        '<div class="cover" style="width:100%;height:100%"></div>' +
        '<div class="top">' +
          (tutor.verified ? '<span class="badge badge-verified">' + ic("patch-check-fill") + ' Verified</span>' : '<span class="badge" style="background:rgba(255,255,255,.9)">Unverified</span>') +
          (tutor.match_score ? '<span class="badge" style="background:rgba(11,17,32,.72);color:#a5b4fc">' + tutor.match_score + '% match</span>' : "") +
        "</div>" +
        '<div class="overlay">' +
          '<div class="price">' + money(tutor.hourly_rate) + ' <small>/ ' + (tutor.session_duration_minutes || 60) + " min session</small></div>" +
        "</div>" +
      "</div>" +
      '<div class="tutor-body">' +
        '<div class="tutor-id">' +
          '<div class="avatar-slot"></div>' +
          "<div>" +
            "<h3>" + esc(tutor.full_name) + "</h3>" +
            '<div class="where">' + ic("geo-alt-fill") + " " + esc(tutor.city) + ", " + esc(tutor.state) + "</div>" +
          "</div>" +
        "</div>" +
        '<p class="tutor-headline">' + esc(tutor.headline) + "</p>" +
        '<div class="tutor-tags">' + subjectChips(tutor, 2) + "</div>" +
        '<div class="tutor-meta">' +
          "<div><span class='k'>" + (tutor.years_experience || 0) + "</span><span class='v'>Years exp</span></div>" +
          "<div><span class='k'>" + (tutor.completed_sessions || 0) + "</span><span class='v'>Sessions</span></div>" +
          "<div><span class='k'>" + (tutor.review_count || 0) + "</span><span class='v'>Reviews</span></div>" +
        "</div>" +
        '<div class="tutor-avail">' + availabilitySummary(tutor) + "</div>" +
        '<div class="row-between" style="gap:8px">' + ratingHtml +
          '<span class="badge badge-accent">' + esc(MODE_LABELS[tutor.teaching_mode] || "Hybrid") + "</span>" +
        "</div>" +
        '<div class="tutor-actions">' +
          '<a class="btn btn-outline btn-sm" href="tutor-profile.html?id=' + tutor.id + '">View profile</a>' +
          '<a class="btn btn-primary btn-sm" href="' + (options.bookHref || ("tutor-profile.html?id=" + tutor.id + "&book=1")) + '">' +
            (options.bookLabel || "Request session") + "</a>" +
        "</div>" +
      "</div>";

    // media with graceful fallback
    card.querySelector(".cover").appendChild(
      image(cover, tutor.full_name + " teaching", "", tutor.full_name)
    );
    const coverImg = card.querySelector(".cover img, .cover div");
    if (coverImg) { coverImg.style.width = "100%"; coverImg.style.height = "100%"; coverImg.style.objectFit = "cover"; }

    // avatar
    const avatarSlot = card.querySelector(".avatar-slot");
    const avatar = image(tutor.avatar_url, tutor.full_name, "avatar", tutor.full_name);
    avatarSlot.appendChild(avatar);

    // favourite heart
    if (options.showFavorite !== false) {
      const top = card.querySelector(".top");
      const fav = el("button", {
        class: "fav-btn" + (tutor.is_favorite ? " active" : ""),
        "aria-label": tutor.is_favorite ? "Remove from saved tutors" : "Save this tutor",
        title: tutor.is_favorite ? "Saved" : "Save tutor",
        type: "button",
        html: tutor.is_favorite ? '<i class="bi bi-heart-fill"></i>' : '<i class="bi bi-heart"></i>'
      });
      fav.addEventListener("click", async (e) => {
        e.preventDefault(); e.stopPropagation();
        if (!API.isAuthenticated()) { location.href = "login.html?next=" + encodeURIComponent("tutors.html"); return; }
        if (API.role() !== "student") { toastInfo("Only students and parents can save tutors."); return; }
        try {
          const res = await API.toggleFavorite(tutor.id);
          tutor.is_favorite = res.data.is_favorite;
          fav.classList.toggle("active", tutor.is_favorite);
          fav.innerHTML = tutor.is_favorite ? '<i class="bi bi-heart-fill"></i>' : '<i class="bi bi-heart"></i>';
          fav.title = tutor.is_favorite ? "Saved" : "Save tutor";
          toastSuccess(res.detail);
          if (options.onFavoriteChange) options.onFavoriteChange(tutor);
        } catch (err) { toastError(err.message); }
      });
      top.appendChild(fav);
    }

    card.addEventListener("click", (e) => {
      if (e.target.closest("a, button")) return;
      location.href = "tutor-profile.html?id=" + tutor.id;
    });
    card.style.cursor = "pointer";
    return card;
  }

  function renderTutorGrid(container, tutors, options) {
    container.innerHTML = "";
    const grid = el("div", { class: "tutor-grid" });
    tutors.forEach((t) => grid.appendChild(tutorCard(t, options)));
    container.appendChild(grid);
  }

  /* -------------------------------------------------- shared page helper -- */
  function pageHeader(title, subtitle, extraHtml) {
    return '<div class="page-head"><div class="container">' +
      (extraHtml || "") +
      "<h1>" + esc(title) + "</h1>" +
      (subtitle ? "<p>" + esc(subtitle) + "</p>" : "") +
      "</div></div>";
  }

  /** Resolve the three-way persona (student | tutor | parent | admin) for a user. */
  function personaFor(user) {
    if (!user) return "";
    if (user.persona) return user.persona;
    try {
      const all = JSON.parse(localStorage.getItem("tm_personas") || "{}");
      const known = user.email ? all[String(user.email).toLowerCase()] : null;
      if (known && known.persona) return known.persona;
    } catch (e) { /* ignore malformed storage */ }
    return user.role === "tutor" ? "tutor" : user.role === "admin" ? "admin" : "student";
  }

  function roleLabel(role, user) {
    if (user && personaFor(user) === "parent") return "Parent";
    return { tutor: "Tutor", student: "Student", parent: "Parent", admin: "Administrator" }[role] || role;
  }

  global.App = {
    boot, requireAuth, tutorCard, renderTutorGrid, subjectChips, availabilitySummary,
    pageHeader, roleLabel, personaFor, syncNotificationBell
  };
})(window);