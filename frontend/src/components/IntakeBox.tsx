// NATURAL-LANGUAGE DELIVERY INTAKE ("offline Google-Maps" style).
// Type a plain-English delivery — "urgent sample from Guy's to Moorfields" —
// and POST /intake parses + creates the job. The orchestrator then emits
// job_created + plan_updated on the WS, which the app already consumes to draw
// the route on the map, so this component only triggers the POST and shows
// feedback (a transient confirmation on success, or an error + suggestion chips).

import { useEffect, useRef, useState } from "react";
import { postIntake, type IntakeResult } from "../api";

type Feedback =
  | { kind: "ok"; message: string }
  | { kind: "error"; error: string; suggestions: string[] };

const CONFIRM_MS = 6000;

export default function IntakeBox() {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const clearTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Drop any pending auto-clear timer on unmount.
  useEffect(() => () => {
    if (clearTimer.current) clearTimeout(clearTimer.current);
  }, []);

  const scheduleClear = () => {
    if (clearTimer.current) clearTimeout(clearTimer.current);
    clearTimer.current = setTimeout(() => setFeedback(null), CONFIRM_MS);
  };

  async function submit() {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setSending(true);
    setFeedback(null);
    if (clearTimer.current) clearTimeout(clearTimer.current);
    try {
      const res: IntakeResult = await postIntake(trimmed);
      if (res.ok) {
        const o = res.resolved?.origin?.name ?? res.job.origin?.name ?? "origin";
        const d =
          res.resolved?.destination?.name ?? res.job.destination?.name ?? "destination";
        const id = res.job?.id ?? "job";
        setFeedback({
          kind: "ok",
          message: res.message || `Created ${id}: ${o} → ${d}`,
        });
        setText("");
        scheduleClear();
      } else {
        setFeedback({
          kind: "error",
          error: res.error || "Could not create that delivery.",
          suggestions: res.suggestions ?? [],
        });
      }
    } catch {
      // Network / unexpected failure — keep the typed text so the user can retry.
      setFeedback({
        kind: "error",
        error: "Could not reach the orchestrator. Check the connection and retry.",
        suggestions: [],
      });
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="intake glass" data-testid="intake-box">
      <div className="intake-head">
        <span className="intake-title">New delivery</span>
        <span className="intake-hint">plain English</span>
      </div>

      <form
        className="intake-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <input
          className="intake-input"
          data-testid="intake-input"
          type="text"
          placeholder="e.g. urgent sample from Guy's to Moorfields"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={sending}
          aria-label="Describe the delivery in plain English"
        />
        <button
          type="submit"
          className="intake-send"
          data-testid="intake-send"
          disabled={sending || text.trim().length === 0}
        >
          {sending ? <span className="intake-spinner" aria-hidden /> : "Send"}
        </button>
      </form>

      {feedback?.kind === "ok" && (
        <div className="intake-ok" data-testid="intake-ok" role="status">
          ✓ {feedback.message}
        </div>
      )}

      {feedback?.kind === "error" && (
        <div className="intake-err" data-testid="intake-error" role="alert">
          <div className="intake-err-msg">{feedback.error}</div>
          {feedback.suggestions.length > 0 && (
            <div className="intake-chips">
              {feedback.suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="intake-chip"
                  onClick={() => {
                    setText(s);
                    setFeedback(null);
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
