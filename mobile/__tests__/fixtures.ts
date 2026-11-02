import type { Match, MomentumShift, Update } from "../src/types";

/** Shared test fixtures (not a test file, so importing it registers no tests). */
export const match: Match = {
  match_id: 1,
  match_date: "Fictional exhibition",
  home_team: { id: 101, name: "Northbridge FC" },
  away_team: { id: 202, name: "Southbank United" },
  session_id: "abc123abc123abc123abc1",
};

export function update(minute: number, net: number | null, score = [0, 0]): Update {
  return {
    event: { id: `e${minute}-${net}`, period: 1, minute, second: 5, type: { name: "Pass" } },
    score: { "101": score[0], "202": score[1] },
    momentum: { home: 0, away: 0, net_difference: net, period: 1 },
    shot_summary: { "101": { shots: 1, xg: 0.25 }, "202": { shots: 0, xg: 0 } },
  };
}

export const shift: MomentumShift = {
  id: "shift-1",
  minute: 12,
  period: 1,
  since_minute: 9,
  from_team: null,
  to_team: { id: 101, name: "Northbridge FC" },
  magnitude: 0.12,
  sequences: [["e1", "e2"]],
  players: ["Northbridge 3"],
  narration: "Northbridge FC took over from 9′.",
  cited_event_ids: ["e2"],
};
