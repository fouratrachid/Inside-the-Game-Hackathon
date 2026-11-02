import { StyleSheet, Text, View } from "react-native";

import { formatClock, type ReplayState } from "../state";
import { colors } from "../theme";

export function Scoreboard({ state }: { state: ReplayState }) {
  const match = state.match;
  if (!match) return null;
  return (
    <View style={styles.card} accessibilityRole="summary">
      <View style={styles.row}>
        <Text style={[styles.team, { color: colors.home }]} numberOfLines={1}>
          {match.home_team.name}
        </Text>
        <Text style={styles.score} testID="score">
          {state.score[0]} – {state.score[1]}
        </Text>
        <Text style={[styles.team, styles.right, { color: colors.away }]} numberOfLines={1}>
          {match.away_team.name}
        </Text>
      </View>
      <Text style={styles.meta} testID="clock">
        {formatClock(state.clock)} · xG {state.xg[0].toFixed(2)} – {state.xg[1].toFixed(2)} ·{" "}
        {state.status === "complete" ? "Full time" : `${state.events} events`}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: 16, borderRadius: 12, backgroundColor: colors.card },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  team: { flex: 1, fontSize: 15, fontWeight: "600" },
  right: { textAlign: "right" },
  score: { fontSize: 32, fontWeight: "700", color: colors.text, fontVariant: ["tabular-nums"] },
  meta: { marginTop: 6, textAlign: "center", color: colors.muted, fontSize: 12 },
});
