/**
 * Echo Guard - Google Meet Content Script
 * Injects non-intrusive Zero-Trust HUD, safely monitors live Google Meet captions without
 * blocking the render thread, and displays emergency barge-in alarms.
 */

(function () {
  console.log('[Echo Guard] Initializing for Google Meet...');

  let hudElement = null;
  let overlayElement = null;
  let speechRecognizer = null;
  let isVoiceRecognitionActive = false;
  let lastCaptionText = '';
  let captionDebounceTimer = null;
  let audioContext = null;
  let throttleTimer = null;
  const captionSelector = 'div[jsname="YSxPC"], div[jscontroller="D1tHje"], .bh44bd, .iTTPOb, .nMHg5';
  const captionObservers = new Map();

  function init() {
    // Delay creation slightly so Google Meet's core DOM and WebRTC can initialize smoothly
    setTimeout(() => {
      createHUD();
      setupCaptionObserver();
      listenToBackgroundMessages();
      chrome.runtime.sendMessage({ type: 'GET_STATUS' }).then(applyStatus).catch(() => updateHUDState('OFFLINE'));
    }, 1200);
  }

  /**
   * Create Floating Minimalist HUD in Google Meet
   */
  function createHUD() {
    if (document.getElementById('echo-meet-hud')) return;

    hudElement = document.createElement('div');
    hudElement.id = 'echo-meet-hud';
    hudElement.innerHTML = `
      <div class="echo-hud-shield" id="echo-hud-shield-indicator">
        <svg viewBox="0 0 24 24">
          <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/>
        </svg>
        <div class="echo-hud-pulse" id="echo-hud-pulse-dot"></div>
      </div>
      <div class="echo-hud-content">
        <div class="echo-hud-title">
          <span>Echo Guard</span>
          <span class="echo-hud-badge" id="echo-hud-status-badge">Connecting</span>
        </div>
        <div class="echo-hud-subtitle" id="echo-hud-transcript-preview">
          Checking monitoring connection · Turn on CC ('c') or Mic
        </div>
      </div>
      <div class="echo-hud-actions">
        <button class="echo-btn-icon" id="echo-btn-mic" title="Toggle Built-in Speech Recognition (🎙️)">
          🎙️
        </button>
        <button class="echo-btn-icon" id="echo-btn-sim" title="Simulate Wire Fraud Attack (⚡ Demo)">
          ⚡
        </button>
      </div>
    `;

    document.body.appendChild(hudElement);

    // Event listeners
    document.getElementById('echo-btn-mic').addEventListener('click', toggleSpeechRecognition);
    document.getElementById('echo-btn-sim').addEventListener('click', () => {
      chrome.runtime.sendMessage({ type: 'SIMULATE_CEO_ATTACK' });
    });
  }

  /**
   * Observe Google Meet Live Captions via DOM MutationObserver
   * CRITICAL: Must ignore mutations inside Echo HUD and throttle calls to prevent freezing!
   */
  function setupCaptionObserver() {
    function scheduleExtraction() {
      if (throttleTimer) return;
      throttleTimer = setTimeout(() => {
        throttleTimer = null;
        // Observe text edits only inside real caption roots. The body observer
        // discovers new roots without watching every text edit across Meet.
        for (const [node, observer] of captionObservers) {
          if (!node.isConnected) { observer.disconnect(); captionObservers.delete(node); }
        }
        for (const node of document.querySelectorAll(captionSelector)) {
          if (captionObservers.has(node)) continue;
          const observer = new MutationObserver(scheduleExtraction);
          observer.observe(node, { childList: true, subtree: true, characterData: true });
          captionObservers.set(node, observer);
        }
        extractCaptions();
      }, 400);
    }
    const observer = new MutationObserver((mutations) => {
      // 1. Filter out mutations triggered by our own extension elements to avoid infinite loops
      let hasExternalChanges = false;
      for (const m of mutations) {
        const target = m.target.nodeType === Node.ELEMENT_NODE ? m.target : m.target.parentElement;
        if (target) {
          if (target.id === 'echo-meet-hud' || target.id === 'echo-barge-in-overlay') {
            continue;
          }
          if (target.closest && (target.closest('#echo-meet-hud') || target.closest('#echo-barge-in-overlay'))) {
            continue;
          }
        }
        hasExternalChanges = true;
        break;
      }

      if (!hasExternalChanges) return;

      // 2. Throttle caption extraction so we don't block Meet's render cycle
      scheduleExtraction();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: false, // Don't watch every character change globally
    });
    scheduleExtraction();
  }

  /**
   * Extract captions from dedicated Google Meet caption containers only
   */
  function extractCaptions() {
    // Specific selectors for actual Google Meet closed caption streams
    const seen = new Set();
    for (const el of captionObservers.keys()) {
      const text = el.textContent.trim();
      if (text.length > 6 && !seen.has(text)) {
        seen.add(text);
        handleNewCaption(text);
      }
    }
  }

  /**
   * Process and debounce detected caption turn
   */
  function handleNewCaption(text, speaker = 'Google Meet Participant') {
    if (text === lastCaptionText) return;
    if (text.startsWith(lastCaptionText) && text.length - lastCaptionText.length < 5) return;

    lastCaptionText = text;
    updateSubtitlePreview(text);

    if (captionDebounceTimer) clearTimeout(captionDebounceTimer);
    captionDebounceTimer = setTimeout(() => {
      console.log('[Echo Meet] Forwarding transcript turn:', text);
      chrome.runtime.sendMessage({
        type: 'TRANSCRIPT_TURN',
        text: text,
        speaker: speaker,
      });
    }, 700);
  }

  /**
   * Built-in Web Speech API recognition fallback
   */
  function toggleSpeechRecognition() {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      alert('Speech Recognition is not supported in this browser version.');
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (isVoiceRecognitionActive && speechRecognizer) {
      speechRecognizer.stop();
      isVoiceRecognitionActive = false;
      const btn = document.getElementById('echo-btn-mic');
      if (btn) btn.style.color = '#94a3b8';
      updateSubtitlePreview('Voice Shield Paused · Turn on CC (\'c\')');
      return;
    }

    try {
      speechRecognizer = new SpeechRecognition();
      speechRecognizer.continuous = true;
      speechRecognizer.interimResults = true;
      speechRecognizer.lang = 'en-US';

      speechRecognizer.onstart = () => {
        isVoiceRecognitionActive = true;
        const btn = document.getElementById('echo-btn-mic');
        if (btn) btn.style.color = '#10b981';
        updateSubtitlePreview('Voice Shield Active · Listening to your microphone');
      };

      speechRecognizer.onresult = (event) => {
        let transcript = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        if (transcript.trim()) {
          handleNewCaption(transcript.trim(), 'Local Mic (Verified)');
        }
      };

      speechRecognizer.onerror = (err) => {
        console.warn('[Echo Meet] Speech recognition error:', err);
      };

      speechRecognizer.onend = () => {
        if (isVoiceRecognitionActive) {
          try {
            speechRecognizer.start();
          } catch (e) {
            console.debug('[Echo Meet] Speech restart notice:', e);
          }
        }
      };

      speechRecognizer.start();
    } catch (err) {
      console.error('[Echo Meet] Failed to start SpeechRecognition:', err);
    }
  }

  /**
   * Update HUD Subtitle Preview Text safely
   */
  function updateSubtitlePreview(text) {
    const preview = document.getElementById('echo-hud-transcript-preview');
    if (preview) {
      preview.textContent = text;
      preview.title = text;
    }
  }

  /**
   * Update HUD State (Safe, Analyzing, Alert)
   */
  function updateHUDState(status, score = 0) {
    const badge = document.getElementById('echo-hud-status-badge');
    const pulse = document.getElementById('echo-hud-pulse-dot');
    if (!badge || !pulse) return;

    if (status === 'OFFLINE' || status === 'CONNECTING') {
      badge.textContent = status;
      badge.style.background = 'rgba(100, 116, 139, 0.25)';
      badge.style.color = '#cbd5e1';
      pulse.style.background = '#94a3b8';
      pulse.style.boxShadow = 'none';
    } else if (status === 'ALERT' || score >= 0.85) {
      badge.textContent = `ALERT ${Math.round(score * 100)}%`;
      badge.style.background = 'rgba(239, 68, 68, 0.25)';
      badge.style.color = '#f87171';
      pulse.style.background = '#ef4444';
      pulse.style.boxShadow = '0 0 10px #ef4444';
    } else if (status === 'SUSPICIOUS' || score >= 0.6) {
      badge.textContent = `SUSPICIOUS ${Math.round(score * 100)}%`;
      badge.style.background = 'rgba(245, 158, 11, 0.25)';
      badge.style.color = '#fbbf24';
      pulse.style.background = '#f59e0b';
      pulse.style.boxShadow = '0 0 8px #f59e0b';
    } else {
      badge.textContent = 'SECURE';
      badge.style.background = 'rgba(16, 185, 129, 0.2)';
      badge.style.color = '#34d399';
      pulse.style.background = '#10b981';
      pulse.style.boxShadow = '0 0 8px #10b981';
    }
  }

  /**
   * Trigger Audio Siren Tone
   */
  function playEmergencyTone() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!audioContext) audioContext = new AudioCtx();
      if (audioContext.state === 'suspended') audioContext.resume();

      const osc = audioContext.createOscillator();
      const gain = audioContext.createGain();

      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(800, audioContext.currentTime);
      osc.frequency.exponentialRampToValueAtTime(400, audioContext.currentTime + 0.3);
      osc.frequency.exponentialRampToValueAtTime(800, audioContext.currentTime + 0.6);

      gain.gain.setValueAtTime(0.15, audioContext.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.7);

      osc.connect(gain);
      gain.connect(audioContext.destination);

      osc.start();
      osc.stop(audioContext.currentTime + 0.7);
    } catch (e) {
      console.debug('[Echo Meet] Audio tone suppressed:', e);
    }
  }

  /**
   * Vocal Speech Warning
   */
  function speakWarning(text) {
    if ('speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.05;
        utterance.pitch = 1.0;
        window.speechSynthesis.speak(utterance);
      } catch (e) {
        console.debug('[Echo Meet] Speech warning notice:', e);
      }
    }
  }

  /**
   * Render Emergency Barge-in Overlay right on top of Google Meet
   */
  function showEmergencyOverlay(alert) {
    if (document.getElementById('echo-barge-in-overlay')) return;

    updateHUDState('ALERT', alert.risk_score || 0.95);
    playEmergencyTone();
    speakWarning('Security Alert: Coercive wire transfer request intercepted. Corporate Treasury API has been locked.');

    overlayElement = document.createElement('div');
    overlayElement.id = 'echo-barge-in-overlay';

    const tactics = alert.matched_tactics && alert.matched_tactics.length > 0
      ? alert.matched_tactics.map(t => `<span class="echo-tactic-tag">${t}</span>`).join('')
      : '<span class="echo-tactic-tag">BYPASS_FOUR_EYES</span><span class="echo-tactic-tag">AUTHORITY_INTIMIDATION</span>';

    const triggerQuote = alert.trigger_text || "Wire $25.6M immediately... Waived by executive order. Do NOT verify.";

    overlayElement.innerHTML = `
      <div class="echo-overlay-card">
        <div class="echo-overlay-stripe"></div>
        
        <div class="echo-overlay-header">
          <div class="echo-overlay-alarm-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/>
              <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
          </div>
          <div class="echo-overlay-title-group">
            <h2>🚨 Echo Zero-Trust Fraud Defense Interception</h2>
            <p>Real-time Coercion & BEC Wire Fraud Intercepted by Gemini Security Model</p>
          </div>
        </div>

        <div class="echo-overlay-risk-meter">
          <div>
            <div style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 600;">Threat Assessment</div>
            <div style="font-size: 14px; font-weight: 600; color: #f87171;">CRITICAL FRAUD ATTEMPT</div>
          </div>
          <div class="risk-val">${Math.round((alert.risk_score || 0.95) * 100)}% RISK</div>
        </div>

        <div style="font-size: 12px; font-weight: 600; color: #cbd5e1; margin-bottom: 8px;">Intercepted Coercion Tactics:</div>
        <div class="echo-overlay-tactics">
          ${tactics}
        </div>

        <div class="echo-overlay-quote">
          "${triggerQuote}"
        </div>

        <div style="font-size: 12px; color: #94a3b8; margin-bottom: 24px; display: flex; align-items: center; gap: 8px;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#ef4444;"></span>
          Corporate Treasury API (#TX-2026-ARUP88) frozen via <strong>CAEP RFC 9493</strong>.
        </div>

        <div class="echo-overlay-actions">
          <button class="echo-btn-secondary" id="echo-btn-dismiss">
            Dismiss call alert
          </button>
          <button class="echo-btn-primary" id="echo-btn-open-treasury">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
            Inspect Treasury Lock
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(overlayElement);

    // Overlay button actions
    document.getElementById('echo-btn-dismiss').addEventListener('click', () => {
      chrome.runtime.sendMessage({
        type: 'DISMISS_ALERT',
        reason: 'Meeting host cleared alarm as false positive',
      });
    });

    document.getElementById('echo-btn-open-treasury').addEventListener('click', () => {
      window.open('http://localhost:3000/transfer', '_blank');
    });
  }

  function dismissEmergencyOverlay() {
    const el = document.getElementById('echo-barge-in-overlay');
    if (el) el.remove();
    updateHUDState('NORMAL', 0);
    updateSubtitlePreview('Call alert cleared · Bank release requires verification in Treasury');
  }

  function applyStatus(status) {
    if (status.lastAlert) { showEmergencyOverlay(status.lastAlert); return; }
    if (document.getElementById('echo-barge-in-overlay')) dismissEmergencyOverlay();
    updateHUDState(status.connectionStatus === 'connected' ? 'NORMAL'
      : status.connectionStatus === 'connecting' ? 'CONNECTING' : 'OFFLINE', status.currentRiskScore || 0);
  }

  /**
   * Listen for events dispatched from Background Service Worker
   */
  function listenToBackgroundMessages() {
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
      console.log('[Echo Meet] Inbound background message:', message);

      if (message.type === 'ECHO_SECURITY_ALERT') {
        showEmergencyOverlay(message.alert);
        sendResponse({ received: true });
      } else if (message.type === 'ECHO_RISK_UPDATE' && !document.getElementById('echo-barge-in-overlay')) {
        updateHUDState(message.status, message.risk_score);
        sendResponse({ received: true });
      } else if (message.type === 'ECHO_ALERT_DISMISSED') {
        dismissEmergencyOverlay();
        sendResponse({ received: true });
      } else if (message.type === 'ECHO_MOCK_CAPTION') {
        updateSubtitlePreview(`${message.speaker}: "${message.text}"`);
        sendResponse({ received: true });
      } else if (message.type === 'ECHO_STATUS_UPDATE') {
        applyStatus(message.status);
        sendResponse({ received: true });
      }
    });
  }

  // Start initialization smoothly
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
