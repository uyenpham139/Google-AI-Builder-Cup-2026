import { createRequire } from "node:module";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const require = createRequire(import.meta.url);
const { isMeetRoomUrl, createMeetLifecycle } = require("../src/meet.js");

describe("isMeetRoomUrl", () => {
  it.each([
    "https://meet.google.com/abc-defg-hij",
    "https://meet.google.com/abc-defg-hij?authuser=1",
    "https://meet.google.com/abc-defg-hij/",
    "https://meet.google.com/abc-defg-hij#x",
  ])("accepts %s", (url) => expect(isMeetRoomUrl(url)).toBe(true));

  it.each([
    "https://meet.google.com/",
    "https://meet.google.com/landing",
    "https://meet.google.com/abc-defg-hijk",
    "https://meet.google.com/ab-defg-hij",
    "https://meet.google.com/ABC-DEFG-HIJ",
    "http://meet.google.com/abc-defg-hij",
    "https://evil.example/meet.google.com/abc-defg-hij",
    "https://meet.google.com.evil.example/abc-defg-hij",
    "",
  ])("rejects %s", (url) => expect(isMeetRoomUrl(url)).toBe(false));

  it("tolerates non-string input", () => {
    expect(isMeetRoomUrl(undefined)).toBe(false);
    expect(isMeetRoomUrl(null)).toBe(false);
  });
});

describe("createMeetLifecycle", () => {
  let url;
  beforeEach(() => {
    vi.useFakeTimers();
    url = "https://meet.google.com/landing";
  });
  afterEach(() => vi.useRealTimers());

  const make = () => {
    const onEnter = vi.fn();
    const onLeave = vi.fn();
    const life = createMeetLifecycle({ getUrl: () => url, onEnter, onLeave, intervalMs: 500 });
    return { life, onEnter, onLeave };
  };

  it("does nothing on a non-room page", () => {
    const { onEnter, onLeave } = make();
    vi.advanceTimersByTime(5000);
    expect(onEnter).not.toHaveBeenCalled();
    expect(onLeave).not.toHaveBeenCalled();
  });

  it("enters immediately if the page already is a room", () => {
    url = "https://meet.google.com/abc-defg-hij";
    const { onEnter } = make();
    expect(onEnter).toHaveBeenCalledTimes(1);
  });

  it("enters once when navigating into a room and leaves once when navigating out", () => {
    const { onEnter, onLeave } = make();
    url = "https://meet.google.com/abc-defg-hij";
    vi.advanceTimersByTime(500);
    vi.advanceTimersByTime(2000);
    expect(onEnter).toHaveBeenCalledTimes(1);
    url = "https://meet.google.com/landing";
    vi.advanceTimersByTime(500);
    vi.advanceTimersByTime(2000);
    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it("re-enters for a second meeting", () => {
    const { onEnter, onLeave } = make();
    url = "https://meet.google.com/abc-defg-hij";
    vi.advanceTimersByTime(500);
    url = "https://meet.google.com/landing";
    vi.advanceTimersByTime(500);
    url = "https://meet.google.com/xyz-abcd-efg";
    vi.advanceTimersByTime(500);
    expect(onEnter).toHaveBeenCalledTimes(2);
    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it("stop() halts polling and leaves an active room exactly once", () => {
    url = "https://meet.google.com/abc-defg-hij";
    const { life, onLeave } = make();
    life.stop();
    life.stop();
    vi.advanceTimersByTime(5000);
    expect(onLeave).toHaveBeenCalledTimes(1);
  });
});
