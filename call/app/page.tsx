'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Mic,
  MicOff,
  PhoneOff,
  Phone,
  Play,
  ShieldCheck,
  ShieldAlert,
  Shield,
  X,
  Users,
  Copy,
  Check,
  Volume2,
  Send,
  Sparkles,
  MessageSquare,
  Repeat,
  Puzzle,
  Settings,
  SlidersHorizontal,
  Video,
  CheckCircle2,
  Cpu,
  Lock,
  Key
} from 'lucide-react';
import { API_URL, BARGE_IN_MESSAGE, CALLER, SCENARIOS, SELF, Scenario, WS_URL } from '@/lib/config';

type Guard = 'safe' | 'analyzing' | 'suspicious' | 'alert' | 'disabled';
type Caption = { id: number; text: string; speaker: string; interim?: boolean };
type Role = 'caller' | 'callee';
type SidePanel = 'none' | 'chat' | 'people' | 'scenarios';
type SettingsTab = 'echo' | 'audio' | 'video' | 'general';
type RiskSensitivity = 'standard' | 'strict' | 'relaxed';

interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

const GUARD_UI: Record<Guard, { label: string; cls: string; dot: string; Icon: typeof Shield }> = {
  safe: { label: 'Secure', cls: 'bg-emerald-950/80 border-emerald-500/30 text-emerald-400', dot: 'bg-emerald-400', Icon: ShieldCheck },
  analyzing: { label: 'Analyzing', cls: 'bg-slate-800/80 border-slate-600/30 text-slate-300', dot: 'bg-blue-400 animate-pulse', Icon: Shield },
  suspicious: { label: 'Suspicious', cls: 'bg-amber-950/80 border-amber-500/30 text-amber-300', dot: 'bg-amber-400 animate-ping', Icon: ShieldAlert },
  alert: { label: 'Fraud Detected', cls: 'bg-red-950/80 border-red-500/40 text-red-300', dot: 'bg-red-500 animate-ping', Icon: ShieldAlert },
  disabled: { label: 'Disabled', cls: 'bg-slate-900/80 border-white/10 text-slate-400', dot: 'bg-slate-500', Icon: Shield },
};

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function speak(text: string, opts: { rate?: number; voiceId?: string } = {}): Promise<void> {
  if (typeof window === 'undefined') return;

  const elevenLabsKey =
    localStorage.getItem('echo_elevenlabs_key')?.trim() ||
    process.env.NEXT_PUBLIC_ELEVENLABS_API_KEY?.trim();
  const voiceId =
    localStorage.getItem('echo_elevenlabs_voice_id') ||
    opts.voiceId ||
    process.env.NEXT_PUBLIC_ELEVENLABS_VOICE_ID?.trim() ||
    'pNInz6obpgDQGcFmaJgB'; // Adam

  // =========================================================================
  // TIER 1: ElevenLabs Ultra-Realistic AI Voice (Priority 1)
  // =========================================================================
  if (elevenLabsKey) {
    try {
      console.log('[TTS Engine] Tier 1: Attempting ElevenLabs voice synthesis...');
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 4500); // 4.5s timeout guard

      const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`, {
        method: 'POST',
        headers: {
          'xi-api-key': elevenLabsKey,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          text,
          model_id: 'eleven_turbo_v2_5',
          voice_settings: {
            stability: 0.45,
            similarity_boost: 0.85,
            style: 0.35,
            use_speaker_boost: true,
          },
        }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        return new Promise((resolve) => {
          audio.onended = () => {
            URL.revokeObjectURL(url);
            resolve();
          };
          audio.onerror = () => {
            URL.revokeObjectURL(url);
            resolve();
          };
          audio.play().catch(() => resolve());
        });
      } else {
        const errText = await res.text().catch(() => '');
        console.warn(`[TTS Engine] Tier 1 (ElevenLabs) HTTP ${res.status}: ${errText}. Falling back to Tier 2...`);
      }
    } catch (e) {
      console.warn('[TTS Engine] Tier 1 (ElevenLabs) failed or timed out:', e, '-> Falling back to Tier 2 (Google Voice)...');
    }
  }

  // =========================================================================
  // Web Speech Helper for Tier 2 and Tier 3
  // =========================================================================
  const speakWithVoice = (chosenVoice: SpeechSynthesisVoice | null, tierName: string): Promise<boolean> => {
    return new Promise((resolve) => {
      if (!('speechSynthesis' in window)) return resolve(false);
      try {
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.lang = 'en-US';
        u.rate = opts.rate ?? 1.05;

        if (chosenVoice) {
          u.voice = chosenVoice;
          console.log(`[TTS Engine] ${tierName}: Playing via voice "${chosenVoice.name}" (${chosenVoice.lang})`);
        }

        let resolved = false;
        const done = (success: boolean) => {
          if (!resolved) {
            resolved = true;
            resolve(success);
          }
        };

        u.onend = () => done(true);
        u.onerror = (err) => {
          console.warn(`[TTS Engine] ${tierName} playback error:`, err);
          done(false);
        };
        setTimeout(() => done(true), Math.max(3000, text.length * 85));
        window.speechSynthesis.speak(u);
      } catch (err) {
        console.warn(`[TTS Engine] ${tierName} exception:`, err);
        resolve(false);
      }
    });
  };

  // Ensure browser voices are loaded
  let voices = window.speechSynthesis?.getVoices() || [];
  if (voices.length === 0 && 'speechSynthesis' in window) {
    await new Promise((r) => {
      const onVoices = () => {
        voices = window.speechSynthesis.getVoices();
        window.speechSynthesis.removeEventListener('voiceschanged', onVoices);
        r(null);
      };
      window.speechSynthesis.addEventListener('voiceschanged', onVoices);
      setTimeout(r, 200);
    });
    voices = window.speechSynthesis?.getVoices() || [];
  }

  // =========================================================================
  // TIER 2: Google Natural Voice (High-Fidelity Neural Fallback)
  // =========================================================================
  const googleVoice = voices.find(
    (v) => (v.name.includes('Google') || v.name.includes('Natural')) && (v.lang.startsWith('en') || v.lang.startsWith('vi'))
  );

  if (googleVoice) {
    const success = await speakWithVoice(googleVoice, 'Tier 2 (Google Voice)');
    if (success) return;
    console.warn('[TTS Engine] Tier 2 (Google Voice) playback failed. Falling back to Tier 3 (Classic Robot Voice)...');
  } else {
    console.warn('[TTS Engine] No Google Voice detected in browser. Falling back to Tier 3 (Classic Robot Voice)...');
  }

  // =========================================================================
  // TIER 3: Classic Robot / System Offline Voice (Guaranteed Fallback)
  // =========================================================================
  const robotVoice =
    voices.find((v) => !v.name.includes('Google') && (v.name.includes('David') || v.name.includes('Zira') || v.name.includes('Desktop') || v.name.includes('Sam'))) ||
    voices.find((v) => v.lang.startsWith('en')) ||
    voices[0] ||
    null;

  await speakWithVoice(robotVoice, 'Tier 3 (Classic Robot Voice)');
}

function playTestChime() {
  try {
    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextClass) return;
    const ctx = new AudioContextClass();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(587.33, ctx.currentTime);
    osc.frequency.setValueAtTime(880, ctx.currentTime + 0.12);
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.4);
  } catch {
    speak('Speaker audio test successful.');
  }
}

export default function CallPage() {
  const [inCall, setInCall] = useState(true);
  const [role, setRole] = useState<Role>('callee'); // Callee = Alex Chen (Treasury Controller), Caller = Robert Higgins (CEO)
  const [isEchoActive, setIsEchoActive] = useState(true); // PLUGIN SWITCH: Guard ON/OFF
  const [sidePanel, setSidePanel] = useState<SidePanel>('none');
  const [pluginMenuOpen, setPluginMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsTab>('echo');

  // Meeting Settings & Defaults
  const [defaultEchoActive, setDefaultEchoActive] = useState(true);
  const [autoLockBanking, setAutoLockBanking] = useState(true);
  const [voiceBargeInAlert, setVoiceBargeInAlert] = useState(true);
  const [riskSensitivity, setRiskSensitivity] = useState<RiskSensitivity>('standard');
  const [noiseCancellation, setNoiseCancellation] = useState(true);
  const [elevenLabsApiKey, setElevenLabsApiKey] = useState('');
  const [elevenLabsVoiceId, setElevenLabsVoiceId] = useState('pNInz6obpgDQGcFmaJgB');

  const [connected, setConnected] = useState(false);
  const [peerCount, setPeerCount] = useState(1);
  const [guard, setGuard] = useState<Guard>('safe');
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [speaking, setSpeaking] = useState(false);
  const [aiThinking, setAiThinking] = useState(false);
  const [micOn, setMicOn] = useState(false);
  const [remoteAudioActive, setRemoteAudioActive] = useState(false);
  const [running, setRunning] = useState(false);
  const [bargeIn, setBargeIn] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);
  const [clock, setClock] = useState('');
  const [customInput, setCustomInput] = useState('');
  const [conversationHistory, setConversationHistory] = useState<{ speaker: string; text: string; time: string }[]>([]);
  const conversationHistoryRef = useRef<{ speaker: string; text: string; time: string }[]>([]);
  const triggerAiResponseRef = useRef<(userText: string) => Promise<void>>(async () => {});

  const wsRef = useRef<WebSocket | null>(null);
  const signalingWsRef = useRef<WebSocket | null>(null);
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const recRef = useRef<Recognition | null>(null);
  const runIdRef = useRef(0);
  const captionId = useRef(0);
  const speakTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bargedRef = useRef(false);
  const lastUserSpeechRef = useRef<string>('');
  const pluginMenuRef = useRef<HTMLDivElement | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);

  // Load preferences from localStorage on mount
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const urlRole = params.get('role');
      if (urlRole === 'caller' || urlRole === 'callee') {
        setRole(urlRole);
      }

      const savedDefault = localStorage.getItem('echo_default_guard_active');
      if (savedDefault !== null) {
        const val = savedDefault === 'true';
        setDefaultEchoActive(val);
        setIsEchoActive(val);
      }
      const savedAutoLock = localStorage.getItem('echo_auto_lock_banking');
      if (savedAutoLock !== null) setAutoLockBanking(savedAutoLock === 'true');
      const savedBargeIn = localStorage.getItem('echo_voice_barge_in');
      if (savedBargeIn !== null) setVoiceBargeInAlert(savedBargeIn === 'true');
      const savedSensitivity = localStorage.getItem('echo_risk_sensitivity') as RiskSensitivity | null;
      if (savedSensitivity) setRiskSensitivity(savedSensitivity);
      const savedKey = localStorage.getItem('echo_elevenlabs_key') || process.env.NEXT_PUBLIC_ELEVENLABS_API_KEY || '';
      if (savedKey) setElevenLabsApiKey(savedKey);
      const savedVoice = localStorage.getItem('echo_elevenlabs_voice_id') || process.env.NEXT_PUBLIC_ELEVENLABS_VOICE_ID || 'pNInz6obpgDQGcFmaJgB';
      if (savedVoice) setElevenLabsVoiceId(savedVoice);
    }
  }, []);

  // Close plugin popover when clicking outside
  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (pluginMenuRef.current && !pluginMenuRef.current.contains(e.target as Node)) {
        setPluginMenuOpen(false);
      }
    };
    if (pluginMenuOpen) {
      document.addEventListener('mousedown', handleOutsideClick);
      return () => document.removeEventListener('mousedown', handleOutsideClick);
    }
  }, [pluginMenuOpen]);

  // Clean clock
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      setClock(`${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`);
    };
    tick();
    const t = setInterval(tick, 15000);
    return () => clearInterval(t);
  }, []);

  // Auto-scroll chat drawer
  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [conversationHistory]);

  const pushCaption = useCallback((text: string, speakerName: string, interim = false) => {
    setCaptions((prev) => {
      const base = prev.length && prev[prev.length - 1].interim ? prev.slice(0, -1) : prev;
      return [...base, { id: ++captionId.current, text, speaker: speakerName, interim }].slice(-2);
    });
  }, []);

  const markSpeaking = useCallback((ms = 1200) => {
    setSpeaking(true);
    if (speakTimer.current) clearTimeout(speakTimer.current);
    speakTimer.current = setTimeout(() => setSpeaking(false), ms);
  }, []);

  const triggerBargeIn = useCallback(() => {
    if (bargedRef.current || !isEchoActive) return;
    bargedRef.current = true;
    runIdRef.current++;
    setRunning(false);
    setAiThinking(false);
    setBargeIn(true);
    window.speechSynthesis?.cancel();
    setSpeaking(false);
    if (voiceBargeInAlert) {
      speak(BARGE_IN_MESSAGE, { rate: 1 });
    }
  }, [isEchoActive, voiceBargeInAlert]);

  // WebSocket to Echo Backend (/ws/call)
  useEffect(() => {
    if (!inCall) return;
    let alive = true;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      const ws = new WebSocket(`${WS_URL}/ws/call`);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (alive) retry = setTimeout(connect, 2000);
      };
      ws.onmessage = (event) => {
        let d: Record<string, unknown>;
        try {
          d = JSON.parse(event.data);
        } catch {
          return;
        }

        if (!isEchoActive) {
          setGuard('disabled');
          return;
        }

        if (bargedRef.current && d.type !== 'ALERT_DISMISSED') return;

        switch (d.type) {
          case 'STATUS_OK':
            setGuard((g) => (g === 'analyzing' ? 'safe' : g));
            break;
          case 'TIER1_TRIGGERED':
            setGuard((g) => (g === 'safe' ? 'analyzing' : g));
            break;
          case 'RISK_UPDATE':
          case 'SECURITY_ALERT':
            if (d.action === 'TRIGGER_BARGE_IN_AND_LOCK') {
              setGuard('alert');
              triggerBargeIn();
            } else if (d.status === 'OVERRIDDEN_DISMISSED' || d.status === 'NORMAL') {
              setGuard('safe');
            } else {
              setGuard('suspicious');
            }
            break;
          case 'ALERT_DISMISSED':
            bargedRef.current = false;
            setBargeIn(false);
            setGuard('safe');
            break;
        }
      };
    };

    connect();
    return () => {
      alive = false;
      if (retry) clearTimeout(retry);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [inCall, triggerBargeIn, isEchoActive]);

  const sendTranscriptToEcho = useCallback(
    (text: string, speakerName: string) => {
      if (!isEchoActive) return;
      const ws = wsRef.current;
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'transcript', text, speaker: speakerName }));
      }
    },
    [isEchoActive]
  );

  // WebRTC peer connection
  useEffect(() => {
    if (!inCall) return;

    let pc: RTCPeerConnection;
    let sigWs: WebSocket;

    const setupWebRTC = () => {
      pc = new RTCPeerConnection({
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' },
          { urls: 'stun:stun1.l.google.com:19302' },
        ],
      });
      peerConnectionRef.current = pc;

      pc.ontrack = (event) => {
        if (remoteAudioRef.current && event.streams[0]) {
          remoteAudioRef.current.srcObject = event.streams[0];
          setRemoteAudioActive(true);
        }
      };

      pc.onicecandidate = (event) => {
        if (event.candidate && sigWs.readyState === WebSocket.OPEN) {
          sigWs.send(JSON.stringify({ type: 'ICE_CANDIDATE', candidate: event.candidate }));
        }
      };

      sigWs = new WebSocket(`${WS_URL}/ws/signaling/echo-call-room`);
      signalingWsRef.current = sigWs;

      sigWs.onmessage = async (event) => {
        try {
          const msg = JSON.parse(event.data);

          if (msg.type === 'PEER_JOINED') {
            setPeerCount(msg.peer_count || 1);
            if (role === 'caller' && msg.peer_count >= 2) {
              const offer = await pc.createOffer();
              await pc.setLocalDescription(offer);
              sigWs.send(JSON.stringify({ type: 'SDP_OFFER', sdp: offer }));
            }
          } else if (msg.type === 'PEER_LEFT') {
            setPeerCount(msg.peer_count || 1);
            setRemoteAudioActive(false);
          } else if (msg.type === 'SDP_OFFER') {
            await pc.setRemoteDescription(new RTCSessionDescription(msg.sdp));
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            sigWs.send(JSON.stringify({ type: 'SDP_ANSWER', sdp: answer }));
          } else if (msg.type === 'SDP_ANSWER') {
            await pc.setRemoteDescription(new RTCSessionDescription(msg.sdp));
          } else if (msg.type === 'ICE_CANDIDATE') {
            if (msg.candidate) {
              await pc.addIceCandidate(new RTCIceCandidate(msg.candidate));
            }
          } else if (msg.type === 'REMOTE_TRANSCRIPT') {
            pushCaption(msg.text, msg.speaker);
            sendTranscriptToEcho(msg.text, msg.speaker);
            markSpeaking();
          }
        } catch (e) {
          console.error('Signaling error:', e);
        }
      };
    };

    setupWebRTC();

    return () => {
      if (sigWs) sigWs.close();
      if (pc) pc.close();
    };
  }, [inCall, role, pushCaption, sendTranscriptToEcho, markSpeaking]);

  // AI Roleplay response trigger (Real-time dynamic Gemini 3.5 response)
  const triggerAiResponse = useCallback(
    async (userText: string) => {
      if (!userText.trim()) return;
      setAiThinking(true);

      const aiRole = role === 'callee' ? 'caller' : 'callee';
      const aiSpeakerName = aiRole === 'caller' ? CALLER.name : SELF.name;
      const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      try {
        const historyToSend = conversationHistoryRef.current.slice(-8).map((h) => ({ speaker: h.speaker, text: h.text }));
        const res = await fetch(`${API_URL}/api/call/roleplay/reply`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            user_message: userText,
            role: aiRole,
            history: historyToSend,
          }),
        });

        if (!res.ok) throw new Error('Roleplay API error');
        const data = await res.json();
        const replyText = data.reply;

        const updated = [
          ...conversationHistoryRef.current,
          { speaker: role === 'callee' ? SELF.name : CALLER.name, text: userText, time: nowStr },
          { speaker: aiSpeakerName, text: replyText, time: nowStr },
        ];
        conversationHistoryRef.current = updated;
        setConversationHistory(updated);

        pushCaption(replyText, aiSpeakerName);
        sendTranscriptToEcho(replyText, aiSpeakerName);

        setAiThinking(false);
        setSpeaking(true);
        await speak(replyText);
        setSpeaking(false);
      } catch (err) {
        console.error('AI Roleplay reply failed:', err);
        setAiThinking(false);
        setSpeaking(false);
      }
    },
    [role, pushCaption, sendTranscriptToEcho]
  );

  useEffect(() => {
    triggerAiResponseRef.current = triggerAiResponse;
  }, [triggerAiResponse]);

  // Auto-greeting from AI partner upon call start
  const startAiRoleplayCall = useCallback(async () => {
    try {
      setAiThinking(true);
      const aiRole = role === 'callee' ? 'caller' : 'callee';
      const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      const res = await fetch(`${API_URL}/api/call/roleplay/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: aiRole }),
      });
      if (res.ok) {
        const data = await res.json();
        const greeting = data.greeting;
        const speaker = data.speaker;
        const initial = [{ speaker, text: greeting, time: nowStr }];
        conversationHistoryRef.current = initial;
        setConversationHistory(initial);
        pushCaption(greeting, speaker);
        sendTranscriptToEcho(greeting, speaker);
        setAiThinking(false);
        setSpeaking(true);
        await speak(greeting);
        setSpeaking(false);
      }
    } catch {
      setAiThinking(false);
      setSpeaking(false);
    }
  }, [role, pushCaption, sendTranscriptToEcho]);

  useEffect(() => {
    if (inCall && conversationHistory.length === 0) {
      const timer = setTimeout(() => {
        startAiRoleplayCall();
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [inCall, conversationHistory.length, startAiRoleplayCall]);

  // Mic toggle - Natural Speech to Speech
  const toggleMic = async () => {
    if (micOn) {
      if (localStreamRef.current) {
        localStreamRef.current.getTracks().forEach((t) => t.stop());
        localStreamRef.current = null;
      }
      recRef.current?.stop();
      recRef.current = null;
      setMicOn(false);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      localStreamRef.current = stream;

      if (peerConnectionRef.current) {
        const audioTrack = stream.getAudioTracks()[0];
        const sender = peerConnectionRef.current.getSenders().find((s) => s.track?.kind === 'audio');
        if (sender) {
          sender.replaceTrack(audioTrack);
        } else {
          peerConnectionRef.current.addTrack(audioTrack, stream);
        }

        if (role === 'caller' && signalingWsRef.current?.readyState === WebSocket.OPEN) {
          const offer = await peerConnectionRef.current.createOffer();
          await peerConnectionRef.current.setLocalDescription(offer);
          signalingWsRef.current.send(JSON.stringify({ type: 'SDP_OFFER', sdp: offer }));
        }
      }

      setMicOn(true);

      const w = window as unknown as {
        SpeechRecognition?: new () => Recognition;
        webkitSpeechRecognition?: new () => Recognition;
      };
      const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
      if (Ctor) {
        const rec = new Ctor();
        rec.lang = 'en-US'; // 100% English speech recognition
        rec.continuous = true;
        rec.interimResults = true;
        rec.onresult = (e) => {
          for (let i = e.resultIndex; i < e.results.length; i++) {
            const r = e.results[i];
            const text = r[0].transcript.trim();
            if (!text) continue;
            const currentSpeakerName = role === 'caller' ? CALLER.name : SELF.name;

            if (r.isFinal) {
              if (text === lastUserSpeechRef.current) continue;
              lastUserSpeechRef.current = text;

              pushCaption(text, currentSpeakerName);

              if (signalingWsRef.current?.readyState === WebSocket.OPEN) {
                signalingWsRef.current.send(
                  JSON.stringify({ type: 'REMOTE_TRANSCRIPT', text, speaker: currentSpeakerName })
                );
              }

              sendTranscriptToEcho(text, currentSpeakerName);
              triggerAiResponseRef.current(text);
            } else {
              pushCaption(text, currentSpeakerName, true);
            }
          }
        };
        rec.onend = () => {
          if (recRef.current === rec && micOn) rec.start();
        };
        recRef.current = rec;
        rec.start();
      }
    } catch (err) {
      alert(`Unable to access microphone: ${err}`);
      setMicOn(false);
    }
  };

  const handleUserSendMessage = (msgText: string) => {
    if (!msgText.trim()) return;
    const currentSpeakerName = role === 'caller' ? CALLER.name : SELF.name;
    pushCaption(msgText, currentSpeakerName);
    sendTranscriptToEcho(msgText, currentSpeakerName);
    triggerAiResponse(msgText);

    if (signalingWsRef.current?.readyState === WebSocket.OPEN) {
      signalingWsRef.current.send(
        JSON.stringify({ type: 'REMOTE_TRANSCRIPT', text: msgText, speaker: currentSpeakerName })
      );
    }
    setCustomInput('');
  };

  const runScenario = async (s: Scenario) => {
    setSidePanel('none');
    const runId = ++runIdRef.current;
    setRunning(true);
    window.speechSynthesis?.cancel();

    for (const line of s.lines) {
      if (runIdRef.current !== runId) return;
      pushCaption(line, CALLER.name);
      sendTranscriptToEcho(line, CALLER.name);
      if (signalingWsRef.current?.readyState === WebSocket.OPEN) {
        signalingWsRef.current.send(
          JSON.stringify({ type: 'REMOTE_TRANSCRIPT', text: line, speaker: CALLER.name })
        );
      }
      const minDuration = Math.max(1800, line.length * 55);
      setSpeaking(true);
      await Promise.all([speak(line), delay(minDuration)]);
      setSpeaking(false);
      if (runIdRef.current !== runId) return;
      await delay(500);
    }
    if (runIdRef.current === runId) setRunning(false);
  };

  const copyRoomLink = () => {
    const targetRole = role === 'callee' ? 'caller' : 'callee';
    const url = `${window.location.origin}${window.location.pathname}?role=${targetRole}`;
    navigator.clipboard.writeText(url);
    setCopiedLink(true);
    setTimeout(() => setCopiedLink(false), 2000);
  };

  const toggleEchoActive = () => {
    const next = !isEchoActive;
    setIsEchoActive(next);
    if (!next) {
      setGuard('disabled');
      setBargeIn(false);
    } else {
      setGuard('safe');
    }
  };

  const handleToggleDefaultEcho = (next: boolean) => {
    setDefaultEchoActive(next);
    localStorage.setItem('echo_default_guard_active', String(next));
  };

  const handleToggleAutoLock = (next: boolean) => {
    setAutoLockBanking(next);
    localStorage.setItem('echo_auto_lock_banking', String(next));
  };

  const handleToggleVoiceBargeIn = (next: boolean) => {
    setVoiceBargeInAlert(next);
    localStorage.setItem('echo_voice_barge_in', String(next));
  };

  const handleChangeSensitivity = (val: RiskSensitivity) => {
    setRiskSensitivity(val);
    localStorage.setItem('echo_risk_sensitivity', val);
  };

  const handleSaveElevenLabsKey = (key: string) => {
    setElevenLabsApiKey(key);
    localStorage.setItem('echo_elevenlabs_key', key);
  };

  const handleSaveElevenLabsVoice = (voiceId: string) => {
    setElevenLabsVoiceId(voiceId);
    localStorage.setItem('echo_elevenlabs_voice_id', voiceId);
  };

  const endCall = () => {
    runIdRef.current++;
    recRef.current?.stop();
    recRef.current = null;
    localStreamRef.current?.getTracks().forEach((t) => t.stop());
    window.speechSynthesis?.cancel();
    setMicOn(false);
    setRunning(false);
    setSpeaking(false);
    setAiThinking(false);
    setCaptions([]);
    setBargeIn(false);
    bargedRef.current = false;
    setGuard('safe');
    setInCall(false);
  };

  if (!inCall) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-5 bg-[#202124] text-white">
        <div className="text-xl font-medium text-slate-200">The call has ended</div>
        <button
          onClick={() => {
            setInCall(true);
            setConversationHistory([]);
          }}
          className="h-10 px-6 rounded-full bg-[#8ab4f8] text-[#202124] text-sm font-semibold inline-flex items-center gap-2 hover:bg-[#aecbfa] cursor-pointer shadow-md"
        >
          <Phone className="h-4 w-4" />
          Rejoin Call
        </button>
      </div>
    );
  }

  const g = isEchoActive ? GUARD_UI[guard] : GUARD_UI['disabled'];

  return (
    <div className="h-full flex flex-col bg-[#202124] text-[#e8eaed] relative overflow-hidden select-none font-sans">
      <audio ref={remoteAudioRef} autoPlay playsInline />

      {/* ========================================================================= */}
      {/* 1. BARGE-IN ALARM BANNER (MINIMAL & IMPACTFUL)                             */}
      {/* ========================================================================= */}
      {bargeIn && isEchoActive && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-40 w-[min(620px,92vw)] rounded-xl bg-[#d93025] text-white px-4 py-3 shadow-2xl flex items-center justify-between gap-3 animate-in fade-in slide-in-from-top-2 border border-red-400">
          <div className="flex items-center gap-3">
            <ShieldAlert className="h-5 w-5 shrink-0 animate-bounce" />
            <div className="text-xs leading-snug">
              <span className="font-bold">Financial Coercion Detected:</span> Corporate wire portal locked automatically to protect treasury assets (CAEP RFC 9493).
            </div>
          </div>
          <button
            onClick={() => setBargeIn(false)}
            className="p-1 rounded-full hover:bg-white/20 cursor-pointer text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* ========================================================================= */}
      {/* 2. MAIN STAGE: VIDEO GRID + FLOATING SECURITY BADGE                       */}
      {/* ========================================================================= */}
      <div className="flex-1 relative p-3 pb-0 flex overflow-hidden">
        <div className="flex-1 relative flex overflow-hidden rounded-2xl bg-[#303134]">
          {/* Main Remote / Partner Video Tile */}
          <div
            className={`flex-1 relative flex items-center justify-center overflow-hidden transition-all ${
              guard === 'alert' && isEchoActive ? 'ring-2 ring-[#d93025]' : ''
            }`}
          >
            {/* Center Avatar */}
            <div className="relative flex flex-col items-center">
              {speaking && (
                <span className="speaking-ring absolute inset-0 -m-3 rounded-full bg-[#8ab4f8] opacity-75 animate-ping" />
              )}
              <div
                className={`relative h-36 w-36 rounded-full flex items-center justify-center text-4xl font-semibold text-white shadow-xl transition-all ${
                  speaking ? 'scale-105 bg-[#5e35b1]' : 'bg-[#7b5ea7]'
                }`}
              >
                {role === 'callee' ? 'RH' : 'AC'}
              </div>

              {aiThinking && (
                <div className="mt-3 px-3 py-1 rounded-full bg-slate-900/80 backdrop-blur-sm text-slate-300 text-xs flex items-center gap-1.5 border border-white/10 animate-pulse">
                  <Sparkles className="h-3 w-3 text-blue-400" />
                  <span>Thinking & Replying...</span>
                </div>
              )}
            </div>

            {/* Bottom-Left Participant Name Tag (Google Meet style) */}
            <div className="absolute left-4 bottom-4 text-xs font-medium text-white/90 bg-black/50 backdrop-blur-sm px-2.5 py-1 rounded-md flex items-center gap-1.5">
              <span>{role === 'callee' ? CALLER.name : SELF.name}</span>
              <span className="text-white/50">•</span>
              <span className="text-white/60">{role === 'callee' ? CALLER.role : SELF.role}</span>
              {remoteAudioActive && (
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              )}
            </div>

            {/* Top-Right: Minimalist Echo Guard Status Badge */}
            <div className="absolute right-4 top-4 z-20">
              <button
                onClick={() => {
                  setPluginMenuOpen(true);
                  setSidePanel('none');
                }}
                className={`h-8 px-3 rounded-full text-xs font-medium inline-flex items-center gap-2 backdrop-blur-md transition-all cursor-pointer border shadow-sm ${g.cls}`}
                title="Click to view status or configure Echo Guard Add-on"
              >
                <g.Icon className="h-3.5 w-3.5" />
                <span>Echo Guard: {connected ? g.label : 'Offline'}</span>
                <span className={`h-2 w-2 rounded-full ${g.dot}`} />
              </button>
            </div>

            {/* Bottom-Right Self-View PiP */}
            <div className="absolute right-4 bottom-4 w-44 aspect-video rounded-xl bg-[#202124] border border-white/10 flex items-center justify-center shadow-lg overflow-hidden">
              <div className="h-10 w-10 rounded-full bg-[#1a73e8] flex items-center justify-center text-sm font-semibold text-white">
                {role === 'caller' ? CALLER.initials : SELF.initials}
              </div>
              <div className="absolute left-2 bottom-1.5 text-[11px] text-white/80 font-medium">
                {role === 'caller' ? 'You (CEO)' : 'You (Treasury Controller)'}
              </div>
              {!micOn && (
                <div className="absolute right-2 bottom-1.5 p-1 rounded-full bg-black/60">
                  <MicOff className="h-3 w-3 text-white/80" />
                </div>
              )}
            </div>

            {/* Subtitles (Clean floating text overlay at bottom center) */}
            {captions.length > 0 && (
              <div className="absolute bottom-20 left-1/2 -translate-x-1/2 w-[min(720px,85%)] text-center space-y-1 pointer-events-none z-10">
                {captions.map((c) => (
                  <div
                    key={c.id}
                    className="inline-block px-3.5 py-1.5 rounded-lg bg-black/75 backdrop-blur-md text-sm text-white border border-white/10 shadow-lg"
                  >
                    <span className="text-[#8ab4f8] font-semibold mr-1.5">{c.speaker}:</span>
                    <span className={c.interim ? 'text-white/70 italic' : 'text-white font-normal'}>
                      {c.text}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ========================================================================= */}
          {/* 3. SLIDE-OUT SIDE DRAWER (LIVE TRANSCRIPT / PEOPLE / PRESET SCENARIOS)   */}
          {/* ========================================================================= */}
          {sidePanel !== 'none' && (
            <div className="w-84 bg-[#28292c] border-l border-white/10 flex flex-col z-30 transition-all">
              <div className="h-14 px-4 flex items-center justify-between border-b border-white/10 text-sm font-medium">
                <span>
                  {sidePanel === 'chat' && 'Live In-Call Transcript'}
                  {sidePanel === 'people' && `Participants (${peerCount >= 2 ? '2' : '1'})`}
                  {sidePanel === 'scenarios' && 'Preset Scenarios'}
                </span>
                <button
                  onClick={() => setSidePanel('none')}
                  className="p-1.5 rounded-full hover:bg-white/10 text-slate-400 hover:text-white cursor-pointer"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {sidePanel === 'chat' && (
                <div className="flex-1 flex flex-col p-4 overflow-hidden">
                  <div className="text-[11px] uppercase tracking-wider text-slate-400 font-mono mb-2 flex items-center justify-between">
                    <span>Live Conversation Stream</span>
                    <span className="text-emerald-400 font-sans normal-case text-[10px] flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      Active
                    </span>
                  </div>

                  {/* Clean natural conversation stream (NO GAME DIALOGUE CHIPS) */}
                  <div ref={chatScrollRef} className="flex-1 overflow-y-auto space-y-3 text-xs pr-1">
                    {conversationHistory.map((m, idx) => {
                      const isMe = m.speaker.includes('Alex') || m.speaker.includes('You');
                      return (
                        <div
                          key={idx}
                          className={`p-3 rounded-xl border ${
                            isMe
                              ? 'bg-[#1e293b] border-blue-500/20 text-slate-100 ml-4'
                              : 'bg-[#303134] border-white/5 text-slate-200 mr-4'
                          }`}
                        >
                          <div className="flex items-center justify-between mb-1">
                            <span className={`text-[11px] font-semibold ${isMe ? 'text-[#8ab4f8]' : 'text-purple-300'}`}>
                              {m.speaker}
                            </span>
                            <span className="text-[10px] text-slate-500 font-mono">{m.time}</span>
                          </div>
                          <div className="leading-relaxed text-[12px]">{m.text}</div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Direct input fallback if not using microphone */}
                  <div className="mt-3 pt-3 border-t border-white/10 flex items-center gap-2">
                    <input
                      type="text"
                      value={customInput}
                      onChange={(e) => setCustomInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleUserSendMessage(customInput);
                      }}
                      placeholder="Type a message or speak into mic..."
                      className="flex-1 bg-[#303134] text-xs text-white placeholder-slate-400 px-3 py-2 rounded-lg border border-white/10 focus:outline-none focus:border-blue-500"
                    />
                    <button
                      onClick={() => handleUserSendMessage(customInput)}
                      disabled={!customInput.trim()}
                      className="p-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white cursor-pointer transition-colors"
                    >
                      <Send className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              )}

              {sidePanel === 'people' && (
                <div className="p-4 space-y-4">
                  <div className="space-y-2">
                    <div className="flex items-center justify-between p-2.5 rounded-lg bg-[#303134]">
                      <div className="flex items-center gap-2.5">
                        <div className="h-8 w-8 rounded-full bg-[#7b5ea7] flex items-center justify-center text-xs font-bold text-white">
                          {CALLER.initials}
                        </div>
                        <div className="text-xs">
                          <div className="font-medium text-white">{CALLER.name}</div>
                          <div className="text-slate-400 text-[11px]">Caller (External Partner)</div>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center justify-between p-2.5 rounded-lg bg-[#303134]">
                      <div className="flex items-center gap-2.5">
                        <div className="h-8 w-8 rounded-full bg-[#1a73e8] flex items-center justify-center text-xs font-bold text-white">
                          {SELF.initials}
                        </div>
                        <div className="text-xs">
                          <div className="font-medium text-white">{SELF.name} (You)</div>
                          <div className="text-slate-400 text-[11px]">Treasury Controller</div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={copyRoomLink}
                    className="w-full py-2 px-3 rounded-lg bg-[#303134] hover:bg-[#3c4043] text-xs text-slate-200 flex items-center justify-center gap-2 border border-white/10 cursor-pointer transition-colors"
                  >
                    {copiedLink ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                    <span>{copiedLink ? 'Link Copied to Clipboard' : 'Copy Room Invite Link'}</span>
                  </button>
                </div>
              )}

              {sidePanel === 'scenarios' && (
                <div className="p-4 space-y-2">
                  <div className="text-[11px] uppercase tracking-wider text-slate-400 font-mono mb-2">
                    Automated Test Scenarios
                  </div>
                  {SCENARIOS.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => runScenario(s)}
                      className="w-full text-left p-3 rounded-lg bg-[#303134] hover:bg-[#3c4043] text-xs text-slate-200 flex items-center justify-between cursor-pointer border border-white/5 transition-colors"
                    >
                      <span className="font-medium">{s.label}</span>
                      <Play className="h-3.5 w-3.5 text-slate-400" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 4. GOOGLE MEET MINIMALIST BOTTOM BAR                                      */}
      {/* ========================================================================= */}
      <div className="h-20 px-6 grid grid-cols-3 items-center">
        {/* Left: Meeting info & Clock */}
        <div className="text-xs text-slate-300 flex items-center gap-2 select-text">
          <span className="font-medium">{clock}</span>
          <span className="text-white/20">|</span>
          <span className="text-slate-400 font-mono">echo-room-live</span>
        </div>

        {/* Center: Essential Call Controls */}
        <div className="flex justify-center items-center gap-3">
          {/* Microphone */}
          <button
            onClick={toggleMic}
            title={micOn ? 'Mute microphone' : 'Unmute microphone'}
            className={`h-11 w-11 rounded-full flex items-center justify-center transition-all cursor-pointer shadow-md ${
              micOn
                ? 'bg-[#3c4043] hover:bg-[#4a4d51] text-white'
                : 'bg-[#ea4335] hover:bg-[#f05545] text-white'
            }`}
          >
            {micOn ? <Mic className="h-5 w-5" /> : <MicOff className="h-5 w-5" />}
          </button>

          {/* Switch Role (Callee vs Caller) */}
          <button
            onClick={() => {
              setRole(role === 'callee' ? 'caller' : 'callee');
              setConversationHistory([]);
            }}
            title={`Switch Role: Currently ${role === 'callee' ? 'Alex Chen (Treasury)' : 'Robert Higgins (CEO)'}`}
            className="h-11 w-11 rounded-full bg-[#3c4043] hover:bg-[#4a4d51] text-white flex items-center justify-center cursor-pointer transition-colors"
          >
            <Repeat className="h-4 w-4" />
          </button>

          {/* Preset Scenario toggle */}
          <button
            onClick={() => setSidePanel(sidePanel === 'scenarios' ? 'none' : 'scenarios')}
            title="Preset Scenarios"
            className={`h-11 w-11 rounded-full flex items-center justify-center cursor-pointer transition-colors ${
              sidePanel === 'scenarios' ? 'bg-[#8ab4f8] text-[#202124]' : 'bg-[#3c4043] hover:bg-[#4a4d51] text-white'
            }`}
          >
            <Play className="h-4 w-4" />
          </button>

          {/* ===================================================================== */}
          {/* PLUGIN BUTTON: TOGGLE ECHO ZERO-TRUST GUARD ADD-ON                    */}
          {/* ===================================================================== */}
          <div className="relative" ref={pluginMenuRef}>
            <button
              onClick={() => {
                setPluginMenuOpen((v) => !v);
                setSidePanel('none');
              }}
              title="Add-ons: Echo Zero-Trust Guard"
              className={`h-11 w-11 rounded-full flex items-center justify-center cursor-pointer transition-all shadow-md ${
                pluginMenuOpen
                  ? 'bg-[#8ab4f8] text-[#202124]'
                  : isEchoActive
                  ? 'bg-[#1e3a2b] hover:bg-[#274b37] text-emerald-400 border border-emerald-500/40 ring-2 ring-emerald-500/20'
                  : 'bg-[#3c4043] hover:bg-[#4a4d51] text-white'
              }`}
            >
              <Puzzle className="h-5 w-5" />
            </button>

            {/* Plugin Popover with Switch */}
            {pluginMenuOpen && (
              <div className="absolute bottom-16 left-1/2 -translate-x-1/2 w-88 rounded-2xl bg-[#28292c] border border-white/10 shadow-2xl p-4 z-50 animate-in fade-in slide-in-from-bottom-2">
                <div className="flex items-center justify-between pb-3 border-b border-white/10">
                  <div className="flex items-center gap-2">
                    <Puzzle className="h-4 w-4 text-[#8ab4f8]" />
                    <span className="text-xs font-semibold text-white">Call Add-ons</span>
                  </div>
                  <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded-full bg-white/10 text-slate-300">
                    Active Extension
                  </span>
                </div>

                {/* Plugin Card */}
                <div className="mt-3 p-3.5 rounded-xl bg-[#303134] border border-white/5 space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2.5">
                      <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center text-slate-950 shadow-md">
                        <Shield className="h-5 w-5 fill-slate-950" />
                      </div>
                      <div>
                        <div className="text-xs font-bold text-white">Echo Zero-Trust Guard</div>
                        <div className="text-[11px] text-slate-400">Financial fraud interception</div>
                      </div>
                    </div>

                    {/* The requested Toggle Switch */}
                    <button
                      type="button"
                      onClick={toggleEchoActive}
                      title={isEchoActive ? 'Disable Echo Guard' : 'Enable Echo Guard'}
                      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                        isEchoActive ? 'bg-emerald-500' : 'bg-slate-700'
                      }`}
                    >
                      <span
                        className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out ${
                          isEchoActive ? 'translate-x-5' : 'translate-x-0'
                        }`}
                      />
                    </button>
                  </div>

                  {/* Status explanation */}
                  <div className="pt-2 border-t border-white/5 text-[11px] leading-relaxed">
                    {isEchoActive ? (
                      <div className="text-emerald-400 flex items-start gap-1.5 font-medium">
                        <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                        <div>
                          <span>This call is <strong>PROTECTED</strong> by Echo Guard.</span>
                          <p className="text-[10px] text-slate-400 font-normal mt-0.5">
                            Banking portal (Port 3000) will be automatically frozen via CAEP RFC 9493 if coercion is detected.
                          </p>
                        </div>
                      </div>
                    ) : (
                      <div className="text-slate-400 flex items-start gap-1.5 font-medium">
                        <X className="h-3.5 w-3.5 mt-0.5 text-slate-500 shrink-0" />
                        <div>
                          <span>This call is <strong>UNPROTECTED</strong>.</span>
                          <p className="text-[10px] text-slate-500 font-normal mt-0.5">
                            Standard audio mode. Wire transactions on Port 3000 will not be intercepted.
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Footer link to full settings */}
                <button
                  onClick={() => {
                    setPluginMenuOpen(false);
                    setSettingsTab('echo');
                    setSettingsOpen(true);
                  }}
                  className="w-full mt-3 py-2 text-center text-xs text-[#8ab4f8] hover:underline font-medium cursor-pointer"
                >
                  Configure Advanced Settings →
                </button>
              </div>
            )}
          </div>

          {/* ===================================================================== */}
          {/* SETTINGS BUTTON: OPEN COMPREHENSIVE MEETING SETTINGS MODAL           */}
          {/* ===================================================================== */}
          <button
            onClick={() => {
              setSettingsOpen(true);
              setPluginMenuOpen(false);
            }}
            title="Meeting Settings"
            className="h-11 w-11 rounded-full bg-[#3c4043] hover:bg-[#4a4d51] text-white flex items-center justify-center cursor-pointer transition-colors shadow-md"
          >
            <Settings className="h-5 w-5" />
          </button>

          {/* End Call */}
          <button
            onClick={endCall}
            title="Leave Call"
            className="h-11 w-14 rounded-full bg-[#ea4335] hover:bg-[#f05545] text-white flex items-center justify-center cursor-pointer transition-colors shadow-md"
          >
            <PhoneOff className="h-5 w-5" />
          </button>
        </div>

        {/* Right: Drawer Toggles */}
        <div className="flex justify-end items-center gap-2">
          {speaking ? (
            <span className="text-emerald-400 flex items-center gap-1.5 text-xs mr-3 font-medium">
              <Volume2 className="h-4 w-4 animate-bounce" />
            </span>
          ) : null}

          {/* Chat Drawer Toggle */}
          <button
            onClick={() => setSidePanel(sidePanel === 'chat' ? 'none' : 'chat')}
            title="Live Transcript & Chat"
            className={`h-10 w-10 rounded-full flex items-center justify-center cursor-pointer transition-colors ${
              sidePanel === 'chat' ? 'bg-[#8ab4f8] text-[#202124]' : 'hover:bg-white/10 text-slate-300'
            }`}
          >
            <MessageSquare className="h-4 w-4" />
          </button>

          {/* People Drawer Toggle */}
          <button
            onClick={() => setSidePanel(sidePanel === 'people' ? 'none' : 'people')}
            title="Participants"
            className={`h-10 w-10 rounded-full flex items-center justify-center cursor-pointer transition-colors ${
              sidePanel === 'people' ? 'bg-[#8ab4f8] text-[#202124]' : 'hover:bg-white/10 text-slate-300'
            }`}
          >
            <Users className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 5. FULL SETTINGS DIALOG (GOOGLE MEET STYLE MODAL)                         */}
      {/* ========================================================================= */}
      {settingsOpen && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150">
          <div className="w-[740px] max-w-[96vw] h-[550px] rounded-2xl bg-[#28292c] border border-white/10 shadow-2xl flex flex-col overflow-hidden text-white">
            {/* Modal Header */}
            <div className="h-14 px-6 border-b border-white/10 flex items-center justify-between">
              <div className="text-base font-medium">Call Settings</div>
              <button
                onClick={() => setSettingsOpen(false)}
                className="p-1.5 rounded-full hover:bg-white/10 text-slate-400 hover:text-white cursor-pointer"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Modal Content: 2-Column Tabs */}
            <div className="flex-1 flex overflow-hidden">
              {/* Left Tab List */}
              <div className="w-52 border-r border-white/10 p-2 space-y-1 bg-[#232427]">
                <button
                  onClick={() => setSettingsTab('echo')}
                  className={`w-full text-left px-3 py-2.5 rounded-xl text-xs font-medium flex items-center gap-2.5 transition-colors cursor-pointer ${
                    settingsTab === 'echo'
                      ? 'bg-[#3c4043] text-white shadow-sm font-semibold'
                      : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
                  }`}
                >
                  <Shield className="h-4 w-4 text-emerald-400" />
                  <span>Echo AI Defense</span>
                  <span className="ml-auto w-1.5 h-1.5 rounded-full bg-emerald-400" />
                </button>

                <button
                  onClick={() => setSettingsTab('audio')}
                  className={`w-full text-left px-3 py-2.5 rounded-xl text-xs font-medium flex items-center gap-2.5 transition-colors cursor-pointer ${
                    settingsTab === 'audio'
                      ? 'bg-[#3c4043] text-white shadow-sm font-semibold'
                      : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
                  }`}
                >
                  <Mic className="h-4 w-4 text-blue-400" />
                  <span>Audio & Voice</span>
                </button>

                <button
                  onClick={() => setSettingsTab('video')}
                  className={`w-full text-left px-3 py-2.5 rounded-xl text-xs font-medium flex items-center gap-2.5 transition-colors cursor-pointer ${
                    settingsTab === 'video'
                      ? 'bg-[#3c4043] text-white shadow-sm font-semibold'
                      : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
                  }`}
                >
                  <Video className="h-4 w-4 text-purple-400" />
                  <span>Video</span>
                </button>

                <button
                  onClick={() => setSettingsTab('general')}
                  className={`w-full text-left px-3 py-2.5 rounded-xl text-xs font-medium flex items-center gap-2.5 transition-colors cursor-pointer ${
                    settingsTab === 'general'
                      ? 'bg-[#3c4043] text-white shadow-sm font-semibold'
                      : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
                  }`}
                >
                  <SlidersHorizontal className="h-4 w-4 text-slate-300" />
                  <span>General</span>
                </button>
              </div>

              {/* Right Content Panel */}
              <div className="flex-1 p-6 overflow-y-auto space-y-6">
                {/* ============================================================= */}
                {/* TAB 1: ECHO AI DEFENSE CONFIGURATION                          */}
                {/* ============================================================= */}
                {settingsTab === 'echo' && (
                  <div className="space-y-6">
                    <div>
                      <div className="text-sm font-bold text-white flex items-center gap-2">
                        <Shield className="h-4 w-4 text-emerald-400" />
                        Echo Zero-Trust Defense Configuration
                      </div>
                      <div className="text-xs text-slate-400 mt-1">
                        Configure real-time voice fraud detection and cross-session banking lock triggers.
                      </div>
                    </div>

                    {/* Setting 1: Default ON for all calls */}
                    <div className="flex items-center justify-between p-3.5 rounded-xl bg-[#303134] border border-white/5">
                      <div>
                        <div className="text-xs font-semibold text-white">Default enabled for all calls</div>
                        <div className="text-[11px] text-slate-400 mt-0.5 leading-relaxed">
                          Automatically arm Echo Guard protection whenever you join an executive conference call.
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleToggleDefaultEcho(!defaultEchoActive)}
                        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                          defaultEchoActive ? 'bg-emerald-500' : 'bg-slate-700'
                        }`}
                      >
                        <span
                          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                            defaultEchoActive ? 'translate-x-5' : 'translate-x-0'
                          }`}
                        />
                      </button>
                    </div>

                    {/* Setting 2: Auto-lock banking portal on fraud */}
                    <div className="flex items-center justify-between p-3.5 rounded-xl bg-[#303134] border border-white/5">
                      <div>
                        <div className="text-xs font-semibold text-white">Auto-lock Corporate Banking Portal (Port 3000)</div>
                        <div className="text-[11px] text-slate-400 mt-0.5 leading-relaxed">
                          Emit CAEP (RFC 9493) lock signals in &lt;50ms when coercion or executive impersonation is detected.
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleToggleAutoLock(!autoLockBanking)}
                        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                          autoLockBanking ? 'bg-emerald-500' : 'bg-slate-700'
                        }`}
                      >
                        <span
                          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                            autoLockBanking ? 'translate-x-5' : 'translate-x-0'
                          }`}
                        />
                      </button>
                    </div>

                    {/* Setting 3: Voice Barge-In */}
                    <div className="flex items-center justify-between p-3.5 rounded-xl bg-[#303134] border border-white/5">
                      <div>
                        <div className="text-xs font-semibold text-white">Voice Barge-In Audio Warning</div>
                        <div className="text-[11px] text-slate-400 mt-0.5 leading-relaxed">
                          Interrupt call audio and inject an emergency spoken warning directly into the user headset.
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleToggleVoiceBargeIn(!voiceBargeInAlert)}
                        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                          voiceBargeInAlert ? 'bg-emerald-500' : 'bg-slate-700'
                        }`}
                      >
                        <span
                          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                            voiceBargeInAlert ? 'translate-x-5' : 'translate-x-0'
                          }`}
                        />
                      </button>
                    </div>

                    {/* Setting 4: Sensitivity Selection */}
                    <div className="space-y-2 p-3.5 rounded-xl bg-[#303134] border border-white/5">
                      <div className="text-xs font-semibold text-white">Risk Analysis Sensitivity</div>
                      <div className="grid grid-cols-3 gap-2 pt-1">
                        {[
                          { id: 'standard', label: 'Standard', desc: '85% threshold (Recommended)' },
                          { id: 'strict', label: 'Strict', desc: '70% threshold (High Security)' },
                          { id: 'relaxed', label: 'Relaxed', desc: '95% threshold (Blatant only)' }
                        ].map((item) => (
                          <button
                            key={item.id}
                            type="button"
                            onClick={() => handleChangeSensitivity(item.id as RiskSensitivity)}
                            className={`p-2.5 rounded-lg text-left border transition-all cursor-pointer ${
                              riskSensitivity === item.id
                                ? 'bg-emerald-950/60 border-emerald-500/60 text-emerald-300 ring-1 ring-emerald-500/40'
                                : 'bg-[#232427] border-white/5 text-slate-400 hover:text-slate-200'
                            }`}
                          >
                            <div className="text-xs font-medium">{item.label}</div>
                            <div className="text-[10px] opacity-75 mt-0.5">{item.desc}</div>
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Connected Infrastructure info */}
                    <div className="p-3 rounded-xl bg-[#232427] border border-white/5 space-y-2 text-xs">
                      <div className="flex items-center justify-between text-slate-400">
                        <span className="flex items-center gap-1.5"><Cpu className="h-3.5 w-3.5 text-blue-400" /> AI Detection Engine:</span>
                        <span className="font-mono text-emerald-400">Gemini 3.5 Flash Lite (Multi-tier)</span>
                      </div>
                      <div className="flex items-center justify-between text-slate-400">
                        <span className="flex items-center gap-1.5"><Lock className="h-3.5 w-3.5 text-purple-400" /> Intercepted Banking Portal:</span>
                        <span className="font-mono text-slate-200">http://localhost:3000 (Port 3000)</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* ============================================================= */}
                {/* TAB 2: AUDIO & ULTRA-REALISTIC VOICE SYNTHESIS                */}
                {/* ============================================================= */}
                {settingsTab === 'audio' && (
                  <div className="space-y-5">
                    <div>
                      <div className="text-sm font-bold text-white">Audio & Voice Synthesis</div>
                      <div className="text-xs text-slate-400 mt-1">Configure your microphone and AI voice realism settings.</div>
                    </div>

                    <div className="space-y-3">
                      <div>
                        <label className="text-xs font-medium text-slate-300 block mb-1">Microphone Input</label>
                        <select className="w-full bg-[#303134] text-xs text-white p-2.5 rounded-lg border border-white/10 focus:outline-none">
                          <option>Default Microphone (System Array / Realtek Audio)</option>
                          <option>Communications Headset Microphone</option>
                        </select>
                      </div>

                      {/* Microphone VU Meter */}
                      <div className="flex items-center gap-2 text-xs text-slate-400">
                        <span>Input Level:</span>
                        <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden flex gap-0.5 p-0.5">
                          {[...Array(16)].map((_, i) => (
                            <div
                              key={i}
                              className={`flex-1 rounded-sm ${
                                micOn && i < 10 ? 'bg-emerald-400' : 'bg-slate-700'
                              }`}
                            />
                          ))}
                        </div>
                      </div>
                    </div>

                    <div className="space-y-3 pt-2 border-t border-white/5">
                      <div>
                        <label className="text-xs font-medium text-slate-300 block mb-1">Speaker Output</label>
                        <select className="w-full bg-[#303134] text-xs text-white p-2.5 rounded-lg border border-white/10 focus:outline-none">
                          <option>Default Speakers (System Output / Realtek Audio)</option>
                          <option>Stereo Headphones</option>
                        </select>
                      </div>

                      <button
                        type="button"
                        onClick={playTestChime}
                        className="px-3.5 py-1.5 rounded-lg bg-[#303134] hover:bg-[#3c4043] text-xs text-slate-200 border border-white/10 flex items-center gap-2 cursor-pointer transition-colors"
                      >
                        <Volume2 className="h-3.5 w-3.5 text-blue-400" />
                        <span>Test Speaker Audio</span>
                      </button>
                    </div>

                    {/* ElevenLabs High-Fidelity Voice Integration */}
                    <div className="p-4 rounded-xl bg-gradient-to-br from-[#202534] to-[#1c1d22] border border-blue-500/20 space-y-3">
                      <div className="flex items-center gap-2 text-xs font-bold text-blue-400">
                        <Key className="h-4 w-4" />
                        <span>Ultra-Realistic Voice Synthesis (3-Tier Engine)</span>
                      </div>
                      <p className="text-[11px] text-slate-300 leading-relaxed">
                        <strong className="text-emerald-400">Tier 1:</strong> ElevenLabs AI Voice (Ultra-realistic) &rarr;{' '}
                        <strong className="text-blue-400">Tier 2:</strong> Google Natural Voice &rarr;{' '}
                        <strong className="text-amber-400">Tier 3:</strong> Classic Robot Synth (Offline). If ElevenLabs runs out of credits or errors, Echo automatically falls back down the chain with zero interruption.
                      </p>

                      <div className="space-y-2">
                        <div>
                          <label className="text-[11px] text-slate-400 block mb-1">ElevenLabs API Key (xi-api-key)</label>
                          <input
                            type="password"
                            value={elevenLabsApiKey}
                            onChange={(e) => handleSaveElevenLabsKey(e.target.value)}
                            placeholder="sk_..."
                            className="w-full bg-[#303134] text-xs text-white p-2 rounded-lg border border-white/10 focus:outline-none font-mono"
                          />
                        </div>

                        <div>
                          <label className="text-[11px] text-slate-400 block mb-1">Voice Profile</label>
                          <select
                            value={elevenLabsVoiceId}
                            onChange={(e) => handleSaveElevenLabsVoice(e.target.value)}
                            className="w-full bg-[#303134] text-xs text-white p-2 rounded-lg border border-white/10 focus:outline-none"
                          >
                            <option value="pNInz6obpgDQGcFmaJgB">Adam (Deep, Authoritative American Executive)</option>
                            <option value="ErXwobaYiN019PkySvjV">Antoni (Urgent & Energetic Corporate Partner)</option>
                            <option value="21m00Tcm4TlvDq8ikWAM">Rachel (Calm & Professional Auditor)</option>
                          </select>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center justify-between p-3 rounded-xl bg-[#303134] border border-white/5">
                      <div>
                        <div className="text-xs font-medium text-white">Environmental Noise Suppression</div>
                        <div className="text-[11px] text-slate-400">Filters background noise for higher speech recognition accuracy.</div>
                      </div>
                      <button
                        type="button"
                        onClick={() => setNoiseCancellation(!noiseCancellation)}
                        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                          noiseCancellation ? 'bg-blue-600' : 'bg-slate-700'
                        }`}
                      >
                        <span
                          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                            noiseCancellation ? 'translate-x-5' : 'translate-x-0'
                          }`}
                        />
                      </button>
                    </div>
                  </div>
                )}

                {/* ============================================================= */}
                {/* TAB 3: VIDEO                                                  */}
                {/* ============================================================= */}
                {settingsTab === 'video' && (
                  <div className="space-y-5">
                    <div>
                      <div className="text-sm font-bold text-white">Video Devices</div>
                      <div className="text-xs text-slate-400 mt-1">Configure camera source and video streaming resolution.</div>
                    </div>

                    <div className="space-y-3">
                      <div>
                        <label className="text-xs font-medium text-slate-300 block mb-1">Camera</label>
                        <select className="w-full bg-[#303134] text-xs text-white p-2.5 rounded-lg border border-white/10 focus:outline-none">
                          <option>Integrated HD Webcam (04f2:b6d9)</option>
                          <option>Virtual Camera (OBS)</option>
                        </select>
                      </div>

                      <div>
                        <label className="text-xs font-medium text-slate-300 block mb-1">Send Resolution</label>
                        <select className="w-full bg-[#303134] text-xs text-white p-2.5 rounded-lg border border-white/10 focus:outline-none">
                          <option>High Definition (720p - Recommended)</option>
                          <option>Standard Definition (360p)</option>
                        </select>
                      </div>
                    </div>
                  </div>
                )}

                {/* ============================================================= */}
                {/* TAB 4: GENERAL                                                */}
                {/* ============================================================= */}
                {settingsTab === 'general' && (
                  <div className="space-y-5">
                    <div>
                      <div className="text-sm font-bold text-white">General Information</div>
                      <div className="text-xs text-slate-400 mt-1">System specifications and connected services</div>
                    </div>

                    <div className="space-y-2.5 text-xs">
                      <div className="flex items-center justify-between p-3 rounded-xl bg-[#303134]">
                        <span className="text-slate-300">Interface & Voice Language</span>
                        <span className="font-semibold text-emerald-400">English (United States - en-US)</span>
                      </div>
                      <div className="flex items-center justify-between p-3 rounded-xl bg-[#303134]">
                        <span className="text-slate-300">Zero-Trust Protocol</span>
                        <span className="font-mono text-emerald-400">CAEP RFC 9493 Active</span>
                      </div>
                      <div className="flex items-center justify-between p-3 rounded-xl bg-[#303134]">
                        <span className="text-slate-300">Hackathon Project</span>
                        <span className="font-semibold text-white">Google AI Builder Cup 2026 - Echo</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Modal Footer */}
            <div className="h-14 px-6 border-t border-white/10 flex items-center justify-end bg-[#202124]">
              <button
                onClick={() => setSettingsOpen(false)}
                className="px-6 py-2 rounded-full bg-[#8ab4f8] text-[#202124] text-xs font-semibold hover:bg-[#aecbfa] cursor-pointer transition-colors shadow"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
