// Glass panel — the web app's `.glass`: --panel bg, hairline border, --radius.
import React from "react";
import { StyleProp, View, ViewStyle } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

export function GlassCard({
  children,
  style,
  solid,
}: {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  solid?: boolean;
}) {
  const { theme } = useTheme();
  return (
    <View
      style={[
        {
          backgroundColor: solid ? theme.panelSolid : theme.panel,
          borderColor: theme.hair,
          borderWidth: 1,
          borderRadius: theme.radius,
          padding: 14,
        },
        style,
      ]}
    >
      {children}
    </View>
  );
}
