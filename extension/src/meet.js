(function () {
  const ROOM_RE = /^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}(?:[/?#].*)?$/;

  function isMeetRoomUrl(url) {
    return typeof url === "string" && ROOM_RE.test(url);
  }

  // Meet is a single-page app: leaving a call changes the URL without a reload,
  // so we watch the URL instead of waiting for page events.
  function createMeetLifecycle({ getUrl, onEnter, onLeave, intervalMs = 500 }) {
    let inRoom = false;
    let timer = null;

    function check() {
      const now = isMeetRoomUrl(getUrl());
      if (now && !inRoom) {
        inRoom = true;
        onEnter();
      } else if (!now && inRoom) {
        inRoom = false;
        onLeave();
      }
    }

    function stop() {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
        if (typeof window !== "undefined") {
          window.removeEventListener("popstate", check);
          window.removeEventListener("hashchange", check);
        }
      }
      if (inRoom) {
        inRoom = false;
        onLeave();
      }
    }

    check();
    timer = setInterval(check, intervalMs);
    if (typeof window !== "undefined") {
      window.addEventListener("popstate", check);
      window.addEventListener("hashchange", check);
    }
    return { stop };
  }

  const api = { isMeetRoomUrl, createMeetLifecycle };
  globalThis.EchoSentry = Object.assign(globalThis.EchoSentry || {}, api);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
