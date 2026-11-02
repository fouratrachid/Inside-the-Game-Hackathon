import { StyleSheet, Text, View } from "react-native";

import { colors } from "../theme";
import type { MomentumShift } from "../types";

export function ShiftNotes({ shifts }: { shifts: MomentumShift[] }) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>Momentum shifts</Text>
      {shifts.length === 0 ? (
        <Text style={styles.empty}>No momentum shift detected yet.</Text>
      ) : (
        shifts.map((shift) => (
          <View key={shift.id} style={styles.note} testID={`shift-note-${shift.id}`}>
            <Text style={styles.time}>
              {shift.since_minute}′ → {shift.minute}′ · {shift.to_team.name}
            </Text>
            <Text style={styles.text}>{shift.narration}</Text>
            {shift.players.length ? (
              <Text style={styles.players}>Involved: {shift.players.slice(0, 3).join(", ")}</Text>
            ) : null}
          </View>
        ))
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: 16, borderRadius: 12, backgroundColor: colors.card, gap: 8 },
  title: { fontSize: 16, fontWeight: "700", color: colors.text },
  empty: { fontSize: 13, color: colors.muted },
  note: { borderTopWidth: StyleSheet.hairlineWidth, borderColor: colors.line, paddingTop: 8 },
  time: { fontWeight: "700", color: colors.shift, fontSize: 13 },
  text: { fontSize: 14, color: colors.text, lineHeight: 20, marginTop: 2 },
  players: { fontSize: 12, color: colors.muted, marginTop: 2 },
});
