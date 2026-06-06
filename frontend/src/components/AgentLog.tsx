// NEMOCLAW local-agent feed — the live narration from the orchestrator's NemoClaw
// agent (real TfL disruptions + live re-plans), arriving as agent_log / notification
// WS events. Shows the last ~5 lines, newest first, with mono timestamps; severe
// lines are tinted. Glass card, bottom-left of the command center.
//
// You can also ASK NemoClaw a question: a free-text box + two preset prompts POST
// to /agent/ask; the answer streams back into this feed as an agent_log line tagged
// "nemotron" (plus a WS "agent_answer" event the store also surfaces here).

import { useMemo, useState } from "react";
import { askAgent } from "../api";
import { useStore } from "../store";

const MAX_LINES = 5;

const PRESET_MONITOR = "Monitor live conditions and flag any couriers at risk.";
const PRESET_ASSESS = "Assess all active drivers and recommend reroutes where needed.";

export default function AgentLog() {
  const logs = useStore((s) => s.logs);
  const pushLog = useStore((s) => s.pushLog);

  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);

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
        <span className="nemo-title">
          <span className="nemo-bars">❘❙</span> NEMOCLAW · LOCAL AGENT
        </span>
        <span className="nemo-voice">
          <span className="nemo-voice-dot" />VOICE LIVE
        </span>
      </header>
      <div className="nemo-sources">sources: TfL · London datastore · live ops</div>
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
      <div className="nemo-presets">
        <button
          type="button"
          className="nemo-preset"
          data-testid="ask-preset-monitor"
          disabled={sending}
          onClick={() => void send(PRESET_MONITOR)}
        >
          Monitor &amp; flag
        </button>
        <button
          type="button"
          className="nemo-preset"
          data-testid="ask-preset-assess"
          disabled={sending}
          onClick={() => void send(PRESET_ASSESS)}
        >
          Assess drivers
        </button>
      </div>
    </section>
  );
}
