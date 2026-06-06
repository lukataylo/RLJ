// NEMOCLAW local-agent feed — the live narration from the orchestrator's NemoClaw
// agent (real TfL disruptions + live re-plans), arriving as agent_log / notification
// WS events. Shows the last ~5 lines, newest first, with mono timestamps; severe
// lines are tinted. Glass card, bottom-left of the command center.

import { useMemo } from "react";
import { useStore } from "../store";

const MAX_LINES = 5;

export default function AgentLog() {
  const logs = useStore((s) => s.logs);

  // Prefer the real agent narration (agent_log + notifications); fall back to all
  // lines so the feed is never empty before the first agent event arrives.
  const feed = useMemo(() => {
    const agentish = logs.filter(
      (l) => l.source === "agent_log" || l.source === "notification",
    );
    const base = agentish.length ? agentish : logs;
    return [...base].slice(-MAX_LINES).reverse(); // newest first
  }, [logs]);

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
        {feed.map((l, i) => (
          <div key={`${l.ts}-${i}`} className={`nemo-line lvl-${l.level}`}>
            <span className="nemo-ts">
              {new Date(l.ts).toLocaleTimeString("en-GB", { hour12: false }).slice(0, 5)}
            </span>
            <span className="nemo-msg">{l.message}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
