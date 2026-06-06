// Speedometer gauge (react-native-svg) — 240° sweep. Coloured arc = current
// speed; a tick marks the green-wave target. Green when within ~2.5 km/h of
// target, else cream. RN port of driver-app/src/components/Speedometer.tsx.
import React from "react";
import { View } from "react-native";
import Svg, { Line, Path, Text as SvgText } from "react-native-svg";
import { useTheme } from "../theme/ThemeProvider";
import { FONT } from "../theme/tokens";

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

export function Speedometer({
  speedKmh,
  targetKmh,
  max = 60,
  size = 168,
}: {
  speedKmh: number;
  targetKmh?: number;
  max?: number;
  size?: number;
}) {
  const { theme } = useTheme();
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 16;
  const cur = Math.max(0, Math.min(max, speedKmh));
  const curFrac = cur / max;
  const onTarget = targetKmh != null && Math.abs(speedKmh - targetKmh) <= 2.5;
  const color = onTarget ? theme.green : theme.text;

  const fillEnd = START + SWEEP * curFrac;
  const tickDeg =
    targetKmh != null
      ? START + SWEEP * Math.max(0, Math.min(1, targetKmh / max))
      : null;
  const tickInner = tickDeg != null ? polar(cx, cy, r - 13, tickDeg) : null;
  const tickOuter = tickDeg != null ? polar(cx, cy, r + 6, tickDeg) : null;

  return (
    <View>
      <Svg width={size} height={size}>
        {/* track */}
        <Path
          d={arcPath(cx, cy, r, START, START + SWEEP)}
          fill="none"
          stroke={theme.fill2}
          strokeWidth={11}
          strokeLinecap="round"
        />
        {/* current speed arc */}
        {curFrac > 0.001 && (
          <Path
            d={arcPath(cx, cy, r, START, fillEnd)}
            fill="none"
            stroke={color}
            strokeWidth={11}
            strokeLinecap="round"
          />
        )}
        {/* green-wave target tick */}
        {tickInner && tickOuter && (
          <Line
            x1={tickInner.x}
            y1={tickInner.y}
            x2={tickOuter.x}
            y2={tickOuter.y}
            stroke={theme.amber}
            strokeWidth={4}
            strokeLinecap="round"
          />
        )}
        <SvgText
          x={cx}
          y={cy + 6}
          textAnchor="middle"
          fontSize={34}
          fontFamily={FONT.head}
          fill={theme.text}
        >
          {Math.round(cur)}
        </SvgText>
        <SvgText
          x={cx}
          y={cy + 26}
          textAnchor="middle"
          fontSize={11}
          fontFamily={FONT.bodyMed}
          fill={theme.muted}
        >
          km/h
        </SvgText>
        {targetKmh != null && (
          <SvgText
            x={cx}
            y={cy + 48}
            textAnchor="middle"
            fontSize={11}
            fontFamily={FONT.bodyMed}
            fill={theme.amber}
          >
            {`target ${Math.round(targetKmh)}`}
          </SvgText>
        )}
      </Svg>
    </View>
  );
}
