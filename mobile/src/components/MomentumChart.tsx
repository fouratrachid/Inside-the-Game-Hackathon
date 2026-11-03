import { StyleSheet, Text, View } from "react-native";
import Svg, { Line, Path, Polygon } from "react-native-svg";

import type { MomentumPoint } from "../state";
import { colors } from "../theme";
import type { MomentumShift } from "../types";

const WIDTH = 320;
const HEIGHT = 120;
const MID = HEIGHT / 2;

/** Pure geometry so it can be tested without rendering. */
export function chartGeometry(points: MomentumPoint[], shifts: MomentumShift[], homeId: number) {
  const total = Math.max(10, ...points.map((p) => p.minute + 1));
  const x = (minute: number) => (minute / total) * WIDTH;
  const y = (net: number) => MID - (Math.max(-0.1, Math.min(0.1, net)) / 0.1) * (MID - 6);
  const area = points.length
    ? `M ${x(points[0].minute)} ${MID} ` +
      points.map((p) => `L ${x(p.minute).toFixed(1)} ${y(p.net).toFixed(1)}`).join(" ") +
      ` L ${x(points[points.length - 1].minute)} ${MID} Z`
    : "";
  const markers = shifts.map((shift) => ({
    id: shift.id,
    x: x(shift.minute),
    home: shift.to_team.id === homeId,
  }));
  return { area, markers };
}

export function MomentumChart(props: {
  points: MomentumPoint[];
  shifts: MomentumShift[];
  homeId: number;
}) {
  const { area, markers } = chartGeometry(props.points, props.shifts, props.homeId);
  return (
    <View style={styles.card}>
      <Text style={styles.title}>Match momentum</Text>
      <Text style={styles.caption}>Recent attacking threat (xT proxy) · home above, away below</Text>
      <Svg
        width="100%"
        height={HEIGHT}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        accessibilityLabel={`Momentum chart with ${markers.length} momentum shifts`}
      >
        {area ? <Path d={area} fill={colors.home} opacity={0.85} testID="momentum-area" /> : null}
        <Line x1={0} y1={MID} x2={WIDTH} y2={MID} stroke={colors.line} strokeWidth={1} />
        {markers.map((m) => (
          <Polygon
            key={m.id}
            testID={`shift-marker-${m.id}`}
            points={
              m.home
                ? `${m.x},${MID - 12} ${m.x + 6},${MID - 2} ${m.x - 6},${MID - 2}`
                : `${m.x},${MID + 12} ${m.x + 6},${MID + 2} ${m.x - 6},${MID + 2}`
            }
            fill={m.home ? colors.home : colors.away}
          />
        ))}
      </Svg>
      {!area ? <Text style={styles.empty}>Waiting for the first actions…</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { padding: 16, borderRadius: 12, backgroundColor: colors.card, gap: 4 },
  title: { fontSize: 16, fontWeight: "700", color: colors.text },
  caption: { fontSize: 12, color: colors.muted },
  empty: { fontSize: 12, color: colors.muted, textAlign: "center" },
});
