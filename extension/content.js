(function () {
  const { createMeetLifecycle } = globalThis.EchoSentry;

  let hud = null;
  let audio = null; // { ctx, stream }

  function mountHud() {
    if (hud) return;
    hud = document.createElement("echo-sentry-hud");
    document.documentElement.appendChild(hud);
  }

  async function releaseAudio() {
    if (!audio) return;
    const { ctx, stream } = audio;
    audio = null;
    stream.getTracks().forEach((t) => t.stop());
    await ctx.close().catch(() => undefined);
  }

  async function unmountHud() {
    if (hud) {
      hud.detachAnalyser();
      hud.remove(); // disconnectedCallback also cancels the render loop
      hud = null;
    }
    await releaseAudio();
  }

  async function attachTabAudio(streamId) {
    if (!hud) return;
    await releaseAudio();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
    });
    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    source.connect(analyser);
    // Capturing a tab mutes it for the user; route it back to the speakers.
    source.connect(ctx.destination);
    audio = { ctx, stream };
    stream.getAudioTracks()[0].onended = () => {
      if (hud) hud.detachAnalyser();
      void releaseAudio();
    };
    hud.attachAnalyser(analyser);
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message && message.type === "ECHO_STREAM_ID" && typeof message.streamId === "string") {
      attachTabAudio(message.streamId).catch((err) => console.warn("[ECHO] Tab audio failed:", err));
    }
  });

  createMeetLifecycle({
    getUrl: () => location.href,
    onEnter: mountHud,
    onLeave: () => void unmountHud(),
  });
})();
