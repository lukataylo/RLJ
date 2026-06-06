// Small uppercase status/priority pill — echoes the web `.cap` label style
// (10px, letter-spacing) with a tinted soft background.
import React from "react";
import { Text, View } from "react-native";
import { FONT } from "../theme/tokens";

export function StatusPill({
  label,
  color,
}: {
  label: string;
  color: string;
}) {
  return (
    <View
      style={{
        alignSelf: "flex-start",
        paddingHorizontal: 8,
        paddingVertical: 3,
        borderRadius: 999,
        backgroundColor: tint(color, 0.16),
        borderWidth: 1,
        borderColor: tint(color, 0.4),
      }}
    >
      <Text
        style={{
          color,
          fontFamily: FONT.bodySemi,
          fontSize: 10,
          letterSpacing: 1.2,
        }}
      >
        {label.toUpperCase()}
      </Text>
    </View>
  );
}

// Turn a #RRGGBB into an rgba() string at the given alpha.
function tint(hex: string, alpha: number): string {
  const m = hex.replace("#", "");
  const n = m.length === 3 ? m.split("").map((c) => c + c).join("") : m;
  const r = parseInt(n.slice(0, 2), 16);
  const g = parseInt(n.slice(2, 4), 16);
  const b = parseInt(n.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}
