import { createRequire } from "node:module";
import { afterEach, describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const { showThreatOverlay, removeThreatOverlay, OVERLAY_ID } = require("../src/overlay.js");

afterEach(() => {
  document.body.innerHTML = "";
  document.documentElement.querySelectorAll("#" + OVERLAY_ID).forEach((el) => el.remove());
});

const threat = { riskScore: 0.94, acousticFlag: "94% (Synthetic Voice)" };

function host() {
  return document.getElementById(OVERLAY_ID);
}

describe("showThreatOverlay", () => {
  it("renders the vignette and modal inside a shadow root", () => {
    showThreatOverlay(threat);
    const root = host().shadowRoot;
    expect(root.querySelector(".vignette")).not.toBeNull();
    expect(root.querySelector(".modal")).not.toBeNull();
    expect(document.querySelector(".modal")).toBeNull();
  });

  it("shows the required title, evidence and ERP notice", () => {
    showThreatOverlay(threat);
    const text = host().shadowRoot.textContent;
    expect(text).toContain("CRITICAL SECURITY THREAT: CEO FRAUD DETECTED");
    expect(text).toContain("94% (Synthetic Voice)");
    expect(text).toContain("DoA: Violated");
    expect(text).toContain("Hệ thống đã tự động khóa cứng cổng thanh toán ERP.");
  });

  it("falls back to the risk score when there is no acoustic flag", () => {
    showThreatOverlay({ riskScore: 0.91 });
    expect(host().shadowRoot.textContent).toContain("91%");
  });

  it("treats threat data as text, never as markup", () => {
    showThreatOverlay({ riskScore: 0.9, acousticFlag: "<img src=x onerror=alert(1)>" });
    expect(host().shadowRoot.querySelector("img")).toBeNull();
    expect(host().shadowRoot.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("is idempotent: a repeated lock keeps a single overlay", () => {
    showThreatOverlay(threat);
    showThreatOverlay(threat);
    expect(document.querySelectorAll("#" + OVERLAY_ID)).toHaveLength(1);
  });

  it("has no dismiss control (there is no unfreeze flow)", () => {
    showThreatOverlay(threat);
    expect(host().shadowRoot.querySelector("button")).toBeNull();
  });

  it("sits above the page and ignores pointer events on the vignette", () => {
    showThreatOverlay(threat);
    const css = host().shadowRoot.querySelector("style").textContent;
    expect(css).toContain("rgba(225, 29, 72");
    expect(css).toContain("pointer-events: none");
  });
});

describe("removeThreatOverlay", () => {
  it("removes the overlay and tolerates being called twice", () => {
    showThreatOverlay(threat);
    removeThreatOverlay();
    removeThreatOverlay();
    expect(host()).toBeNull();
  });
});
