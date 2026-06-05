// Prominent "Ask" voice button — UI / deep-link placeholder for the driver
// voice assistant. Tapping deep-links to the voice agent if a handler URL is
// configured; otherwise it shows a transient "listening" affordance so the
// gesture is demoable without the backend wired up.

import { useState } from "react";

// Deep-link target for the voice assistant (placeholder). A real build would
// point this at the voice agent (tel:, a custom scheme, or an in-app route).
const VOICE_DEEPLINK = "rlj-voice://driver/ask";

export default function AskButton() {
  const [listening, setListening] = useState(false);

  function ask() {
    setListening(true);
    // Best-effort deep link; harmless no-op if the scheme isn't registered.
    try {
      window.location.href = VOICE_DEEPLINK;
    } catch {
      /* ignore */
    }
    window.setTimeout(() => setListening(false), 2600);
  }

  return (
    <button
      type="button"
      className={`ask-fab ${listening ? "listening" : ""}`}
      data-testid="ask-voice"
      aria-label="Ask the voice assistant"
      onClick={ask}
    >
      <span className="ask-rings" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className="ask-mic" aria-hidden="true">🎙️</span>
      <span className="ask-label">{listening ? "Listening…" : "Ask"}</span>
    </button>
  );
}
