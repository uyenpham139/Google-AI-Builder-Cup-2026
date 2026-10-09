// Clicking the toolbar icon grants activeTab and lets us ask Chrome for a
// capture id for that tab. The content script on the page consumes it.
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id) return;
  try {
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id, consumerTabId: tab.id });
    await chrome.tabs.sendMessage(tab.id, { type: "ECHO_STREAM_ID", streamId });
  } catch (err) {
    console.warn("[ECHO] Could not start tab capture:", err);
  }
});
