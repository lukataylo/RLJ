// Full-screen voice assistant overlay — a faint dot-field with two amber
// dot-matrix eyes that blink, a phase line and an End control. Mirrors the
// PulseGo operator dashboard's back-and-forth voice loop:
//   open → listen (Web Speech API) → POST /driver/ask → speak the answer via
//   ElevenLabs (/tts) → automatically listen again, until the driver taps End.
// Answers are route-grounded: the active courier + last GPS fix go with each
// question. If speech recognition is unsupported, a text input fallback still
// calls /driver/ask and speaks the reply.

import { useEffect, useRef, useState } from "react";
import { askDriver } from "../api";
import { selectActiveRoute, useStore } from "../store";
import {
  prepareSpeech,
  speakElevenLabs,
  speechSupported,
  startListening,
  stopSpeaking,
  type Listener,
} from "../lib/voice";

const LISTEN_SECONDS = 15;

// One eye = a rounded 4×4 block; the centre 2×2 is the brighter "pupil".
const EYE = [
  [0, 1, 1, 0],
  [1, 1, 1, 1],
  [1, 1, 1, 1],
  [0, 1, 1, 0],
];
const PUPIL = new Set(["1,1", "1,2", "2,1", "2,2"]);
const COLS = 23;
const ROWS = 11;

function Eyes() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [blink, setBlink] = useState(false);

  useEffect(() => {
    let t: number;
    const schedule = () => {
      t = window.setTimeout(() => {
        setBlink(true);
        window.setTimeout(() => setBlink(false), 130);
        schedule();
      }, 2400 + Math.round(Math.abs(Math.sin(ROWS * 37)) * 1400));
    };
    schedule();
    return () => window.clearTimeout(t);
  }, []);

  // Centre two eyes (each 4 wide, 5 cols apart) in the grid.
  const gap = 5;
  const totalW = 4 + gap + 4;
  const startC = Math.round((COLS - totalW) / 2);
  const startR = Math.round((ROWS - 4) / 2);
  const origins = [
    { r: startR, c: startC },
    { r: startR, c: startC + 4 + gap },
  ];

  const on = new Set<string>();
  const pupil = new Set<string>();
  for (const o of origins) {
    for (let i = 0; i < EYE.length; i++) {
      for (let j = 0; j < EYE[i].length; j++) {
        if (!EYE[i][j]) continue;
        if (blink && i !== 1 && i !== 2) continue;
        const r = o.r + i;
        const c = o.c + j;
        on.add(`${r},${c}`);
        if (!blink && PUPIL.has(`${i},${j}`)) pupil.add(`${r},${c}`);
      }
    }
  }

  return (
    <div className="vo-eyes" ref={ref} aria-hidden>
      {Array.from({ length: ROWS }).flatMap((_, r) =>
        Array.from({ length: COLS }).map((__, c) => {
          const k = `${r},${c}`;
          const cls = pupil.has(k) ? "pupil" : on.has(k) ? "on" : "";
          return <span key={k} className={`vo-dot ${cls}`} />;
        }),
      )}
    </div>
  );
}

type Phase = "listening" | "thinking" | "speaking" | "unsupported";

