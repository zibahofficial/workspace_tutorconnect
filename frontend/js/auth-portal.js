/* ==========================================================================
   auth-portal.js — logic for the ADD-ONLY auth pages:
       /login/   /signup/   /forgot-password/
   Talks to the live backend exclusively through the existing window.API
   client (js/api.js). It never modifies any existing module: it only reads
   API.* and stores two extra, namespaced localStorage keys used to remember
   the three-way role (student | tutor | parent) on the session user object.
   ========================================================================== */
(function (global) {
  "use strict";

  const PERSONAS_KEY = "tm_personas";        // { email: { persona, child_name } }
  const ROLE_PARAM = "next";

  /* ------------------------------------------------------------ storage -- */
  function readPersonas() {
    try { return JSON.parse(localStorage.getItem(PERSONAS_KEY) || "{}"); }
    catch (e) { return {}; }
  }

  function rememberPersona(email, persona, extra) {
    if (!email) return;
    const all = readPersonas();
    all[String(email).toLowerCase()] = Object.assign({ persona: persona }, extra || {});
    try { localStorage.setItem(PERSONAS_KEY, JSON.stringify(all)); } catch (e) {}
  }

  function knownPersona(email) {
    const entry = readPersonas()[String(email || "").toLowerCase()];
    return entry || null;
  }

  /* Attach the three-way role to the stored session user object so every
     other screen (and this portal) can read `user.account_role`. */
  function stampUser(user, persona, extra) {
    const stamped = Object.assign({}, user, extra || {});
    stamped.persona = persona || defaultPersona(user.role);
    stamped.account_role = stamped.persona;   // student | tutor | parent | admin
    API.store.user = stamped;
    return stamped;
  }

  function defaultPersona(role) {
    return role === "tutor" ? "tutor" : role === "admin" ? "admin" : "student";
  }

  /* ------------------------------------------------------------- routing -- */
  function nextUrl(fallback) {
    const raw = new URLSearchParams(location.search).get(ROLE_PARAM) || "";
    if (raw.startsWith("/") && !raw.startsWith("//")) return raw;
    return fallback;
  }

  function redirectFor(user) {
    switch (user.account_role || user.role) {
      case "tutor":  return nextUrl("/dashboard.html?view=overview");
      case "parent": return nextUrl("/dashboard.html?view=browse");
      case "admin":  return nextUrl("/dashboard.html?view=overview");
      default:       return nextUrl("/dashboard.html?view=overview");
    }
  }

  /* --------------------------------------------------------------- utils -- */
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function showBox(box, messages) {
    if (!box) return;
    box.innerHTML = messages.map((m) => "<div>" + UI.esc(m) + "</div>").join("");
    box.classList.add("show");
  }

  function clearFieldErrors(form) {
    $$(".ap-field-error", form).forEach((n) => n.remove());
    $$(".ap-input", form).forEach((n) => n.style.borderColor = "");
  }

  function paintFieldErrors(form, errors) {
    (errors || []).forEach((err) => {
      const field = err && err.field;
      if (!field) return;
      const input = form.querySelector('[name="' + field + '"]');
      if (!input) return;
      input.style.borderColor = "var(--rose)";
      const span = document.createElement("span");
      span.className = "ap-field-error";
      span.textContent = err.message;
      input.closest(".ap-field").appendChild(span);
    });
  }

  function wireEye(button) {
    if (!button) return;
    button.addEventListener("click", () => {
      const target = document.getElementById(button.dataset.eye);
      if (!target) return;
      const hidden = target.type === "password";
      target.type = hidden ? "text" : "password";
      button.setAttribute("aria-label", hidden ? "Hide password" : "Show password");
      button.dataset.showing = hidden ? "1" : "";
      const on = button.querySelector(".eye-on");
      const off = button.querySelector(".eye-off");
      if (on && off) { on.style.display = hidden ? "" : "none"; off.style.display = hidden ? "none" : ""; }
      target.focus({ preventScroll: true });
    });
  }

  function wireStrength(input, meter, label) {
    if (!input || !meter) return;
    const score = (value) => {
      let n = 0;
      if (value.length >= 8) n++;
      if (/[A-Z]/.test(value) && /[a-z]/.test(value)) n++;
      if (/\d/.test(value)) n++;
      if (/[^A-Za-z0-9]/.test(value) || value.length >= 12) n++;
      return value ? Math.max(1, n) : 0;
    };
    const words = ["", "Weak", "Fair", "Good", "Strong"];
    input.addEventListener("input", () => {
      const s = score(input.value);
      meter.dataset.score = String(s);
      if (label) label.textContent = input.value ? "Password strength: " + words[s] : "";
    });
  }

  function busy(button, on, text) {
    if (!button) return;
    if (on) {
      button.dataset.label = button.innerHTML;
      button.disabled = true;
      button.innerHTML = UI.esc(text || "One moment…");
    } else {
      button.disabled = false;
      if (button.dataset.label) button.innerHTML = button.dataset.label;
    }
  }

  /* ---------------------------------------------------------- top bar ---- */
  function initTopbar() {
    const bar = $(".ap-topbar");
    if (!bar) return;

    const search = $(".ap-search input", bar);
    if (search) {
      search.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        const q = search.value.trim();
        location.href = "/tutors.html" + (q ? "?q=" + encodeURIComponent(q) : "");
      });
    }

    const burger = $(".ap-burger", bar);
    const actions = $(".ap-topbar-actions", bar);
    if (burger && actions) {
      burger.addEventListener("click", () => {
        const open = actions.hasAttribute("data-open");
        if (open) actions.removeAttribute("data-open");
        else actions.setAttribute("data-open", "1");
        actions.style.position = open ? "" : "absolute";
        actions.style.right = open ? "" : "14px";
        actions.style.top = open ? "" : "54px";
        actions.style.flexDirection = open ? "" : "column";
        actions.style.background = open ? "" : "var(--surface)";
        actions.style.border = open ? "" : "1px solid var(--border)";
        actions.style.borderRadius = open ? "" : "12px";
        actions.style.padding = open ? "" : "12px 16px";
        actions.style.boxShadow = open ? "" : "var(--shadow-sm)";
        actions.querySelectorAll(".ap-link-plain").forEach((l) => (l.style.display = open ? "" : "inline-flex"));
      });
    }
  }

  /* --------------------------------------------------------- SIGN IN ----- */
  function initSignIn() {
    const form = $("#ap-signin-form");
    if (!form) return;

    if (API.isAuthenticated()) location.replace(redirectFor(stampUser(API.user, personaOf(API.user))));

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const box = $("#ap-signin-error");
      showBox(box, []);
      box.classList.remove("show");
      clearFieldErrors(form);

      const email = form.email.value.trim();
      const password = form.password.value;
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        showBox(box, ["Enter a valid email address."]);
        return;
      }
      if (!password) {
        showBox(box, ["Enter your password."]);
        return;
      }

      const submit = $("#ap-signin-submit");
      busy(submit, true, "Signing in…");
      try {
        const data = await API.login({ email: email, password: password });
        API.saveSession(data);                       // persist the JWT + user before stamping
        const known = knownPersona(email);
        const persona = known ? known.persona : defaultPersona(data.user.role);
        const user = stampUser(data.user, persona, known || {});
        rememberPersona(email, persona, known || {});
        location.replace(redirectFor(user));
      } catch (err) {
        busy(submit, false);
        const messages = [err.message || "Sign in failed."];
        (err.errors || []).forEach((e) => messages.push(e.message));
        showBox(box, messages);
        paintFieldErrors(form, err.errors);
      }
    });
  }

  function personaOf(user) {
    if (!user) return "student";
    const known = knownPersona(user.email);
    return (known && known.persona) || user.persona || defaultPersona(user.role);
  }

  /* --------------------------------------------------------- SIGN UP ----- */
  const ROLE_COPY = {
    student: "Book sessions, track requests and review tutors after each completed session.",
    tutor:
      "Publish your profile, set weekly availability and receive booking requests. Approval is instant for demo accounts.",
    parent:
      "A parent account uses the family dashboard: browse tutors, request sessions and manage reviews on your child's behalf.",
  };

  function initSignUp() {
    const form = $("#ap-signup-form");
    if (!form) return;

    wireStrength(form.password, $("#ap-strength"), $("#ap-strength-label"));

    let persona = "student";
    const tabs = $$(".ap-role-tab");
    const hint = $("#ap-role-hint");

    function selectPersona(next) {
      persona = next;
      tabs.forEach((t) => t.setAttribute("aria-selected", String(t.dataset.role === next)));
      $$(".ap-section", form).forEach((sec) => sec.classList.toggle("on", sec.dataset.section === next));
      if (hint) hint.textContent = ROLE_COPY[next] || "";
    }
    tabs.forEach((tab) => tab.addEventListener("click", () => selectPersona(tab.dataset.role)));
    selectPersona("student");

    /* subject chips (tutors) — live from /api/subjects */
    const chosen = new Set();
    const chipHost = $("#ap-subject-chips");
    if (chipHost) {
      API.subjects({ only_with_tutors: false })
        .then((payload) => {
          const items = (payload && payload.items) || [];
          chipHost.innerHTML = "";
          items.slice(0, 40).forEach((subject) => {
            const chip = document.createElement("button");
            chip.type = "button";
            chip.className = "ap-chip";
            chip.setAttribute("aria-pressed", "false");
            chip.dataset.id = String(subject.id);
            chip.innerHTML = UI.esc(subject.name) +
              '<span class="ap-chip-count">' + (subject.tutor_count || 0) + "</span>";
            chip.addEventListener("click", () => {
              const on = chip.getAttribute("aria-pressed") === "true";
              chip.setAttribute("aria-pressed", String(!on));
              if (on) chosen.delete(subject.id); else chosen.add(subject.id);
            });
            chipHost.appendChild(chip);
          });
        })
        .catch(() => {
          chipHost.innerHTML = '<span class="ap-field-error">Could not load subjects — is the API running?</span>';
        });
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const box = $("#ap-signup-error");
      box.classList.remove("show");
      clearFieldErrors(form);

      const value = (name) => (form.elements[name] ? form.elements[name].value.trim() : "");
      const problems = [];

      if (value("full_name").length < 2) problems.push(["full_name", "Enter your full name."]);
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value("email"))) problems.push(["email", "Enter a valid email address."]);
      if (form.password.value.length < 8) problems.push(["password", "Password must be at least 8 characters."]);

      const payload = {
        full_name: value("full_name"),
        email: value("email"),
        password: form.password.value,
        city: value("city") || undefined,
        state: value("state") || undefined,
      };

      let extra = {};
      if (persona === "tutor") {
        payload.role = "tutor";
        payload.headline = value("headline");
        payload.bio = value("bio");
        payload.years_experience = value("years_experience") === "" ? undefined : Number(value("years_experience"));
        payload.hourly_rate = value("hourly_rate") === "" ? undefined : Number(value("hourly_rate"));
        payload.teaching_mode = value("teaching_mode") || undefined;
        payload.subject_ids = Array.from(chosen);
        if (!payload.headline) problems.push(["headline", "Add a one-line headline."]);
        if ((payload.bio || "").trim().length < 40) problems.push(["bio", "Bio must be at least 40 characters."]);
        if (payload.years_experience === undefined || Number.isNaN(payload.years_experience)) problems.push(["years_experience", "Years of experience is required."]);
        if (payload.hourly_rate === undefined || Number.isNaN(payload.hourly_rate)) problems.push(["hourly_rate", "Hourly rate is required."]);
        if (!payload.subject_ids.length) problems.push([null, "Select at least one subject you teach."]);
      } else if (persona === "parent") {
        payload.role = "student";               // backend account type
        payload.guardian_name = payload.full_name;
        payload.education_level = value("child_level") || undefined;
        extra = { persona: "parent", child_name: value("child_name") || undefined };
        if (!value("child_name")) problems.push(["child_name", "Enter your child's name."]);
      } else {
        payload.role = "student";
        payload.education_level = value("education_level") || undefined;
        payload.guardian_name = value("guardian_name") || undefined;
        extra = { persona: "student" };
      }

      if (problems.length) {
        showBox(box, problems.map((p) => p[1]));
        paintFieldErrors(form, problems.filter((p) => p[0]).map((p) => ({ field: p[0], message: p[1] })));
        return;
      }

      const submit = $("#ap-signup-submit");
      busy(submit, true, "Creating your account…");
      try {
        const data = await API.register(payload);
        API.saveSession(data);                       // persist the JWT so the profile PUT below is authenticated

        if (persona === "parent" && extra.child_name) {
          // record who the account is managed for on the live student profile
          try {
            await API.updateStudentProfile({
              learning_goals: "Parent-managed account for " + extra.child_name + ".",
            });
          } catch (e) { /* profile extras are best-effort */ }
        }

        rememberPersona(payload.email, persona, extra);
        const user = stampUser(data.user, persona, extra);
        location.replace(nextUrl(persona === "tutor"
          ? "/dashboard.html?view=availability&onboard=1"
          : redirectFor(user)));
      } catch (err) {
        busy(submit, false);
        const messages = [err.message || "Registration failed."];
        (err.errors || []).forEach((e) => messages.push(e.message));
        showBox(box, messages);
        paintFieldErrors(form, err.errors);
      }
    });
  }

  /* --------------------------------------------------- FORGOT PASSWORD --- */
  function initForgot() {
    const form = $("#ap-forgot-form");
    const done = $("#ap-forgot-done");
    if (!form || !done) return;

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const box = $("#ap-forgot-error");
      box.classList.remove("show");
      const email = form.email.value.trim();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        showBox(box, ["Enter the email address you registered with."]);
        return;
      }
      form.style.display = "none";
      $("#ap-forgot-email-echo").textContent = email;
      done.classList.add("on");
    });

    const again = $("#ap-forgot-again");
    if (again) {
      again.addEventListener("click", () => {
        done.classList.remove("on");
        form.style.display = "";
        form.email.value = "";
        form.email.focus();
      });
    }
  }

  /* ---------------------------------------------------------------- boot -- */
  document.addEventListener("DOMContentLoaded", () => {
    initTopbar();
    const page = document.body.dataset.apPage;
    if (page === "signin") initSignIn();
    if (page === "signup") initSignUp();
    if (page === "forgot") initForgot();
    $$(".ap-eye").forEach(wireEye);
    const year = $("#ap-year");
    if (year) year.textContent = String(new Date().getFullYear());
  });
})(window);
