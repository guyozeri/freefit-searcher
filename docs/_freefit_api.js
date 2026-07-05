/*
 * FreeFit mobile-API client for the browser.
 *
 * The API (ffservice.freefit.co.il) sends `Access-Control-Allow-Origin: *` and
 * accepts browser User-Agents, so the page calls it directly — no backend.
 *
 * Auth is per-user and lives only in this browser: the device token is
 * generated here, registered by passing an SMS check, and kept in
 * localStorage. Nothing secret is ever baked into the page.
 */
window.FreeFit = (function () {
  const BASE = "https://ffservice.freefit.co.il/MobileManagementService";
  const APP_VER = "2.2.20";
  const STORE_KEY = "freefit_session";

  // ---- session (localStorage) ----

  function loadSession() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; }
    catch (_) { return {}; }
  }
  function saveSession(s) { localStorage.setItem(STORE_KEY, JSON.stringify(s)); }
  function clearSession() { localStorage.removeItem(STORE_KEY); }
  function isLoggedIn() {
    const s = loadSession();
    return !!(s.token_base && s.id && s.phone);
  }
  function currentPhone() { return loadSession().phone || null; }

  // ---- helpers ----

  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
      const r = crypto.getRandomValues(new Uint8Array(1))[0] % 16;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }
  function randomHex(nBytes) {
    return Array.from(crypto.getRandomValues(new Uint8Array(nBytes)))
      .map(b => b.toString(16).padStart(2, "0")).join("");
  }
  function makeDeviceToken() { return randomHex(16); }               // 32 hex chars
  function makeToken(base) { return (10 + Math.floor(Math.random() * 11)) + base; }

  // Mirror the app/book.py contract: floats keep a trailing .0 ("12" -> "12.0").
  // JSON.parse collapses 12.0 to the JS number 12, so re-add the decimal.
  function fmtFloat(v) {
    if (v == null) return "0.0";
    const n = Number(v);
    return Number.isInteger(n) ? n.toFixed(1) : String(n);
  }

  async function call(method, payload) {
    let resp;
    try {
      resp = await fetch(`${BASE}/${method}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (e) {
      throw new Error("Network error — could not reach FreeFit.");
    }
    if (!resp.ok) throw new Error(`${method}: HTTP ${resp.status}`);
    const env = await resp.json();
    if (env.Error && env.Error !== 0) {
      const err = new Error(env.Message || `${method} failed (Error ${env.Error})`);
      err.code = env.Error;
      throw err;
    }
    let data = env.Data;
    if (typeof data === "string" && data.length) {
      try { data = JSON.parse(data); } catch (_) { /* leave as string */ }
    }
    return data;
  }

  // The server-side session expires (Error 11); a fresh Login re-establishes it.
  const SESSION_EXPIRED = [11];

  async function loginRefresh() {
    const s = loadSession();
    if (!s.token_base) throw new Error("Not logged in.");
    await call("Login", {
      Token: makeToken(s.token_base), ID: s.id, PushToken: s.push_token || "",
      Phone: s.phone, AppVer: APP_VER,
    });
  }

  // Run an authenticated call; if the session expired, Login once and retry.
  async function authed(method, payload) {
    try {
      return await call(method, payload);
    } catch (e) {
      if (SESSION_EXPIRED.includes(e.code)) {
        await loginRefresh();
        return await call(method, payload);
      }
      throw e;
    }
  }

  // ---- auth ----

  async function sendSmsCode(phone) {
    await call("SendSmsCode", { Phone: phone });
  }

  async function verifyAndLogin(phone, code) {
    const s = loadSession();
    const tokenBase = s.token_base || makeDeviceToken();
    const pushToken = s.push_token || uuid();

    const verify = await call("VerifySmsCode", {
      DeviceType: "web",
      DeviceConfStr: '[{"os_version":"web"},{"device_config":"browser"},{"language":"he"}]',
      PushToken: pushToken,
      Code: code,
      IgnoreOtpCode: false,
      Phone: phone,
      AppVer: APP_VER,
      Token: makeToken(tokenBase),
    });
    const id = String((verify && verify.RecordID) || "");
    if (!id) throw new Error("Verification did not return an account id.");

    // Login pulls the full profile (card number needed for booking).
    const profile = await call("Login", {
      Token: makeToken(tokenBase), ID: id, PushToken: pushToken,
      Phone: phone, AppVer: APP_VER,
    });
    const row = Array.isArray(profile) ? profile[0] : profile;
    const session = {
      token_base: tokenBase, push_token: pushToken, id, phone,
      card_number: (row && row.CardNumber) || "",
      bin_id: (row && row.BinID) || "",
      first_name: (row && row.FirstName) || "",
    };
    saveSession(session);
    return session;
  }

  function logout() { clearSession(); }

  // ---- data / booking ----

  async function getLessons(clubId) {
    const s = loadSession();
    const data = await authed("GetClubLessonList", {
      Token: makeToken(s.token_base), ID: s.id,
      ClubID: String(clubId), Phone: s.phone,
    });
    return Array.isArray(data) ? data : [];
  }

  async function getOrders() {
    const s = loadSession();
    const data = await authed("GetClubOrders", {
      Phone: s.phone, Token: makeToken(s.token_base), ID: s.id,
    });
    return Array.isArray(data) ? data : [];
  }

  // club = { id, tid (TerminalID), bt (BinType) }; lesson from getLessons()
  async function book(club, lesson) {
    const s = loadSession();
    await authed("ClubOrder", {
      Phone: s.phone,
      BinType: club.bt,
      LessonName: lesson.LessonName,
      IsCancelAllow: lesson.IsCancelAllow || false,
      Token: makeToken(s.token_base),
      PreOrderDate: lesson.LessonStartDate,
      RboxLessonID: String(lesson.RboxLessonID),
      ID: s.id,
      ClubID: String(club.id),
      IsOnlyCheckWithoutTransaction: "false",
      LessonStartDate: lesson.LessonStartDate,
      CancelationTime: fmtFloat(lesson.CancelationTime),
      LessonEndDate: lesson.LessonEndDate,
      IsRbox: true,
      CardNumber: s.card_number,
      IsSubscriptionOrder: "true",
      TerminalID: String(club.tid),
      CoachName: lesson.CoachName || "",
    });
    return true;
  }

  async function cancel(clubOrderNum) {
    const s = loadSession();
    await authed("CancelClubOrder", {
      Token: makeToken(s.token_base), Phone: s.phone,
      ClubOrderNum: String(clubOrderNum), ID: s.id,
    });
    return true;
  }

  return {
    isLoggedIn, currentPhone, logout,
    sendSmsCode, verifyAndLogin,
    getLessons, getOrders, book, cancel,
  };
})();
