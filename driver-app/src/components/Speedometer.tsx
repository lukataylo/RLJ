// Speedometer-style SVG gauge for the green-wave card.
// 240° sweep. The coloured arc shows current speed; a neon tick marks the
// green-wave target. Green when you're within ~2 km/h of target, else amber.

interface Props {
  speedKmh: number; // current speed
  targetKmh?: number; // green-wave target
  max?: number; // gauge max (km/h)
  size?: number;
}

const START = 150; // deg — bottom-left
const SWEEP = 240; // deg total

function polar(cx: number, cy: number, r: number, deg: number) {
  const rad = (deg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function arcPath(cx: number, cy: number, r: number, a0: number, a1: number) {
  const p0 = polar(cx, cy, r, a0);
  const p1 = polar(cx, cy, r, a1);
  const large = a1 - a0 > 180 ? 1 : 0;
  return `M ${p0.x} ${p0.y} A ${r} ${r} 0 ${large} 1 ${p1.x} ${p1.y}`;
}

export default function Speedometer({
  speedKmh,
  targetKmh,
  max = 60,
  size = 200,
}: Props) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 18;
  const cur = Math.max(0, Math.min(max, speedKmh));
  const curFrac = cur / max;
  const onTarget =
    targetKmh != null && Math.abs(speedKmh - targetKmh) <= 2.5;
  const color = onTarget ? "#34d399" : "#fff6ee";

  const fillEnd = START + SWEEP * curFrac;
  const tickDeg =
    targetKmh != null
      ? START + SWEEP * Math.max(0, Math.min(1, targetKmh / max))
      : null;
  const tickInner = tickDeg != null ? polar(cx, cy, r - 14, tickDeg) : null;
  const tickOuter = tickDeg != null ? polar(cx, cy, r + 6, tickDeg) : null;

  return (
    <div className="speedo">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <defs>
          <filter id="speedo-glow" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="3" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {/* track */}
        <path
          d={arcPath(cx, cy, r, START, START + SWEEP)}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth={12}
          strokeLinecap="round"
        />
        {/* current speed arc */}
        {curFrac > 0.001 && (
          <path
            d={arcPath(cx, cy, r, START, fillEnd)}
            fill="none"
            stroke={color}
            strokeWidth={12}
            strokeLinecap="round"
            filter="url(#speedo-glow)"
            style={{ transition: "stroke 0.4s ease" }}
          />
        )}
        {/* green-wave target tick */}
        {tickInner && tickOuter && (
          <line
            x1={tickInner.x}
            y1={tickInner.y}
            x2={tickOuter.x}
            y2={tickOuter.y}
            stroke="#f6c453"
            strokeWidth={4}
            strokeLinecap="round"
            filter="url(#speedo-glow)"
          />
        )}
        <text x={cx} y={cy + 2} textAnchor="middle" className="speedo-value">
          {Math.round(cur)}
        </text>
        <text x={cx} y={cy + 26} textAnchor="middle" className="speedo-unit">
          km/h
        </text>
        {targetKmh != null && (
          <text x={cx} y={cy + 52} textAnchor="middle" className="speedo-target">
            target {Math.round(targetKmh)}
          </text>
        )}
      </svg>
    </div>
  );
}
