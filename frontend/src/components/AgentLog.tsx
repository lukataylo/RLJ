// NEMOCLAW local-agent feed — the live narration from the orchestrator's NemoClaw
// agent (real TfL disruptions + live re-plans), arriving as agent_log / notification
// WS events. Shows the last ~5 lines, newest first, with mono timestamps; severe
// lines are tinted. Glass card, bottom-left of the command center.
//
// You can also ASK NemoClaw a question: a free-text box + two preset prompts POST
// to /agent/ask; the answer streams back into this feed as an agent_log line tagged
// "nemotron" (plus a WS "agent_answer" event the store also surfaces here).

import { useEffect, useMemo, useRef, useState } from "react";
import { askAgent, executeAgentAction, postIntake } from "../api";
import { useStore } from "../store";
import { renderMarkdown } from "../lib/markdown";
import type { LogLine } from "../store";
import NemoFace from "./NemoFace";
import {
  speechSupported,
  startListening,
  prepareSpeech,
  speakElevenLabs,
  stopSpeaking,
  type Listener,
} from "../lib/voice";

const MAX_LINES = 6;
const LISTEN_SECONDS = 15;

// Intent detection: treat the text as a delivery request when it has a
// "from … to …" shape OR mentions a courier/sample verb. Otherwise it's a
// question routed to the NemoClaw agent.
const DELIVERY_FROM_TO = /\bfrom\b[\s\S]*\bto\b/i;
const DELIVERY_VERBS =
  /\b(deliver|pick[\s-]?up|collect|drop[\s-]?off|transport|bring|take)\b/i;
const isDeliveryRequest = (text: string) =>
  DELIVERY_FROM_TO.test(text) || DELIVERY_VERBS.test(text);

// A Yes/No card the operator approves to run an agent-proposed action (reroute a
// courier, re-optimise the fleet, send a heads-up). "Yes" executes the action against
// its real orchestrator endpoint; the resulting plan/notification flows back over the
// WS like any other operator action.
function DecisionCard({ action }: { action: NonNullable<LogLine["action"]> }) {
  const pushLog = useStore((s) => s.pushLog);
  const [status, setStatus] =
    useState<"idle" | "running" | "done" | "declined">("idle");

  const approve = async () => {
    setStatus("running");
    try {
      await executeAgentAction(action);
      setStatus("done");
      pushLog({
        level: "info",
        message: `✓ ${action.confirm ?? "Done"} — ${action.label.replace(/\?$/, "")}.`,
        source: "agent_log",
      });
    } catch {
      setStatus("idle");
      pushLog({
        level: "warn",
        message: `Couldn't ${(action.confirm ?? "run that").toLowerCase()} — try again.`,
        source: "system",
      });
    }
  };

  if (status === "done")
    return (
      <div className="nemo-decision done" data-testid="decision-card">
        <span className="nemo-decision-result">✓ {action.confirm ?? "Done"}</span>
      </div>
    );
  if (status === "declined")
    return (
      <div className="nemo-decision declined" data-testid="decision-card">
        <span className="nemo-decision-result">Dismissed</span>
      </div>
    );

  return (
    <div className="nemo-decision" data-testid="decision-card">
      <span className="nemo-decision-label">{action.label}</span>
      <div className="nemo-decision-btns">
        <button
          type="button"
          className="nemo-decision-yes"
          data-testid="decision-yes"
          disabled={status === "running"}
          onClick={approve}
        >
          {status === "running" ? "…" : (action.confirm ?? "Yes")}
        </button>
        <button
          type="button"
          className="nemo-decision-no"
          data-testid="decision-no"
          disabled={status === "running"}
          onClick={() => setStatus("declined")}
        >
          No
        </button>
      </div>
    </div>
  );
}

