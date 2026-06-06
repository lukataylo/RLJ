// Upcoming jobs — my route's stops first (in sequence), then any other active
// jobs. Tapping a job focuses it on the Navigate map. Pull-to-refresh re-fetches.
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import { FlatList, RefreshControl, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { JobCard } from "../../src/components/JobCard";
import { getJobs } from "../../src/lib/api";
import { UPCOMING } from "../../src/lib/format";
import { selectMyJobs, useStore } from "../../src/lib/store";
import type { DeliveryJob } from "../../src/lib/types";
import { useTheme } from "../../src/theme/ThemeProvider";
import { FONT } from "../../src/theme/tokens";

export default function Jobs() {
  const { theme } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [refreshing, setRefreshing] = useState(false);

  const jobs = useStore((s) => s.jobs);
  const myJobs = useStore(selectMyJobs);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    const res = await getJobs();
    if (res.ok && res.data) useStore.getState().setJobs(res.data);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // My route jobs (ordered) first, then other upcoming jobs not in my route.
  const mine = myJobs.filter((j) => UPCOMING.includes(j.status));
  const mineIds = new Set(mine.map((j) => j.id));
  const others = jobs.filter(
    (j) => UPCOMING.includes(j.status) && !mineIds.has(j.id),
  );

  const data: Array<{ section?: string; job?: DeliveryJob; mine?: boolean }> = [];
  if (mine.length) {
    data.push({ section: "On your route" });
    mine.forEach((job) => data.push({ job, mine: true }));
  }
  if (others.length) {
    data.push({ section: "Other active jobs" });
    others.forEach((job) => data.push({ job }));
  }

  return (
    <View style={{ flex: 1, backgroundColor: theme.bg, paddingTop: insets.top + 12 }}>
      <Header title="Jobs" subtitle={`${mine.length + others.length} upcoming`} theme={theme} />
      <FlatList
        data={data}
        keyExtractor={(item, i) => item.section ?? `${item.job!.id}-${i}`}
        contentContainerStyle={{ padding: 16, paddingBottom: 24 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={theme.accent} />
        }
        ListEmptyComponent={
          <Text style={{ color: theme.muted, fontFamily: FONT.body, textAlign: "center", marginTop: 48 }}>
            No upcoming jobs. Pull to refresh.
          </Text>
        }
        renderItem={({ item }) =>
          item.section ? (
            <Text
              style={{
                color: theme.muted,
                fontFamily: FONT.bodySemi,
                fontSize: 10,
                letterSpacing: 1.4,
                marginTop: 6,
                marginBottom: 8,
              }}
            >
              {item.section.toUpperCase()}
            </Text>
          ) : (
            <JobCard
              job={item.job!}
              showStatus
              onPress={() =>
                router.navigate({ pathname: "/navigate", params: { jobId: item.job!.id } })
              }
            />
          )
        }
      />
    </View>
  );
}

export function Header({
  title,
  subtitle,
  theme,
}: {
  title: string;
  subtitle?: string;
  theme: ReturnType<typeof useTheme>["theme"];
}) {
  return (
    <View style={{ paddingHorizontal: 18, marginBottom: 4 }}>
      <Text style={{ color: theme.text, fontFamily: FONT.head, fontSize: 24 }}>{title}</Text>
      {subtitle ? (
        <Text style={{ color: theme.muted, fontFamily: FONT.bodyMed, fontSize: 13, marginTop: 2 }}>
          {subtitle}
        </Text>
      ) : null}
    </View>
  );
}
