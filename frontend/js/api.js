/* ==========================================================================
   api.js — thin REST client for the TutorConnect FastAPI backend.
   Every screen in the app reads/writes through this module, so all data is
   live database state (no hard-coded content anywhere).
   ========================================================================== */
(function (global) {
  "use strict";

  const TOKEN_KEY = "tm_token";
  const USER_KEY = "tm_user";
  const BASE = "/api";

  class ApiError extends Error {
    constructor(message, status, errors, payload) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.errors = errors || [];
      this.payload = payload || {};
    }
  }

  /* ------------------------------------------------------------ storage -- */
  const store = {
    get token() {
      try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
    },
    set token(v) {
      try { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); } catch (e) {}
    },
    get user() {
      try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch (e) { return null; }
    },
    set user(v) {
      try { v ? localStorage.setItem(USER_KEY, JSON.stringify(v)) : localStorage.removeItem(USER_KEY); } catch (e) {}
    },
    clear() { this.token = ""; this.user = null; }
  };

  /* -------------------------------------------------------------- query -- */
  function qs(params) {
    if (!params) return "";
    const usp = new URLSearchParams();
    Object.keys(params).forEach((key) => {
      const value = params[key];
      if (value === undefined || value === null || value === "" || value === false) return;
      if (Array.isArray(value)) {
        value.forEach((v) => v !== "" && v !== null && v !== undefined && usp.append(key, v));
      } else {
        usp.append(key, value);
      }
    });
    const out = usp.toString();
    return out ? "?" + out : "";
  }

  /* ------------------------------------------------------------- fetch --- */
  async function request(method, path, options) {
    options = options || {};
    const headers = Object.assign({}, options.headers || {});
    let body = options.body;

    if (body !== undefined && !(body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }
    if (store.token) headers["Authorization"] = "Bearer " + store.token;

    let response;
    try {
      response = await fetch(BASE + path + qs(options.query), {
        method,
        headers,
        body,
        credentials: "same-origin"
      });
    } catch (networkError) {
      throw new ApiError(
        "Cannot reach the server. Check that the backend is running and try again.",
        0, [], {}
      );
    }

    let payload = null;
    const text = await response.text();
    if (text) {
      try { payload = JSON.parse(text); }
      catch (e) { payload = { detail: text.slice(0, 400) }; }
    }

    if (!response.ok) {
      const message =
        (payload && (payload.detail || payload.message)) ||
        "Something went wrong (" + response.status + "). Please try again.";
      const err = new ApiError(
        typeof message === "string" ? message : JSON.stringify(message),
        response.status,
        (payload && payload.errors) || [],
        payload || {}
      );
      if (response.status === 401 && store.token && !options.skipAuthRedirect) {
        // token expired / revoked -> drop the session
        store.clear();
        global.dispatchEvent(new CustomEvent("tm:unauthorized"));
      }
      throw err;
    }
    return payload;
  }

  const api = {
    ApiError,
    qs,
    get: (p, o) => request("GET", p, o),
    post: (p, b, o) => request("POST", p, Object.assign({ body: b }, o || {})),
    put: (p, b, o) => request("PUT", p, Object.assign({ body: b }, o || {})),
    patch: (p, b, o) => request("PATCH", p, Object.assign({ body: b }, o || {})),
    del: (p, o) => request("DELETE", p, o),

    /* ---------------------------------------------------------- session -- */
    store,
    get user() { return store.user; },
    get token() { return store.token; },
    isAuthenticated() { return !!store.token; },
    role() { return (store.user && store.user.role) || null; },
    saveSession(data) {
      if (data && data.access_token) store.token = data.access_token;
      if (data && data.user) store.user = data.user;
      return data && data.user;
    },
    async logout() {
      try { if (store.token) await request("POST", "/auth/logout", { skipAuthRedirect: true }); }
      catch (e) { /* best effort */ }
      store.clear();
    },
    async refreshMe() {
      if (!store.token) return null;
      try {
        const me = await request("GET", "/auth/me", { skipAuthRedirect: true });
        store.user = me;
        return me;
      } catch (e) {
        store.clear();
        return null;
      }
    },

    /* ------------------------------------------------------------- auth -- */
    register: (payload) => request("POST", "/auth/register", { body: payload }),
    login: (payload) => request("POST", "/auth/login", { body: payload }),
    me: () => request("GET", "/auth/me"),
    updateMe: (payload) => request("PUT", "/auth/me", { body: payload }),
    uploadAvatar: (dataUrl) => request("POST", "/auth/avatar", { body: { image: dataUrl } }),
    deleteAvatar: () => request("DELETE", "/auth/avatar"),
    changePassword: (payload) => request("POST", "/auth/change-password", { body: payload }),

    /* ---------------------------------------------------------- tutors --- */
    tutors: (params) => request("GET", "/tutors", { query: params }),
    tutor: (id) => request("GET", "/tutors/" + encodeURIComponent(id)),
    tutorFacets: () => request("GET", "/tutors/facets"),
    createTutorProfile: (payload) => request("POST", "/tutors", { body: payload }),
    updateMyTutorProfile: (payload) => request("PUT", "/tutors/me", { body: payload }),
    updateTutorProfile: (id, payload) => request("PUT", "/tutors/" + id, { body: payload }),
    myTutorProfile: () => request("GET", "/tutors/me"),
    myTutorStats: () => request("GET", "/tutors/me/stats"),
    tutorReviews: (id, limit) => request("GET", "/tutors/" + id + "/reviews", { query: { limit } }),
    tutorRating: (id) => request("GET", "/tutors/" + id + "/rating"),
    openSlots: (id, params) => request("GET", "/tutors/" + id + "/open-slots", { query: params }),
    deleteMyTutorProfile: () => request("DELETE", "/tutors/me"),
    setTutorStatus: (id, payload) => request("PUT", "/tutors/" + id + "/status", { body: payload }),

    /* ----------------------------------------------------- availability -- */
    tutorAvailability: (id) => request("GET", "/tutors/" + id + "/availability"),
    myAvailability: () => request("GET", "/availability/mine"),
    addAvailability: (payload, tutorId) =>
      request("POST", "/availability", { body: payload, query: tutorId ? { tutor_id: tutorId } : undefined }),
    updateAvailability: (id, payload) => request("PUT", "/availability/" + id, { body: payload }),
    toggleAvailability: (id) => request("PATCH", "/availability/" + id + "/toggle"),
    deleteAvailability: (id) => request("DELETE", "/availability/" + id),
    addException: (payload, tutorId) =>
      request("POST", "/availability/exceptions", { body: payload, query: tutorId ? { tutor_id: tutorId } : undefined }),
    deleteException: (id) => request("DELETE", "/availability/exceptions/" + id),

    /* --------------------------------------------------------- requests -- */
    requests: (params) => request("GET", "/requests", { query: params }),
    request: (id) => request("GET", "/requests/" + id),
    createRequest: (payload) => request("POST", "/requests", { body: payload }),
    updateRequest: (id, payload) => request("PUT", "/requests/" + id, { body: payload }),
    decideRequest: (id, payload) => request("PUT", "/requests/" + id + "/status", { body: payload }),
    cancelRequest: (id, payload) => request("POST", "/requests/" + id + "/cancel", { body: payload || {} }),
    deleteRequest: (id) => request("DELETE", "/requests/" + id),
    markRequestRead: (id) => request("POST", "/requests/" + id + "/read"),
    studentStats: () => request("GET", "/requests/mine/stats"),
    upcoming: (limit) => request("GET", "/requests/upcoming/list", { query: { limit } }),

    /* ---------------------------------------------------------- reviews -- */
    myReviews: () => request("GET", "/reviews/mine"),
    createReview: (payload) => request("POST", "/reviews", { body: payload }),
    updateReview: (id, payload) => request("PUT", "/reviews/" + id, { body: payload }),
    deleteReview: (id) => request("DELETE", "/reviews/" + id),

    /* --------------------------------------------------------- students -- */
    myStudentProfile: () => request("GET", "/students/me"),
    updateStudentProfile: (payload) => request("PUT", "/students/me", { body: payload }),

    /* --------------------------------------------------------- subjects -- */
    subjects: (params) => request("GET", "/subjects", { query: params }),
    subjectCategories: () => request("GET", "/subjects/categories"),
    createSubject: (payload) => request("POST", "/subjects", { body: payload }),
    updateSubject: (id, payload) => request("PUT", "/subjects/" + id, { body: payload }),
    deleteSubject: (id) => request("DELETE", "/subjects/" + id),

    /* -------------------------------------------------------- favorites -- */
    favorites: () => request("GET", "/favorites"),
    toggleFavorite: (tutorId) => request("POST", "/favorites/" + tutorId + "/toggle"),

    /* ---------------------------------------------------- notifications -- */
    notifications: (params) => request("GET", "/notifications", { query: params }),
    unreadCount: () => request("GET", "/notifications/unread-count"),
    readNotification: (id) => request("POST", "/notifications/" + id + "/read"),
    readAllNotifications: () => request("POST", "/notifications/read-all"),

    /* ----------------------------------------------------------- admin --- */
    adminStats: (days) => request("GET", "/admin/stats", { query: { days } }),
    adminActivity: (limit) => request("GET", "/admin/activity", { query: { limit } }),
    adminUsers: (params) => request("GET", "/admin/users", { query: params }),
    adminUser: (id) => request("GET", "/admin/users/" + id),
    adminUpdateUser: (id, payload) => request("PUT", "/admin/users/" + id, { body: payload }),
    adminToggleUser: (id) => request("POST", "/admin/users/" + id + "/toggle-active"),
    adminDeleteUser: (id) => request("DELETE", "/admin/users/" + id),
    adminCreateUser: (params) => request("POST", "/admin/users", { query: params }),
    adminTutors: (params) => request("GET", "/admin/tutors", { query: params }),
    adminRequests: (params) => request("GET", "/admin/requests", { query: params }),
    adminReviews: (params) => request("GET", "/admin/reviews", { query: params }),
    adminHideReview: (id, reason) => request("POST", "/admin/reviews/" + id + "/hide", undefined, { query: { reason } }),
    adminRestoreReview: (id) => request("POST", "/admin/reviews/" + id + "/restore"),
    adminCancelRequest: (id, reason) => request("POST", "/admin/requests/" + id + "/cancel", undefined, { query: { reason } }),
    adminDeleteRequest: (id) => request("DELETE", "/admin/requests/" + id),

    /* ----------------------------------------------------------- meta ---- */
    health: () => request("GET", "/health"),
    config: () => request("GET", "/config"),
    index: () => request("GET", "")
  };

  global.API = api;
})(window);