export default function AgentLog() {
  const logs = useStore((s) => s.logs);
  const lastAgentAnswer = useStore((s) => s.lastAgentAnswer);
  const pushLog = useStore((s) => s.pushLog);
  const setFocusJob = useStore((s) => s.setFocusJob);
  const setFocusRoute = useStore((s) => s.setFocusRoute);
  const setFocusStops = useStore((s) => s.setFocusStops);

  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);

  // Voice console: a hands-free back-and-forth conversation. Each turn we listen
  // (browser speech recognition) → ask NemoClaw / create a delivery → speak the
  // reply (ElevenLabs) → automatically listen again, until the operator ends it.
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [secs, setSecs] = useState(LISTEN_SECONDS);
  const [heard, setHeard] = useState("");
  const [voicePhase, setVoicePhase] =
    useState<"listening" | "thinking" | "speaking" | "unsupported">("listening");
  const timerRef = useRef<number | null>(null);
  const recRef = useRef<Listener | null>(null);
  // True while the conversation overlay is live; gates the auto-listen loop so a
  // closed/cancelled session never re-opens the mic after a reply finishes.
  const convActiveRef = useRef(false);
  // Stable handle to "start the next listen turn", called from speech-end callbacks.
  const listenTurnRef = useRef<() => void>(() => {});
  const pendingSpeechTasksRef = useRef<Set<string>>(new Set());
  const spokenTaskIdsRef = useRef<Set<string>>(new Set());
  const receivedAnswersRef = useRef<Map<string, string>>(new Map());

  // Inline mic button state
  const [micActive, setMicActive] = useState(false);
  const inlineMicRef = useRef<Listener | null>(null);

  const cancelInlineMic = () => {
    inlineMicRef.current?.cancel();
    inlineMicRef.current = null;
    setMicActive(false);
  };

  const toggleMic = () => {
    if (micActive) {
      cancelInlineMic();
      return;
    }
    if (!speechSupported()) return;
    prepareSpeech();
    setMicActive(true);
    inlineMicRef.current = startListening({
      onPartial: (t) => setQuestion(t),
      onFinal: (t) => {
        setQuestion(t);
        inlineMicRef.current = null;
        setMicActive(false);
        void send(t);
      },
      onError: () => {
        inlineMicRef.current = null;
        setMicActive(false);
      },
      onEnd: () => {
        inlineMicRef.current = null;
        setMicActive(false);
      },
    });
  };

  const clearTimer = () => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const closeVoice = () => {
    convActiveRef.current = false;
    recRef.current?.cancel();
    recRef.current = null;
    clearTimer();
    stopSpeaking();
    setVoiceOpen(false);
  };

  // Start one listen turn. Stays within the live conversation (convActiveRef);
  // onFinal hands the transcript to send(), which (after the reply is spoken)
  // loops back here for the next turn.
  const beginListenTurn = () => {
    if (!convActiveRef.current) return;
    setHeard("");
    setSecs(LISTEN_SECONDS);
    setVoicePhase("listening");
    recRef.current = startListening({
      onPartial: (t) => setHeard(t),
      onFinal: (t) => {
        setHeard(t);
        setVoicePhase("thinking");
        void send(t, { fromConversation: true });
      },
      onError: (e) => {
        if (e === "unsupported") setVoicePhase("unsupported");
      },
    });
  };
  listenTurnRef.current = beginListenTurn;

  const openVoice = () => {
    prepareSpeech();
    setSecs(LISTEN_SECONDS);
    setHeard("");
    setVoiceOpen(true);
    if (!speechSupported()) {
      setVoicePhase("unsupported");
      return;
    }
    convActiveRef.current = true;
    beginListenTurn();
  };

  // Listening countdown (visual + safety stop if the speaker goes quiet too long).
  // Only runs during a listen turn; thinking/speaking phases pause it. Silence to
  // zero ends the whole conversation.
  useEffect(() => {
    if (!voiceOpen || voicePhase !== "listening") return;
    setSecs(LISTEN_SECONDS);
    timerRef.current = window.setInterval(() => {
      setSecs((s) => {
        if (s <= 1) {
          closeVoice();
          return LISTEN_SECONDS;
        }
        return s - 1;
      });
    }, 1000);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [voiceOpen, voicePhase]);

  // Speak only the answer matching a question submitted from this component.
  // In a live voice conversation, resume listening once the reply finishes.
  useEffect(() => {
    if (!lastAgentAnswer) return;
    const taskId = lastAgentAnswer.task_id;
    receivedAnswersRef.current.set(taskId, lastAgentAnswer.answer);
    if (
      pendingSpeechTasksRef.current.delete(taskId) &&
      !spokenTaskIdsRef.current.has(taskId)
    ) {
      spokenTaskIdsRef.current.add(taskId);
      if (convActiveRef.current) setVoicePhase("speaking");
      void speakElevenLabs(lastAgentAnswer.answer, () => {
        if (convActiveRef.current) listenTurnRef.current();
      });
    }
  }, [lastAgentAnswer]);

  useEffect(() => () => {
    inlineMicRef.current?.cancel();
    recRef.current?.cancel();
    if (timerRef.current) window.clearInterval(timerRef.current);
    stopSpeaking();
  }, []);

  // Prefer the real agent narration (agent_log + notifications); fall back to all
  // lines so the feed is never empty before the first agent event arrives.
  const feed = useMemo(() => {
    const agentish = logs.filter(
      (l) => l.source === "agent_log" || l.source === "notification",
    );
    const base = agentish.length ? agentish : logs;
    return [...base].slice(-MAX_LINES).reverse(); // newest first
  }, [logs]);

  const send = async (q: string, opts: { fromConversation?: boolean } = {}) => {
    const text = q.trim();
    if (!text || sending) return;
    prepareSpeech();
    setSending(true);

    // In a live voice conversation, speak `line` then resume listening; otherwise
    // a no-op. Used for delivery confirmations and error feedback so the loop
    // never stalls waiting on a reply that won't arrive over the answer channel.
    const speakAndContinue = (line: string) => {
      if (!opts.fromConversation || !convActiveRef.current) return;
      setVoicePhase("speaking");
      void speakElevenLabs(line, () => {
        if (convActiveRef.current) listenTurnRef.current();
      });
    };

    // A delivery request ("… from X to Y", "deliver sample …") goes to /intake,
    // which creates the job + re-plans; everything else is a question for the agent.
    if (isDeliveryRequest(text)) {
      try {
        const res = await postIntake(text);
        if (res.ok) {
          // Normalise to the multi-drop shape (postIntake backfills these from the
          // legacy single-drop fields, so both old and new backends work here).
          const jobs = res.jobs ?? (res.job ? [res.job] : []);
          const origin = res.resolved?.origin;
          const dests =
            res.resolved?.destinations ??
            (res.resolved?.destination ? [res.resolved.destination] : []);

          const o = origin?.name ?? jobs[0]?.origin?.name ?? "origin";
          const destNames = dests.length
            ? dests.map((d) => d.name)
            : jobs.map((j) => j.destination?.name).filter((n): n is string => !!n);
          const n = jobs.length || destNames.length || 1;
          const word = n === 1 ? "delivery" : "deliveries";
          const composed = destNames.length
            ? `✓ Created ${n} ${word}: ${o} → ${destNames.join(", ")} · route optimized`
            : `✓ Created ${n} ${word} · route optimized`;
          pushLog({
            level: "info",
            message: res.message || composed,
            source: "agent_log",
          });

          // Highlight the first new job on the map.
          if (jobs[0]?.id) setFocusJob(jobs[0].id);
          // Draw the delivery's OWN optimized multi-stop blue road route (origin →
          // drops in visit order). [] if Valhalla was down.
          setFocusRoute(res.route ?? []);
          // Numbered waypoint markers at the optimized stops (origin + drops) so a
          // multi-hop delivery is legible on top of the blue route.
          const stops = [
            ...(origin ? [{ name: origin.name, lat: origin.lat, lng: origin.lng }] : []),
            ...dests.map((d) => ({ name: d.name, lat: d.lat, lng: d.lng })),
          ];
          setFocusStops(stops.length ? stops : null);
          setQuestion("");
          speakAndContinue(`Done. Created a delivery from ${o} to ${d}.`);
        } else {
          const suffix = res.suggestions?.length
            ? ` Did you mean: ${res.suggestions.join(", ")}?`
            : "";
          pushLog({
            level: "warn",
            message: `${res.error || "Could not create that delivery."}${suffix}`,
            source: "agent_log",
          });
          // keep the text so the user can edit and retry
          speakAndContinue(
            `${res.error || "I couldn't create that delivery."}${suffix}`,
          );
        }
      } catch {
        pushLog({
          level: "warn",
          message: "Could not reach the orchestrator — delivery not created.",
          source: "system",
        });
        speakAndContinue("I couldn't reach the dispatcher to create that delivery.");
      } finally {
        setSending(false);
      }
      return;
    }

    // Question → NemoClaw agent. The spoken reply + auto-resume are driven by the
    // lastAgentAnswer effect (answers arrive over the WS channel).
    pushLog({
      level: "info",
      message: `You → NemoClaw: ${text}`,
      source: "agent_log",
    });
    try {
      const task = await askAgent(text);
      pendingSpeechTasksRef.current.add(task.id);
      const earlyAnswer = receivedAnswersRef.current.get(task.id);
      if (earlyAnswer && !spokenTaskIdsRef.current.has(task.id)) {
        pendingSpeechTasksRef.current.delete(task.id);
        spokenTaskIdsRef.current.add(task.id);
        if (convActiveRef.current) setVoicePhase("speaking");
        void speakElevenLabs(earlyAnswer, () => {
          if (convActiveRef.current) listenTurnRef.current();
        });
      }
      setQuestion("");
    } catch {
      pushLog({
        level: "warn",
        message: "Could not reach NemoClaw — question not queued.",
        source: "system",
      });
      speakAndContinue("I couldn't reach NemoClaw just now. Try again.");
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
          <NemoFace variant="field" listening={voicePhase === "listening"} />
          <div className="nvo-content">
            <div className="nvo-top">
              <div className="nvo-status">
                <span className="nvo-rec" />{" "}
                {voicePhase === "thinking"
                  ? "THINKING…"
                  : voicePhase === "speaking"
                    ? "SPEAKING…"
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
                {voicePhase === "thinking"
                  ? "asking NemoClaw…"
                  : voicePhase === "speaking"
                    ? "NemoClaw is replying…"
                    : "speak naturally — I'll keep listening"}
              </div>
              <button
                type="button"
                className="nvo-cancel"
                data-testid="nemo-voice-cancel"
                onClick={closeVoice}
              >
                End
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
          const ts = new Date(l.ts)
            .toLocaleTimeString("en-GB", { hour12: false })
            .slice(0, 5);
          if (l.agentAnswer) {
            // A NemoClaw answer: reasoning dimmed above, Markdown-styled answer, and
            // a Yes/No decision card when the agent proposed an action.
            return (
              <div
                key={l.taskId ?? `${l.ts}-${i}`}
                className="nemo-line lvl-info src-nemotron is-answer"
              >
                <span className="nemo-ts">{ts}</span>
                <div className="nemo-answer">
                  {l.reasoning && (
                    <div className="nemo-reasoning" data-testid="agent-reasoning">
                      <span className="nemo-reason-tag">Agent reasoning</span>
                      <span className="nemo-reason-text">{l.reasoning}</span>
                    </div>
                  )}
                  <div
                    className="nemo-md"
                    data-testid="agent-answer"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(l.message) }}
                  />
                  {l.action && <DecisionCard action={l.action} />}
                </div>
              </div>
            );
          }
          return (
            <div
              key={`${l.ts}-${i}`}
              className={`nemo-line lvl-${l.level}${nemotron ? " src-nemotron" : ""}`}
            >
              <span className="nemo-ts">{ts}</span>
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
        <button
          type="button"
          className={`nemo-ask-mic${micActive ? " active" : ""}`}
          data-testid="ask-mic"
          aria-label={micActive ? "Stop listening" : "Speak to NemoClaw"}
          title={micActive ? "Stop" : "Speak"}
          onClick={toggleMic}
          disabled={sending}
        >
          <svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13" aria-hidden>
            <path d="M12 1a4 4 0 0 0-4 4v7a4 4 0 0 0 8 0V5a4 4 0 0 0-4-4zm-2 4a2 2 0 0 1 4 0v7a2 2 0 0 1-4 0V5zm-5 6h2a5 5 0 0 0 10 0h2a7 7 0 0 1-6 6.92V21h3v2H8v-2h3v-3.08A7 7 0 0 1 5 11z" />
          </svg>
        </button>
        <input
          className="nemo-ask-input"
          data-testid="ask-input"
          type="text"
          placeholder="Ask NemoClaw, or 'deliver sample from Guy's to Moorfields'"
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
