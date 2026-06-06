// NEMOCLAW local-agent feed — the live narration from the orchestrator's NemoClaw
// agent (real TfL disruptions + live re-plans), arriving as agent_log / notification
// WS events. Shows the last ~5 lines, newest first, with mono timestamps; severe
// lines are tinted. Glass card, bottom-left of the command center.
//
// You can also ASK NemoClaw a question: a free-text box + two preset prompts POST
// to /agent/ask; the answer streams back into this feed as an agent_log line tagged
// "nemotron" (plus a WS "agent_answer" event the store also surfaces here).

import { useEffect, useMemo, useRef, useState } from "react";
import { askAgent } from "../api";
import { useStore } from "../store";
import NemoFace from "./NemoFace";
import { speechSupported, startListening, speak, type Listener } from "../lib/voice";

const MAX_LINES = 6;
const LISTEN_SECONDS = 15;

export default function AgentLog() {
  const logs = useStore((s) => s.logs);
  const pushLog = useStore((s) => s.pushLog);

  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);

  // Voice console: real browser speech recognition → /agent/ask → spoken reply.
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [secs, setSecs] = useState(LISTEN_SECONDS);
  const [heard, setHeard] = useState("");
  const [voicePhase, setVoicePhase] = useState<"listening" | "thinking" | "unsupported">("listening");
  const timerRef = useRef<number | null>(null);
  const recRef = useRef<Listener | null>(null);
  const voiceAskAtRef = useRef<number>(0); // ts of last voice ask → speak the reply
  const spokenRef = useRef<Set<string>>(new Set());

  const stopRecognition = () => {
    recRef.current?.stop();
    recRef.current = null;
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const closeVoice = () => {
    stopRecognition();
    setVoiceOpen(false);
  };

  const openVoice = () => {
    setSecs(LISTEN_SECONDS);
    setHeard("");
    setVoiceOpen(true);
    if (!speechSupported()) {
      setVoicePhase("unsupported");
      return;
    }
    setVoicePhase("listening");
    recRef.current = startListening({
      onPartial: (t) => setHeard(t),
      onFinal: (t) => {
        setHeard(t);
        setVoicePhase("thinking");
        voiceAskAtRef.current = Date.now();
        void send(t);
        // brief "thinking" beat, then close — the reply lands in the feed + is spoken
        window.setTimeout(() => setVoiceOpen(false), 1400);
      },
      onError: (e) => {
        if (e === "unsupported") setVoicePhase("unsupported");
      },
    });
  };

  // Listening countdown (visual + safety stop if the speaker goes quiet too long).
  useEffect(() => {
    if (!voiceOpen || voicePhase !== "listening") return;
    setSecs(LISTEN_SECONDS);
    timerRef.current = window.setInterval(() => {
      setSecs((s) => {
        if (s <= 1) {
          stopRecognition();
          setVoiceOpen(false);
          return LISTEN_SECONDS;
        }
        return s - 1;
      });
    }, 1000);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [voiceOpen, voicePhase]);

  // Speak NemoClaw's reply aloud after a VOICE question (first agent line that lands).
  useEffect(() => {
    if (!voiceAskAtRef.current) return;
    for (const l of logs) {
      const t = new Date(l.ts).getTime();
      const key = `${l.ts}|${l.message}`;
      const isAnswer =
        (l.source === "agent_log" || l.source === "notification") &&
        !l.message.startsWith("You →");
      if (t >= voiceAskAtRef.current && isAnswer && !spokenRef.current.has(key)) {
        spokenRef.current.add(key);
        speak(l.message);
        voiceAskAtRef.current = 0; // speak only the first reply
        break;
      }
    }
  }, [logs]);

  // Prefer the real agent narration (agent_log + notifications); fall back to all
  // lines so the feed is never empty before the first agent event arrives.
  const feed = useMemo(() => {
    const agentish = logs.filter(
      (l) => l.source === "agent_log" || l.source === "notification",
    );
    const base = agentish.length ? agentish : logs;
    return [...base].slice(-MAX_LINES).reverse(); // newest first
  }, [logs]);

  const send = async (q: string) => {
    const text = q.trim();
    if (!text || sending) return;
    setSending(true);
    pushLog({
      level: "info",
      message: `You → NemoClaw: ${text}`,
      source: "agent_log",
    });
    try {
      await askAgent(text);
      setQuestion("");
    } catch {
      pushLog({
        level: "warn",
        message: "Could not reach NemoClaw — question not queued.",
        source: "system",
      });
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="nemoclaw glass" data-testid="agent-log">
      <header className="nemo-head">
        <span className="nemo-title">NemoClaw</span>
        <button
          type="button"
          className="nemo-agent-btn"
          data-testid="nemo-voice-open"
          aria-label="Talk to NemoClaw"
          title="Talk to NemoClaw"
          onClick={openVoice}
        >
          <NemoFace variant="button" />
        </button>
      </header>

      {voiceOpen && (
        <div className="nemo-voice-ov" data-testid="nemo-voice">
          {/* eyes are part of a full-bleed background dot field (no frame) */}
          <NemoFace variant="field" listening />
          <button
            type="button"
            className="nvo-close"
            data-testid="nemo-voice-close"
            aria-label="Close voice"
            onClick={closeVoice}
          >
            ✕
          </button>
          <div className="nvo-content">
            <div className="nvo-top">
              <div className="nvo-status">
                <span className="nvo-rec" />{" "}
                {voicePhase === "thinking"
                  ? "THINKING…"
                  : voicePhase === "unsupported"
                    ? "VOICE UNAVAILABLE"
                    : `LISTENING · ${secs}s`}
              </div>
              <div className="nvo-prompt" data-testid="nemo-voice-transcript">
                {voicePhase === "unsupported"
                  ? "Voice isn't supported here — type your question below."
                  : heard
                    ? `“${heard}”`
                    : "How can I help with the fleet?"}
              </div>
            </div>
            <div className="nvo-bottom">
              <div className="nvo-hint">
                {voicePhase === "thinking" ? "asking NemoClaw…" : "speak naturally"}
              </div>
              <button
                type="button"
                className="nvo-cancel"
                data-testid="nemo-voice-cancel"
                onClick={closeVoice}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="nemo-sources">Local agent · TfL · live ops</div>
      <div className="nemo-body" data-testid="nemoclaw-feed">
        {feed.length === 0 && <div className="nemo-empty">Awaiting agent activity…</div>}
        {feed.map((l, i) => {
          // Tint lines narrated by the GB10 Nemotron agent (signal recs / answers).
          const nemotron =
            l.nemotron === true || /nemotron|gb10|green wave|re-?time/i.test(l.message);
          return (
            <div
              key={`${l.ts}-${i}`}
              className={`nemo-line lvl-${l.level}${nemotron ? " src-nemotron" : ""}`}
            >
              <span className="nemo-ts">
                {new Date(l.ts).toLocaleTimeString("en-GB", { hour12: false }).slice(0, 5)}
              </span>
              <span className="nemo-msg">{l.message}</span>
            </div>
          );
        })}
      </div>

      <form
        className="nemo-ask"
        onSubmit={(e) => {
          e.preventDefault();
          void send(question);
        }}
      >
        <input
          className="nemo-ask-input"
          data-testid="ask-input"
          type="text"
          placeholder="Ask NemoClaw…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={sending}
        />
        <button
          type="submit"
          className="nemo-ask-send"
          data-testid="ask-send"
          disabled={sending || question.trim().length === 0}
        >
          {sending ? "…" : "Send"}
        </button>
      </form>
    </section>
  );
}
