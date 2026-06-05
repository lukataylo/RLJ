// Tiny inline SVG sparkline with a soft gradient fill. No dependencies.

interface Props {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  strokeWidth?: number;
}

let gradSeq = 0;

export default function Sparkline({
  values,
  width = 120,
  height = 34,
  color = "#3ddc84",
  strokeWidth = 1.6,
}: Props) {
  const id = `spark-${(gradSeq = (gradSeq + 1) % 100000)}`;
  const clean = values.filter((v) => Number.isFinite(v));
  if (clean.length < 2) {
    return (
      <svg width={width} height={height} className="sparkline" aria-hidden>
        <line
          x1={0}
          y1={height - 2}
          x2={width}
          y2={height - 2}
          stroke={color}
          strokeOpacity={0.35}
          strokeWidth={strokeWidth}
        />
      </svg>
    );
  }
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  const pad = 2;
  const n = clean.length;
  const x = (i: number) => pad + (i / (n - 1)) * (width - pad * 2);
  const y = (v: number) => height - pad - ((v - min) / span) * (height - pad * 2);

  const pts = clean.map((v, i) => [x(i), y(v)] as const);
  const line = pts.map(([px, py], i) => `${i === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const area = `${line} L${x(n - 1).toFixed(1)},${height} L${x(0).toFixed(1)},${height} Z`;

  // Approximate path length so the draw-in animation completes exactly.
  let len = 0;
  for (let i = 1; i < pts.length; i++) {
    len += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
  }

  return (
    <svg width={width} height={height} className="sparkline" aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.4} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
        <filter id={`${id}-glow`} x="-20%" y="-40%" width="140%" height="180%">
          <feGaussianBlur stdDeviation="1.4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <path d={area} fill={`url(#${id})`} />
      <path
        className="spark-draw"
        style={{ ["--spark-len" as string]: len.toFixed(0) }}
        d={line}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
        strokeLinecap="round"
        filter={`url(#${id}-glow)`}
      />
      <circle cx={x(n - 1)} cy={y(clean[n - 1])} r={2.6} fill={color} filter={`url(#${id}-glow)`} />
    </svg>
  );
}
