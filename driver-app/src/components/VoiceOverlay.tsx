// Full-screen voice "listening" overlay — a faint dot-field with two amber
// dot-matrix eyes that blink, a prompt, a countdown and a Cancel control.
// Mirrors the PulseGo agent voice surface. Mock affordance: counts down then
// closes (no backend wired in the PWA).

import { useEffect, useRef, useState } from "react";

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

export default function VoiceOverlay({
  name,
  onClose,
}: {
  name?: string;
  onClose: () => void;
}) {
  const [secs, setSecs] = useState(LISTEN_SECONDS);

  useEffect(() => {
    const id = window.setInterval(() => {
      setSecs((s) => {
        if (s <= 1) {
          window.clearInterval(id);
          onClose();
          return LISTEN_SECONDS;
        }
        return s - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [onClose]);

  const prompt = name ? `${name} — how are you doing today?` : "How can I help on the road?";

  return (
    <div className="voice-overlay" data-testid="voice-overlay" role="dialog" aria-label="Voice assistant listening">
      <button type="button" className="vo-close" aria-label="Close" onClick={onClose}>
        ✕
      </button>

      <div className="vo-top">
        <div className="vo-status">
          <span className="vo-rec" /> LISTENING · {secs}s
        </div>
        <h2 className="vo-prompt">{prompt}</h2>
      </div>

      <div className="vo-stage">
        <Eyes />
      </div>

      <div className="vo-bottom">
        <span className="vo-hint">speak naturally · {LISTEN_SECONDS} seconds</span>
        <button type="button" className="vo-cancel" data-testid="voice-cancel" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}
