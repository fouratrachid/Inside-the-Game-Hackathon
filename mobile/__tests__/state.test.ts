import { formatClock, initialState, reducer } from "../src/state";
import { match, shift, update } from "./fixtures";

test("the match event stores the server session id needed by /chat", () => {
  const state = reducer(reducer(initialState, { type: "connect" }), { type: "match", data: match });
  expect(state.status).toBe("live");
  expect(state.sessionId).toBe("abc123abc123abc123abc1");
});

test("updates set score, clock and xG; momentum keeps one point per minute", () => {
  let state = reducer(initialState, { type: "match", data: match });
  state = reducer(state, { type: "update", data: update(3, 0.02) });
  state = reducer(state, { type: "update", data: update(3, 0.04, [1, 0]) });
  state = reducer(state, { type: "update", data: update(4, null, [1, 0]) });
  expect(state.score).toEqual([1, 0]);
  expect(formatClock(state.clock)).toBe("04:05");
  expect(state.xg).toEqual([0.25, 0]);
  expect(state.momentum).toEqual([{ period: 1, minute: 3, net: 0.04 }]);
  expect(state.events).toBe(3);
});

test("updates before the match event are ignored", () => {
  expect(reducer(initialState, { type: "update", data: update(1, 0.1) })).toBe(initialState);
});

test("shifts are newest first and deduplicated", () => {
  let state = reducer(initialState, { type: "momentum_shift", data: shift });
  state = reducer(state, { type: "momentum_shift", data: shift });
  state = reducer(state, { type: "momentum_shift", data: { ...shift, id: "shift-2" } });
  expect(state.shifts.map((s) => s.id)).toEqual(["shift-2", "shift-1"]);
});

test("complete, error and reset", () => {
  expect(reducer(initialState, { type: "complete" }).status).toBe("complete");
  const failed = reducer(initialState, { type: "error", message: "boom" });
  expect([failed.status, failed.error]).toEqual(["error", "boom"]);
  expect(reducer(failed, { type: "reset" })).toEqual(initialState);
  expect(formatClock(null)).toBe("00:00");
});
