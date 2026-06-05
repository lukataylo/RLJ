// Live agent narration feed (agent_log + notification + system events).

import { useEffect, useRef } from "react";
import { useStore } from "../store";

const LEVEL_CLASS: Record<string, string> = {
  warn: "log-warn",
  error: "log-error",
  info: "log-info",
};

export default function AgentLog() {
  const logs = useStore((s) => s.logs);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  return (
    <section className="log" data-testid="agent-log">
      <div className="log-title">
        <span>Agent Log</span>
        <span className="log-count">{logs.length}</span>
      </div>
      <div className="log-body">
        {logs.length === 0 && <div className="log-empty">Waiting for events…</div>}
        {logs.map((l, i) => (
          <div key={i} className={`log-line ${LEVEL_CLASS[l.level] ?? "log-info"}`}>
            <span className="log-ts">
              {new Date(l.ts).toLocaleTimeString("en-GB", { hour12: false })}
            </span>
            <span className={`log-tag tag-${l.source}`}>{l.source.replace("_", " ")}</span>
            <span className="log-msg">{l.message}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </section>
  );
}
