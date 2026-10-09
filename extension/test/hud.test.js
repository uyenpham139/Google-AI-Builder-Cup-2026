import { createRequire } from "node:module";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const require = createRequire(import.meta.url);
const { EchoSentryHud, BAR_COUNT } = require("../src/hud.js");

let rafCallbacks;
let drawn;

function fakeAnalyser(values) {
  return {
    fftSize: 0,
    frequencyBinCount: 32,
    getByteFrequencyData: (arr) => arr.set(values.slice(0, arr.length)),
  };
}

beforeEach(() => {
  rafCallbacks = new Map();
  let id = 0;
  vi.stubGlobal("requestAnimationFrame", (cb) => {
    rafCallbacks.set(++id, cb);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", (n) => rafCallbacks.delete(n));
  drawn = [];
  HTMLCanvasElement.prototype.getContext = () => ({
    clearRect: () => {},
    fillRect: (x, y, w, h) => drawn.push({ x, y, w, h }),
    beginPath: () => {},
    fill: () => {},
    set fillStyle(_v) {},
  });
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

function mount() {
  const hud = document.createElement("echo-sentry-hud");
  document.body.appendChild(hud);
  return hud;
}

function frame() {
  const [[id, cb]] = [...rafCallbacks.entries()];
  rafCallbacks.delete(id);
  cb(0);
}

describe("Shadow DOM isolation", () => {
  it("keeps the canvas inside the shadow root, invisible to the page", () => {
    const hud = mount();
    expect(hud.shadowRoot.querySelector("#waveform-canvas")).not.toBeNull();
    expect(document.querySelector("#waveform-canvas")).toBeNull();
  });

  it("shows the brand, standby state and no pulsing dot colour of live", () => {
    const hud = mount();
    const text = hud.shadowRoot.textContent;
    expect(text).toContain("ECHO Sentry");
    expect(text).toContain("STANDBY");
    expect(text).not.toContain("LIVE MONITORING");
    expect(hud.live).toBe(false);
  });

  it("does not build the shadow DOM twice when re-attached", () => {
    const hud = mount();
    document.body.removeChild(hud);
    document.body.appendChild(hud);
    expect(hud.shadowRoot.querySelectorAll("canvas")).toHaveLength(1);
  });
});

describe("analyser binding", () => {
  it("switches to LIVE MONITORING and configures fftSize 64", () => {
    const hud = mount();
    const analyser = fakeAnalyser(new Array(32).fill(0));
    hud.attachAnalyser(analyser);
    expect(analyser.fftSize).toBe(64);
    expect(hud.live).toBe(true);
    expect(hud.shadowRoot.textContent).toContain("LIVE MONITORING");
  });

  it("draws a 2 px floor in silence and up to 20 px for loud input", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    frame();
    expect(drawn).toHaveLength(BAR_COUNT);
    expect(drawn.every((b) => b.h === 2)).toBe(true);

    drawn.length = 0;
    hud.detachAnalyser();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(255)));
    frame();
    expect(drawn.every((b) => b.h === 20)).toBe(true);
  });

  it("scales bars with amplitude between the floor and the max", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(128)));
    frame();
    const h = drawn[0].h;
    expect(h).toBeGreaterThan(2);
    expect(h).toBeLessThan(20);
  });

  it("keeps drawing every frame while attached", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(10)));
    frame();
    expect(rafCallbacks.size).toBe(1);
    frame();
    expect(rafCallbacks.size).toBe(1);
  });
});

describe("render loop cleanup", () => {
  it("cancels the animation frame when the analyser is detached", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    expect(rafCallbacks.size).toBe(1);
    hud.detachAnalyser();
    expect(rafCallbacks.size).toBe(0);
    expect(hud.live).toBe(false);
  });

  it("cancels the animation frame when the element is removed", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    hud.remove();
    expect(rafCallbacks.size).toBe(0);
  });

  it("does not start a second loop when attached twice", () => {
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    expect(rafCallbacks.size).toBe(1);
  });

  it("survives a canvas without a 2d context", () => {
    HTMLCanvasElement.prototype.getContext = () => null;
    const hud = mount();
    hud.attachAnalyser(fakeAnalyser(new Array(32).fill(0)));
    expect(() => frame()).not.toThrow();
  });
});
