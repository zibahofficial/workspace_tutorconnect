/* ==========================================================================
   tutors.js — search & discovery. Builds real query strings against
   GET /api/tutors and renders live database results.
   ========================================================================== */
(function () {
  "use strict";

  const { esc, money, el, debounce, toastError } = UI;

  const state = {
    q: "", subject_id: "", location: "", mode: "",
    min_price: "", max_price: "", min_experience: "",
    day: "", start_after: "", end_before: "", available_today: false,
    min_rating: "", verified_only: false, sort: "relevance",
    page: 1, page_size: 12
  };

  const els = {};
  let facets = null;
  let suppressSync = false;

  /* ------------------------------------------------------------- setup --- */
  function cacheEls() {
    ["f-q", "f-subject_id", "f-location", "f-mode", "f-min_price", "f-max_price",
     "f-price-range", "f-start_after", "f-end_before", "f-available_today",
     "f-verified_only", "f-sort", "topQ", "topQClear", "results", "skeleton",
     "resultCount", "activeChips", "activeSummary", "paginationHost", "resetFilters",
     "dayGrid", "expTabs", "ratingTabs", "cityList", "priceRangeLabel", "mobileFilters", "filters"]
      .forEach((id) => { els[id] = document.getElementById(id); });
  }

  function readInitialState() {
    const params = UI.readQueryParams();
    Object.keys(state).forEach((key) => {
      if (params[key] !== undefined) {
        if (key === "available_today" || key === "verified_only") state[key] = params[key] === "true" || params[key] === "1";
        else if (key === "page" || key === "page_size") state[key] = Number(params[key]) || state[key];
        else state[key] = params[key];
      }
    });
  }

  function pushStateToInputs() {
    suppressSync = true;
    els["f-q"].value = state.q;
    els["topQ"].value = state.q;
    els["f-subject_id"].value = state.subject_id;
    els["f-location"].value = state.location;
    els["f-mode"].value = state.mode;
    els["f-min_price"].value = state.min_price;
    els["f-max_price"].value = state.max_price;
    els["f-start_after"].value = state.start_after;
    els["f-end_before"].value = state.end_before;
    els["f-available_today"].checked = !!state.available_today;
    els["f-verified_only"].checked = !!state.verified_only;
    els["f-sort"].value = state.sort || "relevance";
    const rangeValue = state.max_price ? Math.min(Number(state.max_price), Number(els["f-price-range"].max)) : Number(els["f-price-range"].max);
    els["f-price-range"].value = String(rangeValue);
    updateRangeLabel();
    syncTabs();
    syncDays();
    els["topQClear"].classList.toggle("show", !!state.q);
    suppressSync = false;
  }

  function syncTabs() {
    els.expTabs.querySelectorAll(".pill-tab").forEach((b) =>
      b.classList.toggle("active", String(b.dataset.min || "") === String(state.min_experience || "")));
    els.ratingTabs.querySelectorAll(".pill-tab").forEach((b) =>
      b.classList.toggle("active", String(b.dataset.rating || "") === String(state.min_rating || "")));
  }

  function syncDays() {
    els.dayGrid.querySelectorAll(".day-btn").forEach((b) =>
      b.classList.toggle("active", b.dataset.day === state.day));
  }

  function updateRangeLabel() {
    const value = Number(els["f-price-range"].value);
    const max = Number(els["f-price-range"].max);
    els.priceRangeLabel.textContent = value >= max ? "Any budget" : "Up to " + money(value);
  }

  function writeUrl() {
    const params = {};
    Object.keys(state).forEach((key) => {
      const value = state[key];
      if (value === "" || value === false || value === null || value === undefined) return;
      if (key === "page" && Number(value) === 1) return;
      if (key === "page_size" && Number(value) === 12) return;
      params[key] = value;
    });
    UI.writeQueryParams(params, true);
  }

  /* ---------------------------------------------------------- facets ----- */
  async function loadFacets() {
    try {
      facets = await API.tutorFacets();
      const select = els["f-subject_id"];
      /* subject emoji (s.icon) kept on purpose */
      (facets.subjects || [])
        .filter((s) => s.tutor_count > 0)
        .forEach((s) => select.appendChild(el("option", { value: String(s.id) },
          (s.icon && String(s.icon).indexOf("bi-") !== 0 ? s.icon + " " : "") + s.name + " (" + s.tutor_count + ")")));
      select.value = state.subject_id;

      const cities = new Set();
      (facets.cities || []).forEach((c) => cities.add(c));
      (facets.states || []).forEach((c) => cities.add(c));
      els.cityList.innerHTML = "";
      Array.from(cities).sort().forEach((c) => els.cityList.appendChild(el("option", { value: c })));

      const price = facets.price || {};
      if (price.max) {
        const roundedMax = Math.ceil(price.max / 500) * 500;
        els["f-price-range"].max = String(Math.max(roundedMax, 10000));
      }

      els.dayGrid.innerHTML = "";
      (facets.days || []).forEach((day) => {
        const btn = el("button", { type: "button", class: "day-btn", "data-day": day, title: day },
          day.slice(0, 3));
        btn.addEventListener("click", () => {
          state.day = state.day === day ? "" : day;
          state.page = 1;
          syncDays();
          apply();
        });
        els.dayGrid.appendChild(btn);
      });
      syncDays();
    } catch (err) {
      toastError(err.message, "Filters unavailable");
    }
  }

  /* ----------------------------------------------------------- search ---- */
  function buildQuery() {
    const q = {};
    Object.keys(state).forEach((key) => {
      const value = state[key];
      if (value === "" || value === false || value === null || value === undefined) return;
      q[key] = value;
    });
    return q;
  }

  function renderChips() {
    const chips = [];
    if (state.q) chips.push({ key: "q", label: "“" + state.q + "”" });
    if (state.subject_id && facets) {
      const subject = (facets.subjects || []).find((s) => String(s.id) === String(state.subject_id));
      if (subject) chips.push({ key: "subject_id", label: subject.name });
    }
    if (state.location) chips.push({ key: "location", icon: "geo-alt-fill", label: state.location });
    if (state.mode) chips.push({ key: "mode", label: UI.MODE_LABELS[state.mode] || state.mode });
    if (state.min_price) chips.push({ key: "min_price", label: "Min " + money(state.min_price) });
    if (state.max_price) chips.push({ key: "max_price", label: "Max " + money(state.max_price) });
    if (state.min_experience) chips.push({ key: "min_experience", label: state.min_experience + "+ years experience" });
    if (state.day) chips.push({ key: "day", icon: "calendar3", label: state.day });
    if (state.start_after) chips.push({ key: "start_after", label: "From " + UI.to12h(state.start_after) });
    if (state.end_before) chips.push({ key: "end_before", label: "Until " + UI.to12h(state.end_before) });
    if (state.available_today) chips.push({ key: "available_today", label: "Available today" });
    if (state.min_rating) chips.push({ key: "min_rating", icon: "star-fill", label: state.min_rating + " and up" });
    if (state.verified_only) chips.push({ key: "verified_only", icon: "patch-check-fill", label: "Verified only" });

    els.activeChips.innerHTML = "";
    if (!chips.length) return;
    chips.forEach((chip) => {
      const node = el("span", { class: "chip" });
      if (chip.icon) node.innerHTML = '<i class="bi bi-' + chip.icon + '"></i> ';
      node.appendChild(document.createTextNode(chip.label));
      const btn = el("button", { type: "button", "aria-label": "Remove filter " + chip.label }, "×");
      btn.addEventListener("click", () => {
        if (chip.key === "available_today" || chip.key === "verified_only") state[chip.key] = false;
        else state[chip.key] = "";
        if (chip.key === "max_price") els["f-price-range"].value = els["f-price-range"].max;
        state.page = 1;
        pushStateToInputs();
        apply();
      });
      node.appendChild(btn);
      els.activeChips.appendChild(node);
    });
  }

  function summarise(total, res) {
    const parts = [];
    if (state.q) parts.push("“" + state.q + "”");
    if (state.location) parts.push("in " + state.location);
    if (state.min_price || state.max_price) {
      parts.push((state.min_price ? money(state.min_price) : "₦0") + "–" + (state.max_price ? money(state.max_price) : "any"));
    }
    els.activeSummary.textContent = parts.length ? "Filters: " + parts.join(" · ") : "";
    els.resultCount.innerHTML = total
      ? "<strong>" + total + "</strong> " + (total === 1 ? "tutor" : "tutors") + " found" +
        (res.pages > 1 ? " · page " + res.page + " of " + res.pages : "")
      : "<strong>0</strong> tutors match those filters";
  }

  async function runSearch() {
    els.results.innerHTML = '<div class="tutor-grid">' + UI.skeletonTutorCards(6) + "</div>";
    els.paginationHost.innerHTML = "";
    try {
      const res = await API.tutors(buildQuery());
      const tutors = res.items || [];
      summarise(res.total || 0, res);
      renderChips();

      if (!tutors.length) {
        els.results.innerHTML = UI.emptyState({
          icon: '<i class="bi bi-search"></i>',
          title: "No tutors match those filters",
          message: "Try widening your budget, removing the day filter, or searching a nearby city. New tutors join every week.",
          actionLabel: "Reset all filters",
          actionHref: "tutors.html"
        });
        const reset = els.results.querySelector("a");
        if (reset) reset.addEventListener("click", (e) => { e.preventDefault(); resetAll(); });
        return;
      }

      App.renderTutorGrid(els.results, tutors, {});

      const pager = UI.pagination(res.page, res.pages, (target) => {
        state.page = target;
        pushStateToInputs();
        apply();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
      if (pager) els.paginationHost.appendChild(pager);
    } catch (err) {
      els.resultCount.textContent = "Search failed";
      els.results.innerHTML = UI.errorState(err.message, "Try again");
      const retry = els.results.querySelector("[data-retry]");
      if (retry) retry.addEventListener("click", runSearch);
      toastError(err.message, "Search failed");
    }
  }

  const apply = debounce(() => {
    writeUrl();
    runSearch();
  }, 260);

  function applyNow() {
    writeUrl();
    runSearch();
  }

  function resetAll() {
    Object.keys(state).forEach((key) => {
      if (key === "page") state[key] = 1;
      else if (key === "page_size") state[key] = 12;
      else if (key === "sort") state[key] = "relevance";
      else if (key === "available_today" || key === "verified_only") state[key] = false;
      else state[key] = "";
    });
    pushStateToInputs();
    applyNow();
  }

  /* ------------------------------------------------------------ wiring --- */
  function bindEvents() {
    const onInput = (key, transform) => (event) => {
      const value = transform ? transform(event.target.value) : event.target.value.trim();
      state[key] = value;
      state.page = 1;
      apply();
    };

    els["f-q"].addEventListener("input", debounce(onInput("q"), 320));
    els["topQ"].addEventListener("input", debounce((e) => {
      els["topQClear"].classList.toggle("show", !!e.target.value);
      els["f-q"].value = e.target.value;
      state.q = e.target.value.trim();
      state.page = 1;
      apply();
    }, 320));
    els["topQClear"].addEventListener("click", () => {
      els["topQ"].value = ""; els["f-q"].value = "";
      els["topQClear"].classList.remove("show");
      state.q = ""; state.page = 1; apply();
      els["topQ"].focus();
    });

    ["f-subject_id", "f-location", "f-mode", "f-min_price", "f-max_price", "f-start_after", "f-end_before"]
      .forEach((id) => {
        const key = id.replace("f-", "");
        const node = els[id];
        const handler = node.tagName === "SELECT" ? "change" : "input";
        node.addEventListener(handler, debounce(onInput(key), handler === "change" ? 0 : 320));
      });

    els["f-price-range"].addEventListener("input", () => {
      updateRangeLabel();
      const value = Number(els["f-price-range"].value);
      const max = Number(els["f-price-range"].max);
      state.max_price = value >= max ? "" : String(value);
      els["f-max_price"].value = state.max_price;
      state.page = 1;
      apply();
    });

    els["f-available_today"].addEventListener("change", (e) => {
      state.available_today = e.target.checked; state.page = 1; apply();
    });
    els["f-verified_only"].addEventListener("change", (e) => {
      state.verified_only = e.target.checked; state.page = 1; apply();
    });
    els["f-sort"].addEventListener("change", (e) => {
      state.sort = e.target.value; state.page = 1; applyNow();
    });

    els.expTabs.querySelectorAll(".pill-tab").forEach((btn) =>
      btn.addEventListener("click", () => {
        state.min_experience = btn.dataset.min || ""; state.page = 1; syncTabs(); apply();
      }));
    els.ratingTabs.querySelectorAll(".pill-tab").forEach((btn) =>
      btn.addEventListener("click", () => {
        state.min_rating = btn.dataset.rating || ""; state.page = 1; syncTabs(); apply();
      }));

    els.resetFilters.addEventListener("click", resetAll);

    // mobile filter toggle
    const mq = window.matchMedia("(max-width: 940px)");
    const applyMq = () => {
      els.mobileFilters.style.display = mq.matches ? "inline-flex" : "none";
      els.filters.classList.toggle("collapsed", mq.matches);
    };
    applyMq();
    mq.addEventListener ? mq.addEventListener("change", applyMq) : mq.addListener(applyMq);
    els.mobileFilters.addEventListener("click", () => {
      const collapsed = els.filters.classList.toggle("collapsed");
      els.mobileFilters.innerHTML = collapsed
        ? '<i class="bi bi-sliders"></i> Show filters'
        : '<i class="bi bi-sliders"></i> Hide filters';
    });
  }

  /* -------------------------------------------------------------- init --- */
  async function init() {
    const ok = await App.boot();
    if (!ok) return;
    cacheEls();
    readInitialState();
    bindEvents();
    await loadFacets();
    pushStateToInputs();
    applyNow();
  }

  document.addEventListener("DOMContentLoaded", init);
})();