// Radial efficiency gauge (window-compliance %). SVG arc, green->amber->red ramp.

import { congestionRGB } from "../lib/palette";

interface Props {
  value: number; // 0..100
  label: string;
  size?: number;
}

export default function Gauge({ value, label, size = 132 }: Props) {
  const pct = Math.max(0, Math.min(100, value));
  const r = size / 2 - 12;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  // 270° sweep starting at the bottom-left.
  const sweep = 0.75;
  const dash = circumference * sweep;
  const offset = dash * (1 - pct / 100);
  // Higher compliance = greener; invert into the congestion ramp (0=green).
  const [rr, gg, bb] = congestionRGB(1 - pct / 100);
  const color = `rgb(${rr},${gg},${bb})`;

  return (
    <div className="gauge">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <g transform={`rotate(135 ${cx} ${cy})`}>
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke="rgba(255,255,255,0.08)"
            strokeWidth={10}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
          />
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={10}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
            strokeDashoffset={offset}
            style={{ transition: "stroke-dashoffset 0.6s ease, stroke 0.6s ease" }}
          />
        </g>
        <text x={cx} y={cy - 2} textAnchor="middle" className="gauge-value">
          {Math.round(pct)}
          <tspan className="gauge-pct">%</tspan>
        </text>
        <text x={cx} y={cy + 18} textAnchor="middle" className="gauge-cap">
          compliance
        </text>
      </svg>
      <div className="gauge-label">{label}</div>
    </div>
  );
}
