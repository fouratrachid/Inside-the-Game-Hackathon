/**
 * Pure replay state: SSE events in, screen state out. Kept free of React Native so it can be
 * unit-tested and so the stream hook stays a thin adapter.
 */
import type { Match, MomentumShift, Update } from "./types";

export interface MomentumPoint {
  period: number;
  minute: number;
  net: number;
}

export type Status = "idle" | "connecting" | "live" | "complete" | "error";

export interface ReplayState {
  status: Status;
  match: Match | null;
  sessionId: string | null;
  score: [number, number];
  clock: { period: number; minute: number; second: number } | null;
  xg: [number, number];
  momentum: MomentumPoint[];
  shifts: MomentumShift[];
  events: number;
  error: string | null;
}

export const initialState: ReplayState = {
  status: "idle",
  match: null,
  sessionId: null,
  score: [0, 0],
  clock: null,
  xg: [0, 0],
  momentum: [],
  shifts: [],
  events: 0,
  error: null,
};

export type Action =
  | { type: "connect" }
  | { type: "match"; data: Match }
  | { type: "update"; data: Update }
  | { type: "momentum_shift"; data: MomentumShift }
  | { type: "complete" }
  | { type: "error"; message: string }
  | { type: "reset" };

export function reducer(state: ReplayState, action: Action): ReplayState {
  switch (action.type) {
    case "connect":
      return { ...initialState, status: "connecting" };
    case "match":
      // The first SSE event carries the server session id that /chat needs.
      return {
        ...state,
        status: "live",
        match: action.data,
        sessionId: action.data.session_id ?? null,
      };
    case "update": {
      const match = state.match;
      if (!match) return state;
      const { event, score, momentum, shot_summary: shots } = action.data;
      const home = String(match.home_team.id);
      const away = String(match.away_team.id);
      const point: MomentumPoint | null =
        momentum.net_difference === null
          ? null
          : { period: event.period, minute: event.minute, net: momentum.net_difference };
      // One point per period-minute, like the web chart: the latest value wins.
      const last = state.momentum[state.momentum.length - 1];
      const sameBucket = last && point && last.period === point.period && last.minute === point.minute;
      const momentumPoints = point
        ? sameBucket
          ? [...state.momentum.slice(0, -1), point]
          : [...state.momentum, point]
        : state.momentum;
      return {
        ...state,
        score: [score[home] ?? 0, score[away] ?? 0],
        clock: { period: event.period, minute: event.minute, second: event.second },
        xg: [shots?.[home]?.xg ?? 0, shots?.[away]?.xg ?? 0],
        momentum: momentumPoints,
        events: state.events + 1,
      };
    }
    case "momentum_shift":
      if (state.shifts.some((shift) => shift.id === action.data.id)) return state;
      return { ...state, shifts: [action.data, ...state.shifts] };
    case "complete":
      return { ...state, status: "complete" };
    case "error":
      return { ...state, status: "error", error: action.message };
    case "reset":
      return initialState;
  }
}

export function formatClock(clock: ReplayState["clock"]): string {
  if (!clock) return "00:00";
  return `${String(clock.minute).padStart(2, "0")}:${String(clock.second).padStart(2, "0")}`;
}
