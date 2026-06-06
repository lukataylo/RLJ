// NemoClaw's agent eyes — a dot-matrix display where lit / heavier dots form two
// eyes that BLINK and FOLLOW THE CURSOR. Two variants:
//   "button" — compact, dots arranged in a PILL shape (rounded corners dropped),
//              no frame; used in the NemoClaw header.
//   "field"  — a full-bleed dot field (the eyes are just brighter dots within the
//              surrounding background dots, edges masked so there's no frame);
//              used as the voice-overlay background.

import { useEffect, useRef, useState } from "react";

// One eye = a rounded 4×4 block; the centre 2×2 is the brighter "pupil".
const EYE = [
  [0, 1, 1, 0],
  [1, 1, 1, 1],
  [1, 1, 1, 1],
  [0, 1, 1, 0],
];
const PUPIL = new Set(["1,1", "1,2", "2,1", "2,2"]);

type Variant = "button" | "field";
const DIMS: Record<Variant, { cols: number; rows: number; gap: number }> = {
  button: { cols: 13, rows: 6, gap: 3 },
  field: { cols: 23, rows: 13, gap: 3 },
};

// Centre the two eyes (each 4 wide, `gap` cols apart) within the grid.
function eyeOrigins(cols: number, rows: number, gap: number) {
  const totalW = 4 + gap + 4;
  const startC = Math.round((cols - totalW) / 2);
  const startR = Math.round((rows - 4) / 2);
  return [
    { r: startR, c: startC },
    { r: startR, c: startC + 4 + gap },
  ];
}

// Pill mask for the button: drop the rounded corner cells so the dot field
// matches the pill silhouette (no rectangular block).
function inPill(r: number, c: number, cols: number, rows: number) {
  const top = r === 0 || r === rows - 1;
  const c1 = c <= 1 || c >= cols - 2;
  const corner0 = (r === 0 || r === rows - 1) && (c === 0 || c === cols - 1);
  return !(corner0 || (top && c1 && (c === 0 || c === cols - 1)));
}

export default function NemoFace({
  variant = "button",
  listening = false,
}: {
  variant?: Variant;
  listening?: boolean;
}) {
  const { cols, rows, gap } = DIMS[variant];
  const ref = useRef<HTMLSpanElement | null>(null);
  const [gaze, setGaze] = useState({ x: 0, y: 0 });
  const [blink, setBlink] = useState(false);
  const gazeRef = useRef(gaze);
  gazeRef.current = gaze;

  // Follow the cursor: shift the eye cluster ±1 dot toward the pointer.
  useEffect(() => {
    let raf = 0;
    const onMove = (e: MouseEvent) => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        const el = ref.current;
        if (!el) return;
        const r = el.getBoundingClientRect();
        const cx = r.left + r.width / 2;
        const cy = r.top + r.height / 2;
        const dz = 24;
        const nx = Math.abs(e.clientX - cx) < dz ? 0 : e.clientX > cx ? 1 : -1;
        const ny = Math.abs(e.clientY - cy) < dz ? 0 : e.clientY > cy ? 1 : -1;
        const g = gazeRef.current;
        if (g.x !== nx || g.y !== ny) setGaze({ x: nx, y: ny });
      });
    };
    window.addEventListener("mousemove", onMove);
    return () => {
      window.removeEventListener("mousemove", onMove);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, []);

  // Blink: a quick close every few seconds (faster while listening).
  useEffect(() => {
    let t: number;
    const schedule = () => {
      const gap2 = (listening ? 2200 : 3600) + ((cols * rows * 37) % 1500);
      t = window.setTimeout(() => {
        setBlink(true);
        window.setTimeout(() => setBlink(false), 130);
        schedule();
      }, gap2);
    };
    schedule();
    return () => window.clearTimeout(t);
  }, [listening, cols, rows]);

  const origins = eyeOrigins(cols, rows, gap);
  const on = new Set<string>();
  const pupil = new Set<string>();
  for (const o of origins) {
    for (let i = 0; i < EYE.length; i++) {
      for (let j = 0; j < EYE[i].length; j++) {
        if (!EYE[i][j]) continue;
        if (blink && i !== 1 && i !== 2) continue;
        const r = o.r + i + gaze.y;
        const c = o.c + j + gaze.x;
        on.add(`${r},${c}`);
        if (!blink && PUPIL.has(`${i},${j}`)) pupil.add(`${r},${c}`);
      }
    }
  }

  return (
    <span
      ref={ref}
      className={`nemo-face2 ${variant}${listening ? " listening" : ""}`}
      style={{ ["--cols" as string]: cols }}
      aria-hidden
    >
      <span className="dm2-grid" style={{ gridTemplateColumns: `repeat(${cols}, var(--d))` }}>
        {Array.from({ length: rows }).flatMap((_, r) =>
          Array.from({ length: cols }).map((__, c) => {
            const k = `${r},${c}`;
            if (variant === "button" && !inPill(r, c, cols, rows)) {
              return <span key={k} className="dm2-dot blank" />;
            }
            const cls = pupil.has(k) ? "pupil" : on.has(k) ? "on" : "off";
            return <span key={k} className={`dm2-dot ${cls}`} />;
          }),
        )}
      </span>
    </span>
  );
}
