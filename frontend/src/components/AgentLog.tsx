// NEMOCLAW local-agent log — the last few narration lines (agent_log + notifications
// + system), with mono timestamps. Glass card, bottom-left of the command center.

import { useStore } from "../store";

export default function AgentLog() {
  const logs = useStore((s) => s.logs);
  const last = logs.slice(-3);

  return (
    <section className="nemoclaw glass" data-testid="agent-log">
      <header className="nemo-head">
        <span className="nemo-title">
          <span className="nemo-bars">❘❙</span> NEMOCLAW · LOCAL AGENT
        </span>
        <span className="nemo-voice">VOICE LIVE</span>
      </header>
      <div className="nemo-body">
        {last.length === 0 && <div className="nemo-empty">Awaiting agent activity…</div>}
        {last.map((l, i) => (
          <div key={i} className={`nemo-line lvl-${l.level}`}>
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
