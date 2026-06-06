// Browser Web Speech API helpers for the NemoClaw voice console.
// Speech recognition (mic → text) + speech synthesis (text → spoken reply).
// Both degrade to no-ops where the browser lacks support, so the overlay never breaks.

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
  stop: () => void;
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
    return { stop: () => {} };
  }
  const rec = new SR();
  rec.lang = "en-GB";
  rec.interimResults = true;
  rec.continuous = false;
  rec.maxAlternatives = 1;

  let finalText = "";
  rec.onresult = (e: any) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      if (res.isFinal) finalText += res[0].transcript;
      else interim += res[0].transcript;
    }
    opts.onPartial?.((finalText + interim).trim());
  };
  rec.onerror = (e: any) => opts.onError?.(String(e?.error ?? "error"));
  rec.onend = () => {
    opts.onEnd?.();
    if (finalText.trim()) opts.onFinal(finalText.trim());
  };
  try {
    rec.start();
  } catch {
    /* already started / not allowed */
  }
  return {
    stop: () => {
      try {
        rec.stop();
      } catch {
        /* no-op */
      }
    },
  };
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
