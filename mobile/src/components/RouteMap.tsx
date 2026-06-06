// react-native-maps view for the Navigate tab: dark custom style, Pulse-Red
// route polyline, priority-coloured stop markers and a live courier marker.
import React, { useEffect, useRef } from "react";
import { Platform, StyleProp, ViewStyle } from "react-native";
import MapView, {
  Marker,
  Polyline,
  PROVIDER_DEFAULT,
  PROVIDER_GOOGLE,
  type Region,
} from "react-native-maps";
import type { GpsFix, LatLng, Stop } from "../lib/types";
import { useTheme } from "../theme/ThemeProvider";
import { MAP_STYLE_DARK, PRIORITY_HEX } from "../theme/tokens";

const LONDON: Region = {
  latitude: 51.508,
  longitude: -0.095,
  latitudeDelta: 0.08,
  longitudeDelta: 0.08,
};

export function RouteMap({
  geometry,
  stops,
  fix,
  follow,
  style,
}: {
  geometry: LatLng[];
  stops: Stop[];
  fix: GpsFix | null;
  follow?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const { theme } = useTheme();
  const mapRef = useRef<MapView>(null);

  // Keep the camera over the driver while navigating.
  useEffect(() => {
    if (follow && fix && mapRef.current) {
      mapRef.current.animateCamera(
        { center: { latitude: fix.lat, longitude: fix.lng }, zoom: 16 },
        { duration: 600 },
      );
    }
  }, [follow, fix?.lat, fix?.lng]);

  const coords = geometry.map((p) => ({ latitude: p.lat, longitude: p.lng }));

  return (
    <MapView
      ref={mapRef}
      style={[{ flex: 1 }, style]}
      provider={Platform.OS === "android" ? PROVIDER_GOOGLE : PROVIDER_DEFAULT}
      customMapStyle={theme.name === "dark" ? MAP_STYLE_DARK : []}
      initialRegion={LONDON}
      showsUserLocation={false}
      showsCompass={false}
      showsMyLocationButton={false}
      toolbarEnabled={false}
    >
      {coords.length >= 2 && (
        <>
          {/* glow underlay + main route line (Pulse Red) */}
          <Polyline coordinates={coords} strokeColor={theme.accentSoft} strokeWidth={11} />
          <Polyline coordinates={coords} strokeColor={theme.accent} strokeWidth={5} />
        </>
      )}

      {stops.map((s, i) => (
        <Marker
          key={`${s.job_id}-${s.kind}-${i}`}
          coordinate={{ latitude: s.location.lat, longitude: s.location.lng }}
          title={s.location.name || (s.kind === "pickup" ? "Pickup" : "Dropoff")}
          description={s.kind}
          pinColor={s.kind === "pickup" ? PRIORITY_HEX.urgent : theme.green}
        />
      ))}

      {fix && (
        <Marker
          coordinate={{ latitude: fix.lat, longitude: fix.lng }}
          anchor={{ x: 0.5, y: 0.5 }}
          flat
          rotation={fix.heading_deg || 0}
        >
          <CourierDot color={theme.accent} ring={theme.accentSoft} />
        </Marker>
      )}
    </MapView>
  );
}

import { View } from "react-native";
function CourierDot({ color, ring }: { color: string; ring: string }) {
  return (
    <View
      style={{
        width: 28,
        height: 28,
        borderRadius: 14,
        backgroundColor: ring,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <View
        style={{
          width: 14,
          height: 14,
          borderRadius: 7,
          backgroundColor: color,
          borderWidth: 2,
          borderColor: "#fff",
        }}
      />
    </View>
  );
}
