// Past jobs — delivered / failed, newest first. Pull-to-refresh re-fetches /jobs.
import React, { useCallback, useEffect, useState } from "react";
import { FlatList, RefreshControl, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { JobCard } from "../../src/components/JobCard";
import { getJobs } from "../../src/lib/api";
import { PAST } from "../../src/lib/format";
import { useStore } from "../../src/lib/store";
import { useTheme } from "../../src/theme/ThemeProvider";
import { FONT } from "../../src/theme/tokens";
import { Header } from "./jobs";

export default function History() {
  const { theme } = useTheme();
  const insets = useSafeAreaInsets();
  const [refreshing, setRefreshing] = useState(false);
  const jobs = useStore((s) => s.jobs);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    const res = await getJobs();
    if (res.ok && res.data) useStore.getState().setJobs(res.data);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const past = jobs
    .filter((j) => PAST.includes(j.status))
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));

  return (
    <View style={{ flex: 1, backgroundColor: theme.bg, paddingTop: insets.top + 12 }}>
      <Header title="History" subtitle={`${past.length} completed`} theme={theme} />
      <FlatList
        data={past}
        keyExtractor={(j) => j.id}
        contentContainerStyle={{ padding: 16, paddingBottom: 24 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={theme.accent} />
        }
        ListEmptyComponent={
          <Text style={{ color: theme.muted, fontFamily: FONT.body, textAlign: "center", marginTop: 48 }}>
            No completed jobs yet.
          </Text>
        }
        renderItem={({ item }) => <JobCard job={item} showStatus past />}
      />
    </View>
  );
}
