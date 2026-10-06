/* ==========================================================================
   login.js — real JWT authentication against POST /api/auth/login
   ========================================================================== */
(function () {
  "use strict";

  const form = document.getElementById("loginForm");
  const alertHost = document.getElementById("formAlert");
  const submitBtn = document.getElementById("submitBtn");

  function nextTarget() {
    const params = UI.readQueryParams();
    const next = params.next;
    if (!next) return "dashboard.html";
    // only allow same-origin relative targets
    if (/^[a-zA-Z0-9\-_.]+\.html/.test(next) && !next.startsWith("//")) return next;
    return "dashboard.html";
  }

  function renderAlert(html) {
    alertHost.innerHTML = html ? '<div style="margin-bottom:16px">' + html + "</div>" : "";
  }

  async function init() {
    const ok = await App.boot();
    if (!ok) return;

    // eye button so users can confirm their password before signing in
    UI.addPasswordToggles(form);

    /* Role picker beside "Create an account": remembers the visitor's choice
       and points the register link at the matching role section. */
    const roleSel = document.getElementById("loginRole");
    const createLink = document.getElementById("createAccountLink");
    if (roleSel) {
      const syncRole = () => {
        const r = roleSel.value;
        try {
          if (r) localStorage.setItem("tc_login_role", r);
          else localStorage.removeItem("tc_login_role");
        } catch (err) { /* private mode: selection simply isn't remembered */ }
        if (createLink) {
          createLink.href = r && r !== "admin" ? "register.html?role=" + encodeURIComponent(r) : "register.html";
        }
      };
      try { roleSel.value = localStorage.getItem("tc_login_role") || ""; } catch (err) { /* ignore */ }
      roleSel.addEventListener("change", syncRole);
      syncRole();
    }

    if (API.isAuthenticated()) {
      renderAlert('<div class="info-box">You are already signed in as <strong>' +
        UI.esc((API.user || {}).full_name) + '</strong>. <a href="dashboard.html">Go to your dashboard</a>.</div>');
    }

    document.querySelectorAll("[data-fill]").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.getElementById("email").value = btn.dataset.fill;
        document.getElementById("password").value = btn.dataset.pass;
        renderAlert("");
        UI.showFieldErrors(form, []);
        document.getElementById("password").focus();
      });
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      renderAlert("");
      UI.showFieldErrors(form, []);

      const email = document.getElementById("email").value.trim();
      const password = document.getElementById("password").value;

      if (!email || !password) {
        renderAlert('<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle"></i></span><div>Please enter both your email and password.</div></div>');
        return;
      }

      UI.setLoading(submitBtn, true, "Signing in…");
      try {
        const data = await API.login({ email, password });
        API.saveSession(data);
        UI.toastSuccess("Welcome back, " + (data.user.full_name.split(" ")[0]) + "!", "Signed in");
        const role = data.user.role;
        const target = nextTarget();
        setTimeout(() => {
          location.href = role === "admin" && target === "dashboard.html" ? "dashboard.html" : target;
        }, 450);
      } catch (err) {
        UI.setLoading(submitBtn, false);
        if (err.status === 422 && err.errors && err.errors.length) {
          UI.showFieldErrors(form, err.errors);
          renderAlert('<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle"></i></span><div>' + UI.esc(err.message) + "</div></div>");
        } else {
          renderAlert('<div class="error-box"><span class="ico"><i class="bi bi-exclamation-triangle"></i></span><div>' + UI.esc(err.message) + "</div></div>");
          document.getElementById("password").value = "";
          document.getElementById("password").focus();
        }
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();