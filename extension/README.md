# ECHO In-Meeting Defense Extension

Chrome (Manifest V3) extension that puts an **ECHO Sentry** HUD on Google Meet: a pill in the top-right corner with a status dot and a 12-bar live waveform, drawn inside a Shadow DOM so Meet's styles cannot touch it.

## Load it

1. Open `chrome://extensions` and turn on **Developer mode**.
2. Click **Load unpacked** and select this `extension/` folder.

## Use it

1. Open a Google Meet room (`https://meet.google.com/abc-defg-hij`). The HUD appears in **STANDBY**.
2. Click the ECHO toolbar icon. Chrome grants tab capture and the HUD switches to **LIVE MONITORING** with the waveform moving.
3. Leave the call. The HUD is removed and the audio capture is released.

Leaving a call is detected from the page URL, because Meet's buttons change with the display language.

## Layout

| File | Role |
|---|---|
| `src/hud.js` | `<echo-sentry-hud>` custom element (Shadow DOM, canvas, `requestAnimationFrame`) |
| `src/meet.js` | Meet room URL check and enter/leave lifecycle |
| `content.js` | Mounts the HUD and binds the tab audio to an `AnalyserNode` |
| `background.js` | Gets the tab capture id when the icon is clicked |
| `test/` | vitest tests, run with `pnpm --filter frontend test` |

## Known gap

The extension shows the waveform only. Streaming its audio to `/ws/audio` should reuse the modules in `frontend/lib/audio/`, and that needs a bundling step that is not part of Feature 1. Real-browser behaviour (tab capture, the live Meet page) is not covered by the automated tests and needs a manual check.