export default function VoiceOverlay({
  name,
  onClose,
}: {
  name?: string;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("listening");
  const [secs, setSecs] = useState(LISTEN_SECONDS);
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState("");
  const [draft, setDraft] = useState("");

  const timerRef = useRef<number | null>(null);
  const recRef = useRef<Listener | null>(null);
  // True while the conversation is live; gates the auto-listen loop so a
  // closed/cancelled session never re-opens the mic after a reply finishes.
  const convActiveRef = useRef(false);
  // Stable handle to "start the next listen turn", called from speech-end callbacks.
  const listenTurnRef = useRef<() => void>(() => {});

  const clearTimer = () => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  // Build route-grounded context from the live store: the active courier, the
  // local driver id and the last GPS fix (lat/lng/heading).
  const askContext = () => {
    const s = useStore.getState();
    const courier = selectActiveRoute(s)?.courier_id ?? null;
    const fix = s.lastFix;
    return {
      courier_id: courier,
      driver_id: s.driver?.id ?? null,
      lat: fix?.lat,
      lng: fix?.lng,
      heading: fix?.heading_deg,
    };
  };

  // Ask the orchestrator, then speak the reply. When the conversation is live we
  // resume listening once the answer finishes; in the text fallback we just idle.
  const ask = async (text: string) => {
    const q = text.trim();
    if (!q) {
      if (convActiveRef.current) listenTurnRef.current();
      return;
    }
    setPhase("thinking");
    setReply("");
    let answer = "";
    try {
      const res = await askDriver(q, askContext());
      answer = res.data?.answer?.trim() ?? "";
    } catch {
      answer = "";
    }
    if (!answer) answer = "Sorry, I couldn't reach the dispatcher. Please try again.";
    setReply(answer);
    setPhase("speaking");
    void speakElevenLabs(answer, () => {
      if (convActiveRef.current) listenTurnRef.current();
      else setPhase("unsupported");
    });
  };

  // Start one listen turn. onFinal hands the transcript to ask(), which (after
  // the reply is spoken) loops back here for the next turn.
  const beginListenTurn = () => {
    if (!convActiveRef.current) return;
    setHeard("");
    setReply("");
    setSecs(LISTEN_SECONDS);
    setPhase("listening");
    recRef.current = startListening({
      onPartial: (t) => setHeard(t),
      onFinal: (t) => {
        setHeard(t);
        void ask(t);
      },
      onError: (e) => {
        if (e === "unsupported") {
          convActiveRef.current = false;
          setPhase("unsupported");
        }
      },
    });
  };
  listenTurnRef.current = beginListenTurn;

  const close = () => {
    convActiveRef.current = false;
    recRef.current?.cancel();
    recRef.current = null;
    clearTimer();
    stopSpeaking();
    onClose();
  };

  // Open the conversation once on mount.
  useEffect(() => {
    prepareSpeech();
    if (!speechSupported()) {
      setPhase("unsupported");
      return;
    }
    convActiveRef.current = true;
    beginListenTurn();
    return () => {
      convActiveRef.current = false;
      recRef.current?.cancel();
      clearTimer();
      stopSpeaking();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Listening countdown (visual + safety stop if the speaker goes quiet too
  // long). Only runs during a listen turn; thinking/speaking pause it. Silence
  // to zero ends the whole conversation.
  useEffect(() => {
    if (phase !== "listening") return;
    setSecs(LISTEN_SECONDS);
    timerRef.current = window.setInterval(() => {
      setSecs((s) => {
        if (s <= 1) {
          close();
          return LISTEN_SECONDS;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearTimer();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const submitText = (e: React.FormEvent) => {
    e.preventDefault();
    const q = draft.trim();
    if (!q) return;
    setHeard(q);
    setDraft("");
    void ask(q);
  };

  const status =
    phase === "thinking"
      ? "THINKING…"
      : phase === "speaking"
        ? "SPEAKING…"
        : phase === "unsupported"
          ? "VOICE UNAVAILABLE"
          : `LISTENING · ${secs}s`;

  const prompt =
    phase === "unsupported"
      ? "Voice isn't supported here — type your question below."
      : phase === "speaking" && reply
        ? reply
        : heard
          ? `“${heard}”`
          : name
            ? `${name} — how can I help on the road?`
            : "How can I help on the road?";

  const hint =
    phase === "thinking"
      ? "asking the dispatcher…"
      : phase === "speaking"
        ? "replying…"
        : phase === "unsupported"
          ? "type to ask"
          : "speak naturally — I'll keep listening";

  return (
    <div
      className="voice-overlay"
      data-testid="voice-overlay"
      role="dialog"
      aria-label="Voice assistant"
    >
      <button type="button" className="vo-close" aria-label="Close" onClick={close}>
        ✕
      </button>

      <div className="vo-top">
        <div className="vo-status">
          <span className="vo-rec" /> {status}
        </div>
        <h2 className="vo-prompt" data-testid="voice-transcript">
          {prompt}
        </h2>
      </div>

      <div className="vo-stage">
        <Eyes />
      </div>

      <div className="vo-bottom">
        {phase === "unsupported" ? (
          <form className="vo-textform" onSubmit={submitText}>
            <input
              className="vo-textinput"
              data-testid="voice-text-input"
              type="text"
              placeholder="Ask about your route…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              autoFocus
            />
            <button
              type="submit"
              className="vo-textsend"
              data-testid="voice-text-send"
              disabled={draft.trim().length === 0}
            >
              Ask
            </button>
          </form>
        ) : (
          <span className="vo-hint">{hint}</span>
        )}
        <button
          type="button"
          className="vo-cancel"
          data-testid="voice-cancel"
          onClick={close}
        >
          End
        </button>
      </div>
    </div>
  );
}
