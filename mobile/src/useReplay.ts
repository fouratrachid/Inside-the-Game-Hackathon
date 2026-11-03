import { useCallback, useEffect, useReducer, useRef } from "react";
import EventSource from "react-native-sse";

import { streamUrl } from "./api";
import { initialState, reducer } from "./state";

type ReplayEventName = "match" | "update" | "momentum_shift" | "complete";

/** Subscribe to a Touchline+ replay over SSE and fold events into ReplayState. */
export function useReplay(base: string) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const source = useRef<EventSource<ReplayEventName> | null>(null);

  const stop = useCallback(() => {
    source.current?.removeAllEventListeners();
    source.current?.close();
    source.current = null;
  }, []);

  const start = useCallback(
    (matchId: number, speed = 10) => {
      stop();
      dispatch({ type: "connect" });
      // Automatic reconnects would start a new server session; the web app disables them too.
      const es = new EventSource<ReplayEventName>(streamUrl(base, matchId, speed), {
        pollingInterval: 0,
      });
      source.current = es;
      const parse = (data: string | null) => (data ? JSON.parse(data) : null);
      es.addEventListener("match", (event) => dispatch({ type: "match", data: parse(event.data) }));
      es.addEventListener("update", (event) => dispatch({ type: "update", data: parse(event.data) }));
      es.addEventListener("momentum_shift", (event) =>
        dispatch({ type: "momentum_shift", data: parse(event.data) }),
      );
      es.addEventListener("complete", () => {
        dispatch({ type: "complete" });
        stop();
      });
      es.addEventListener("error", () => {
        dispatch({ type: "error", message: "Connection interrupted. Restart the replay." });
        stop();
      });
    },
    [base, stop],
  );

  /** Stop streaming and go back to the match picker. */
  const reset = useCallback(() => {
    stop();
    dispatch({ type: "reset" });
  }, [stop]);

  useEffect(() => stop, [stop]);

  return { state, start, stop, reset };
}
