// Browser Web Speech API helpers + ElevenLabs TTS proxy for the NemoClaw voice console.
// Speech recognition (mic → text): browser Web Speech API.
// Speech synthesis (text → spoken reply): ElevenLabs via the orchestrator /tts proxy,
// falling back to the browser's built-in synthesis if the proxy is unavailable.

import { getToken } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type SRCtor = new () => any;

function getSR(): SRCtor | null {
  const w = window as any;
  return (w.SpeechRecognition || w.webkitSpeechRecognition || null) as SRCtor | null;
}

export function speechSupported(): boolean {
  return getSR() !== null;
}

export interface Listener {
  /** Finish recognition and submit any final transcript emitted by the browser. */
  stop: () => void;
  /** Abort recognition without calling onFinal. */
  cancel: () => void;
}

/** Start listening; streams partial text and fires onFinal with the final transcript. */
export function startListening(opts: {
  onPartial?: (text: string) => void;
  onFinal: (text: string) => void;
  onError?: (err: string) => void;
  onEnd?: () => void;
}): Listener {
  const SR = getSR();
  if (!SR) {
    opts.onError?.("unsupported");
    return { stop: () => {}, cancel: () => {} };
  }
  const rec = new SR();
  rec.lang = "en-GB";
  rec.interimResults = true;
  rec.continuous = false;
  rec.maxAlternatives = 1;

  let finalText = "";
  let cancelled = false;
  let failed = false;
  rec.onresult = (e: any) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      if (res.isFinal) finalText += res[0].transcript;
      else interim += res[0].transcript;
    }
    opts.onPartial?.((finalText + interim).trim());
  };
  rec.onerror = (e: any) => {
    failed = true;
    opts.onError?.(String(e?.error ?? "error"));
  };
  rec.onend = () => {
    opts.onEnd?.();
    if (!cancelled && !failed && finalText.trim()) opts.onFinal(finalText.trim());
  };
  try {
    rec.start();
  } catch (err) {
    failed = true;
    opts.onError?.(err instanceof Error ? err.message : "start-failed");
    opts.onEnd?.();
  }
  return {
    stop: () => {
      try {
        rec.stop();
      } catch {
        /* no-op */
      }
    },
    cancel: () => {
      cancelled = true;
      try {
        rec.abort();
      } catch {
        /* no-op */
      }
    },
  };
}

const _BASE = (import.meta.env.VITE_ORCHESTRATOR_URL || "http://localhost:8000").replace(/\/$/, "");
let activeAudio: HTMLAudioElement | null = null;
let activeUrl: string | null = null;
let activeRequest: AbortController | null = null;
let audioContext: AudioContext | null = null;
let activeSource: AudioBufferSourceNode | null = null;
let speechSequence = 0;

function cleanupAudio(): void {
  if (activeSource) {
    activeSource.onended = null;
    try {
      activeSource.stop();
    } catch {
      /* already stopped */
    }
    activeSource.disconnect();
    activeSource = null;
  }
  if (activeAudio) {
    activeAudio.pause();
    activeAudio.src = "";
    activeAudio = null;
  }
  if (activeUrl) {
    URL.revokeObjectURL(activeUrl);
    activeUrl = null;
  }
}

/** Prime browser audio during a user gesture so a later WebSocket answer may play. */
export function prepareSpeech(): void {
  try {
    const AudioContextCtor =
      window.AudioContext ||
      (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) return;
    audioContext ??= new AudioContextCtor();
    if (audioContext.state === "suspended") void audioContext.resume().catch(() => {});
  } catch {
    /* Web Audio unavailable; HTMLAudio and speech synthesis remain as fallbacks. */
  }
}

/** Stop any in-flight ElevenLabs request and currently playing response. */
export function stopSpeaking(): void {
  speechSequence += 1;
  activeRequest?.abort();
  activeRequest = null;
  cleanupAudio();
  try {
    window.speechSynthesis?.cancel();
  } catch {
    /* synthesis unavailable */
  }
}

/** Speak `text` aloud via the browser's speech synthesiser (best-effort). */
export function speak(text: string): void {
  try {
    const synth = window.speechSynthesis;
    if (!synth || !text) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "en-GB";
    u.rate = 1.05;
    u.pitch = 1.0;
    synth.speak(u);
  } catch {
    /* synthesis unavailable */
  }
}

/** Speak `text` via ElevenLabs TTS (proxied through the orchestrator /tts endpoint).
 *  Falls back to browser synthesis if the proxy is unavailable or not configured. */
export async function speakElevenLabs(text: string): Promise<void> {
  if (!text) return;
  stopSpeaking();
  const sequence = speechSequence;
  const controller = new AbortController();
  activeRequest = controller;
  try {
    const token = getToken();
    const res = await fetch(`${_BASE}/tts`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(token ? { authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`${res.status}`);
    if (audioContext) {
      const encoded = await res.arrayBuffer();
      const decoded = await audioContext.decodeAudioData(encoded);
      if (sequence !== speechSequence) return;
      if (audioContext.state === "suspended") await audioContext.resume();
      const source = audioContext.createBufferSource();
      source.buffer = decoded;
      source.connect(audioContext.destination);
      activeSource = source;
      source.onended = () => {
        if (activeSource === source) {
          source.disconnect();
          activeSource = null;
        }
      };
      source.start();
      return;
    }
    const blob = await res.blob();
    if (sequence !== speechSequence) return;
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    activeUrl = url;
    activeAudio = audio;
    const cleanup = () => {
      if (activeAudio === audio) cleanupAudio();
    };
    audio.onended = cleanup;
    audio.onerror = cleanup;
    await audio.play();
  } catch (err) {
    if (sequence === speechSequence && !(err instanceof DOMException && err.name === "AbortError")) {
      cleanupAudio();
      speak(text); // fallback: browser synthesis
    }
  } finally {
    if (activeRequest === controller) activeRequest = null;
  }
}
