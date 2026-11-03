import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "../theme";
import type { Match } from "../types";

export function MatchPicker(props: {
  matches: Match[];
  onPick: (match: Match) => void;
  loading: boolean;
  error: string | null;
}) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>Pick a match</Text>
      {props.loading ? <Text style={styles.muted}>Loading matches…</Text> : null}
      {props.error ? <Text style={styles.error}>{props.error}</Text> : null}
      {props.matches.map((match) => (
        <Pressable
          key={match.match_id}
          onPress={() => props.onPick(match)}
          style={styles.item}
          accessibilityRole="button"
          testID={`match-${match.match_id}`}
        >
          <Text style={styles.name}>
            {match.home_team.name} vs {match.away_team.name}
          </Text>
          <Text style={styles.muted}>{match.match_date}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: 16, borderRadius: 12, backgroundColor: colors.card, gap: 6 },
  title: { fontSize: 16, fontWeight: "700", color: colors.text },
  item: { paddingVertical: 10, borderTopWidth: StyleSheet.hairlineWidth, borderColor: colors.line },
  name: { fontSize: 15, color: colors.text },
  muted: { fontSize: 12, color: colors.muted },
  error: { color: colors.away },
});
