/* ==========================================================================
   register.js — role-aware registration (student, parent or tutor).
   Creates a real account + profile row through POST /api/auth/register.
   ========================================================================== */
(function () {
  "use strict";

  const form = document.getElementById("registerForm");
  const alertHost = document.getElementById("formAlert");
  const submitBtn = document.getElementById("submitBtn");
  const studentFields = document.getElementById("studentFields");
  const parentFields = document.getElementById("parentFields");
  const tutorFields = document.getElementById("tutorFields");
  const subjectPicker = document.getElementById("subjectPicker");

  let subjects = [];
  let currentRole = "student";

  function renderAlert(html) {
    alertHost.innerHTML = html ? '<div style="margin-bottom:16px">' + html + "</div>" : "";
    if (html) alertHost.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function setRole(role) {
    currentRole = role;
    const isTutor = role === "tutor";
    const isParent = role === "parent";
    tutorFields.classList.toggle("hide", !isTutor);
    studentFields.classList.toggle("hide", isTutor);
    parentFields.classList.toggle("hide", !isParent);
    // required flags follow the visible role
    ["headline", "bio", "years_experience", "hourly_rate", "city", "state"].forEach((name) => {
      const nodes = form.querySelectorAll('[name="' + name + '"]');
      const input = Array.from(nodes).find((n) => !n.closest(".hide")) || nodes[0];
      if (input) input.required = isTutor;
    });
    ["education_level", "guardian_name", "child_name"].forEach((name) => {
      const input = form.querySelector('[name="' + name + '"]');
      if (input) input.required = false;
    });
    submitBtn.textContent = isTutor ? "Create tutor account" : isParent ? "Create parent account" : "Create account";
    renderAlert("");
    UI.showFieldErrors(form, []);
  }

  async function loadSubjects() {
    try {
      const res = await API.subjects({});
      subjects = res.items || [];
      subjectPicker.innerHTML = "";
      const subjectSelect = document.getElementById("subjectSelect");
      if (!subjects.length) {
        subjectPicker.innerHTML = '<p class="muted small">No subjects available yet.</p>';
        if (subjectSelect) subjectSelect.disabled = true;
      } else if (subjectSelect && UI.subjectDropdown) {
        UI.subjectDropdown(subjectSelect, subjectPicker, subjects, [], updateSubjectCount);
      }
      updateSubjectCount();
    } catch (err) {
      subjectPicker.innerHTML = '<p class="error-box"><span class="ico">⚠️</span>' + UI.esc(err.message) + "</p>";
    }
  }

  function updateSubjectCount() {
    const n = subjectPicker.querySelectorAll("input:checked").length;
    const node = document.getElementById("subjectCount");
    if (node) node.textContent = String(n);
  }

  function selectedSubjectIds() {
    return Array.from(subjectPicker.querySelectorAll("input:checked")).map((i) => Number(i.value));
  }

  /* --------------------------------------------------------- validation -- */
  function validate() {
    const errors = [];
    const value = (name) => {
      const nodes = form.querySelectorAll('[name="' + name + '"]');
      // Several roles share field names (e.g. "state"): prefer the field that
      // is actually visible for the selected role, never a hidden section's.
      for (const node of nodes) {
        if (!node.closest(".hide")) return String(node.value || "").trim();
      }
      const first = nodes[0];
      return first ? String(first.value || "").trim() : "";
    };

    if (value("full_name").length < 2) errors.push({ field: "full_name", message: "Please enter your full name." });
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value("email"))) errors.push({ field: "email", message: "Enter a valid email address." });

    const password = value("password");
    if (password.length < 8) errors.push({ field: "password", message: "Password must be at least 8 characters." });
    else if (!/[A-Za-z]/.test(password)) errors.push({ field: "password", message: "Password must contain a letter." });
    else if (!/\d/.test(password)) errors.push({ field: "password", message: "Password must contain a number." });

    if (value("confirm_password") !== password) errors.push({ field: "confirm_password", message: "Passwords do not match." });
    if (!document.getElementById("terms").checked) errors.push({ field: "terms", message: "Please accept the terms to continue." });

    if (currentRole === "tutor") {
      if (value("headline").length < 5) errors.push({ field: "headline", message: "Write a short professional headline." });
      if (value("bio").length < 40) errors.push({ field: "bio", message: "Your bio must be at least 40 characters." });
      const years = Number(value("years_experience"));
      if (value("years_experience") === "" || isNaN(years) || years < 0 || years > 70)
        errors.push({ field: "years_experience", message: "Enter your years of experience (0–70)." });
      const rate = Number(value("hourly_rate"));
      if (value("hourly_rate") === "" || isNaN(rate) || rate <= 0)
        errors.push({ field: "hourly_rate", message: "Enter your rate per session." });
      if (value("city").length < 2) errors.push({ field: "city", message: "Which city do you teach in?" });
      if (value("state").length < 2) errors.push({ field: "state", message: "Which state do you teach in?" });
      if (!selectedSubjectIds().length) errors.push({ field: "subject_ids", message: "Select at least one subject you teach." });
    }

    UI.showFieldErrors(form, errors);
    if (errors.length) {
      renderAlert('<div class="error-box"><span class="ico">⚠️</span><div><strong>Please fix ' +
        errors.length + " issue" + (errors.length === 1 ? "" : "s") + ":</strong><ul>" +
        errors.map((e) => "<li>" + UI.esc(e.message) + "</li>").join("") + "</ul></div></div>");
      const first = form.querySelector(".field.invalid input, .field.invalid textarea, .field.invalid select");
      if (first) first.focus();
      return null;
    }
    renderAlert("");

    const payload = {
      role: currentRole === "parent" ? "student" : currentRole,   // parent accounts are family (student-role) accounts
      full_name: value("full_name"),
      email: value("email"),
      password,
      phone: value("phone") || null,
      city: value("city") || null,
      state: value("state") || null
    };

    if (currentRole !== "tutor") {
      payload.education_level = value("education_level") || null;
      payload.guardian_name = value("guardian_name") || null;
    } else {
      Object.assign(payload, {
        headline: value("headline"),
        bio: value("bio"),
        years_experience: Number(value("years_experience")),
        hourly_rate: Number(value("hourly_rate")),
        teaching_mode: value("teaching_mode") || "hybrid",
        qualifications: value("qualifications") || null,
        subject_ids: selectedSubjectIds()
      });
    }
    return payload;
  }

  /* -------------------------------------------------------------- init --- */
  async function init() {
    const ok = await App.boot();
    if (!ok) return;

    if (API.isAuthenticated()) {
      location.replace("dashboard.html");
      return;
    }

    const params = UI.readQueryParams();
    const requested = params.role === "tutor" ? "tutor" : params.role === "parent" ? "parent" : "student";
    const radio = form.querySelector('input[name="role"][value="' + requested + '"]');
    if (radio) radio.checked = true;
    setRole(requested);

    form.querySelectorAll('input[name="role"]').forEach((r) =>
      r.addEventListener("change", () => setRole(r.value))
    );

    // device photo picker (upload / change / remove) — no URL typing anywhere
    const photo = UI.photoPicker({});
    const photoHost = document.getElementById("photoPicker");
    if (photoHost) photoHost.appendChild(photo.el);

    // eye button on both password fields so users can confirm what they typed
    UI.addPasswordToggles(form);

    await loadSubjects();

    // password strength meter
    const password = document.getElementById("password");
    const confirm = document.getElementById("confirmPassword");
    const strengthBar = document.getElementById("strength");
    const strengthText = document.getElementById("strengthText");
    password.addEventListener("input", () => {
      const s = UI.passwordStrength(password.value);
      strengthBar.dataset.score = String(s.score);
      strengthText.textContent = password.value
        ? "Strength: " + s.label + (s.score < 3 ? " — add numbers, symbols or length." : " — looks good.")
        : "Use 8+ characters with a mix of letters and numbers.";
    });
    confirm.addEventListener("input", () => {
      const field = confirm.closest(".field");
      if (!confirm.value) { field.classList.remove("invalid"); return; }
      const match = confirm.value === password.value;
      field.classList.toggle("invalid", !match);
      const slot = field.querySelector(".field-error");
      if (slot) slot.textContent = match ? "" : "Passwords do not match.";
    });

    // bio counter
    const bio = form.querySelector('[name="bio"]');
    if (bio) {
      bio.addEventListener("input", () => {
        document.getElementById("bioCount").textContent = String(bio.value.length);
      });
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const payload = validate();
      if (!payload) return;

      UI.setLoading(submitBtn, true, "Creating your account…");
      try {
        const data = await API.register(payload);
        API.saveSession(data);

        if (currentRole === "parent") {
          // Remember the parent persona (same client-side store the /signup portal uses)
          const childField = form.querySelector('[name="child_name"]');
          const childName = childField ? String(childField.value || "").trim() : "";
          try {
            const all = JSON.parse(localStorage.getItem("tm_personas") || "{}");
            const entry = { persona: "parent" };
            if (childName) entry.child_name = childName;
            all[String(payload.email).toLowerCase()] = entry;
            localStorage.setItem("tm_personas", JSON.stringify(all));
          } catch (e) { /* best effort */ }
          const stamped = Object.assign({}, data.user, { persona: "parent", account_role: "parent" });
          if (childName) stamped.child_name = childName;
          API.store.user = stamped;
          if (childName) {
            try {
              await API.updateStudentProfile({ learning_goals: "Parent-managed account for " + childName + "." });
            } catch (e) { /* profile extras are best effort */ }
          }
        }

        const chosenPhoto = photo.pending();
        if (chosenPhoto) {
          try {
            const uploaded = await API.uploadAvatar(chosenPhoto.dataUrl);
            const stored = Object.assign({}, API.store.user || data.user);
            stored.avatar_url = (uploaded && uploaded.data && uploaded.data.avatar_url) || stored.avatar_url || null;
            API.store.user = stored;
          } catch (uploadErr) {
            UI.toastError("Account created, but the photo upload failed: " + uploadErr.message, "Photo not uploaded");
          }
        }

        UI.toastSuccess(
          currentRole === "tutor"
            ? "Welcome aboard! Next, publish your weekly availability so students can request you."
            : currentRole === "parent"
              ? "Welcome! Your parent account is ready — start browsing tutors for your child."
              : "Welcome! Start searching for tutors that match your needs.",
          "Account created"
        );
        setTimeout(() => {
          location.href = currentRole === "tutor"
            ? "dashboard.html?view=availability&onboard=1"
            : currentRole === "parent"
              ? "dashboard.html?view=browse"
              : "tutors.html";
        }, 900);
      } catch (err) {
        UI.setLoading(submitBtn, false);
        if (err.status === 422 && err.errors && err.errors.length) {
          UI.showFieldErrors(form, err.errors);
          renderAlert('<div class="error-box"><span class="ico">⚠️</span><div><strong>' +
            UI.esc(err.message) + "</strong><ul>" +
            err.errors.map((x) => "<li>" + UI.esc(x.field) + ": " + UI.esc(x.message) + "</li>").join("") +
            "</ul></div></div>");
        } else {
          renderAlert('<div class="error-box"><span class="ico">⚠️</span><div>' + UI.esc(err.message) + "</div></div>");
          if (err.status === 409) {
            const emailField = form.querySelector('[name="email"]');
            if (emailField) emailField.focus();
          }
        }
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
