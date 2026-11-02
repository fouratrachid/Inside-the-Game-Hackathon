import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";

import { fetchMatches } from "./src/api";
import { ChatPanel } from "./src/components/ChatPanel";
import { MatchPicker } from "./src/components/MatchPicker";
import { MomentumChart } from "./src/components/MomentumChart";
import { Scoreboard } from "./src/components/Scoreboard";
import { ShiftNotes } from "./src/components/ShiftNotes";
import { apiUrl } from "./src/config";
import { colors } from "./src/theme";
import type { Match } from "./src/types";
import { useReplay } from "./src/useReplay";

/** Touchline+ second screen: pick a match, follow the replay, read shifts, ask questions. */
export default function App({ base = apiUrl() }: { base?: string }) {
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { state, start, reset } = useReplay(base);

  useEffect(() => {
    let cancelled = false;
    fetchMatches(base)
      .then((list) => !cancelled && setMatches(list))
      .catch(() => !cancelled && setError(`Could not reach ${base}. Is the server running?`))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [base]);

  const watching = state.status !== "idle";
  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="dark" />
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.brand}>Touchline+</Text>
        <Text style={styles.subtitle}>Second screen · replayed event data, no spoilers</Text>
        {!watching ? (
          <MatchPicker
            matches={matches}
            loading={loading}
            error={error}
            onPick={(match) => start(match.match_id)}
          />
        ) : (
          <>
            <Scoreboard state={state} />
            {state.status === "connecting" ? <Text style={styles.muted}>Connecting…</Text> : null}
            {state.error ? <Text style={styles.error}>{state.error}</Text> : null}
            {state.match ? (
              <MomentumChart
                points={state.momentum}
                shifts={state.shifts}
                homeId={state.match.home_team.id}
              />
            ) : null}
            <ShiftNotes shifts={state.shifts} />
            <ChatPanel base={base} sessionId={state.sessionId} />
            <View>
              <Pressable onPress={reset} accessibilityRole="button" style={styles.stop}>
                <Text style={styles.stopText}>Stop replay</Text>
              </Pressable>
            </View>
          </>
        )}
        <Text style={styles.footer}>Data: Hudl StatsBomb open data or a fictional synthetic match.</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { padding: 16, gap: 12 },
  brand: { fontSize: 26, fontWeight: "800", color: colors.text },
  subtitle: { color: colors.muted, marginBottom: 4 },
  muted: { color: colors.muted },
  error: { color: colors.away },
  stop: { alignSelf: "center", padding: 10 },
  stopText: { color: colors.away, fontWeight: "600" },
  footer: { fontSize: 11, color: colors.muted, textAlign: "center", marginTop: 8 },
});
