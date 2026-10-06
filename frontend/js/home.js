/* ==========================================================================
   home.js — landing page. Every number, subject, tutor card and review on this
   page is fetched from the API (i.e. straight from the database).
   ========================================================================== */
(function () {
  "use strict";

  const { esc, money, stars, el, relativeDate, toastError } = UI;

  async function init() {
    const ok = await App.boot();
    if (!ok) return;

    const skeletonHost = document.getElementById("featuredSkeleton");
    if (skeletonHost) skeletonHost.innerHTML = UI.skeletonTutorCards(3);

    await Promise.all([loadFacets(), loadFeatured(), loadTestimonials()]);
  }

  /* ------------------------------------------------------- hero search --- */
  async function loadFacets() {
    try {
      const facets = await API.tutorFacets();

      const subjectSelect = document.getElementById("heroSubject");
      (facets.subjects || [])
        .filter((s) => s.tutor_count > 0)
        .forEach((s) => {
          subjectSelect.appendChild(
            el("option", { value: String(s.id) }, (s.icon && String(s.icon).indexOf("bi-") !== 0 ? s.icon + "  " : "") + s.name + " (" + s.tutor_count + ")")
          );
        });

      const daySelect = document.getElementById("heroDay");
      (facets.days || []).forEach((day) => daySelect.appendChild(el("option", { value: day }, day)));

      // live trust stats
      await fillTrustStats(facets);

      // subject tiles
      const grid = document.getElementById("subjectGrid");
      const popular = (facets.subjects || []).filter((s) => s.tutor_count > 0).slice(0, 12);
      grid.innerHTML = "";
      popular.forEach((subject) => {
        const tile = el("a", {
          class: "subject-tile",
          href: "tutors.html?subject_id=" + subject.id
        }, [
          el("span", { class: "emoji", html: subject.icon ? UI.subjectIcon(subject.icon) : '<i class="bi bi-book"></i>' }),
          el("span", {}, [
            el("strong", { text: subject.name }),
            el("span", { text: UI.plural(subject.tutor_count, "tutor") })
          ])
        ]);
        grid.appendChild(tile);
      });
      if (!popular.length) {
        grid.innerHTML = UI.emptyState({
          icon: '<i class="bi bi-journal-bookmark"></i>',
          title: "No subjects published yet",
          message: "Once tutors create profiles, their subjects appear here automatically."
        });
      }
    } catch (err) {
      toastError(err.message, "Could not load filters");
    }
  }

  async function loadStats() {
    try {
      await fillTrustStats(await API.tutorFacets());
    } catch (e) { /* placeholders stay when the API is unreachable */ }
  }

  /* Fill the four hero trust stats from real database rows. */
  async function fillTrustStats(facets) {
    setText("statTutors", String(facets.total_tutors || 0));
    setText("statSubjects", String((facets.subjects || []).filter((s) => s.tutor_count > 0).length));
    try {
      const res = await API.tutors({ page_size: 100 });
      const items = res.items || [];
      const sessions = items.reduce((s, t) => s + (t.completed_sessions || 0), 0);
      const rated = items.map((t) => t.rating).filter((r) => typeof r === "number" && r > 0);
      setText("statSessions", String(sessions));
      setHtml("statRating", rated.length
        ? (rated.reduce((a, b) => a + b, 0) / rated.length).toFixed(1) + ' <i class="bi bi-star-fill"></i>'
        : "–");
    } catch (e) { /* leave placeholders when the API is unreachable */ }
  }

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function setHtml(id, value) {
    const node = document.getElementById(id);
    if (node) node.innerHTML = value;
  }

  /* ------------------------------------------------------ featured tutors */
  async function loadFeatured() {
    const host = document.getElementById("featuredTutors");
    try {
      const res = await API.tutors({ sort: "rating", page_size: 6 });
      const tutors = res.items || [];

      // sessions counter comes from the tutors payload
      const sessions = tutors.reduce((sum, t) => sum + (t.completed_sessions || 0), 0);
      const rated = tutors.filter((t) => t.review_count > 0);
      const avg = rated.length
        ? rated.reduce((sum, t) => sum + t.rating, 0) / rated.length
        : 0;
      setText("statSessions", sessions ? String(sessions) + "+" : String(tutors.length));
      setHtml("statRating", avg ? avg.toFixed(1) + ' <i class="bi bi-star-fill"></i>' : "–");

      if (!tutors.length) {
        host.innerHTML = UI.emptyState({
          icon: '<i class="bi bi-mortarboard"></i>',
          title: "No tutors published yet",
          message: "Be the first — create a tutor profile and you will appear here instantly.",
          actionLabel: "Become a tutor",
          actionHref: "register.html?role=tutor"
        });
        return;
      }
      App.renderTutorGrid(host, tutors, { showFavorite: false });
    } catch (err) {
      host.innerHTML = UI.errorState(err.message, "Retry");
      const retry = host.querySelector("[data-retry]");
      if (retry) retry.addEventListener("click", loadFeatured);
    }
  }

  /* -------------------------------------------------------- testimonials */
  async function loadTestimonials() {
    const host = document.getElementById("testimonialGrid");
    try {
      const res = await API.tutors({ sort: "rating", page_size: 8, min_rating: 1 });
      const tutors = (res.items || []).filter((t) => t.review_count > 0).slice(0, 3);

      const collected = [];
      for (const tutor of tutors) {
        try {
          const detail = await API.tutor(tutor.id);
          const review = (detail.reviews || [])[0];
          if (review) collected.push({ review, tutor: detail });
        } catch (e) { /* skip */ }
        if (collected.length >= 3) break;
      }

      host.innerHTML = "";
      if (!collected.length) {
        host.innerHTML = UI.emptyState({
          icon: '<i class="bi bi-star-fill"></i>',
          title: "No reviews yet",
          message: "Reviews appear here as soon as students complete their first sessions."
        });
        return;
      }

      collected.forEach(({ review, tutor }) => {
        const card = el("div", { class: "quote" }, [
          el("div", { class: "mark", text: "“" }),
          el("div", { html: stars(review.rating) }),
          el("p", { text: review.comment || review.title || "" }),
          el("div", { class: "who" })
        ]);
        const who = card.querySelector(".who");
        who.appendChild(UI.image(review.student_avatar_url, review.student_name, "", review.student_name));
        who.appendChild(el("div", {}, [
          el("strong", { text: review.student_name }),
          el("span", { text: (review.subject_name || tutor.headline) + " · with " + tutor.full_name })
        ]));
        host.appendChild(card);
      });
    } catch (err) {
      host.innerHTML = UI.errorState(err.message, "Retry");
    }
  }

  /* ------------------------------------------------------------ binding -- */
  document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("heroSearch");
    if (form) {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const data = new FormData(form);
        const params = {};
        data.forEach((value, key) => { if (value) params[key] = value; });
        const usp = new URLSearchParams(params).toString();
        location.href = "tutors.html" + (usp ? "?" + usp : "");
      });
    }
    init();
  });
})();