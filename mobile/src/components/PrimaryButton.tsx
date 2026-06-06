// Pulse-Red primary action button (web `.btn-yellow` → re-themed to accent),
// plus ghost + danger variants. Radius 11 to match the design tokens.
import React from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleProp,
  Text,
  ViewStyle,
} from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { FONT } from "../theme/tokens";

type Variant = "primary" | "ghost" | "danger";

export function PrimaryButton({
  label,
  onPress,
  variant = "primary",
  loading,
  disabled,
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: Variant;
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const { theme } = useTheme();
  const isGhost = variant === "ghost";
  const bg =
    variant === "primary"
      ? theme.accent
      : variant === "danger"
        ? theme.accentSoft
        : theme.fill;
  const fg =
    variant === "primary"
      ? theme.accentContrast
      : variant === "danger"
        ? theme.accent
        : theme.text;

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        {
          backgroundColor: variant === "primary" && pressed ? theme.accentPress : bg,
          borderColor: isGhost ? theme.hair : "transparent",
          borderWidth: isGhost ? 1 : 0,
          borderRadius: theme.radiusBtn,
          paddingVertical: 13,
          paddingHorizontal: 18,
          alignItems: "center",
          justifyContent: "center",
          opacity: disabled ? 0.5 : 1,
        },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <Text style={{ color: fg, fontFamily: FONT.bodySemi, fontSize: 15 }}>
          {label}
        </Text>
      )}
    </Pressable>
  );
}
