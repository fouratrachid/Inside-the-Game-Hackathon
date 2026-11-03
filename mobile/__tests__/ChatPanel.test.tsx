import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";

import { ChatPanel, traceLine } from "../src/components/ChatPanel";

const fetchMock = jest.fn();

beforeEach(() => {
  fetchMock.mockReset();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

function respond(status: number, body: unknown) {
  fetchMock.mockResolvedValueOnce({ ok: status < 400, status, json: async () => body });
}

test("sends only the question and session id, then shows answer and tool trace", async () => {
  respond(200, {
    text: "Northbridge lead on xG.",
    provider: "Gemini",
    orchestrator: "LangGraph",
    tools_used: [{ tool: "get_player_stats", args: { name: "Northbridge 7" } }],
    evidence: [{ id: "e1", minute: 12, action: "Shot · Saved" }],
  });
  await render(<ChatPanel base="http://api" sessionId="sess-1234567890123456" />);
  await fireEvent.changeText(screen.getByLabelText("Your question"), "Who leads?");
  await fireEvent.press(screen.getByLabelText("Ask"));
  expect(await screen.findByText("Northbridge lead on xG.")).toBeTruthy();
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("http://api/chat");
  expect(JSON.parse(init.body)).toEqual({
    question: "Who leads?",
    mode: "simple",
    session_id: "sess-1234567890123456",
  });
  expect(screen.getByText("used: get_player_stats(Northbridge 7)")).toBeTruthy();
  expect(screen.getByText("Evidence: 12′ Shot · Saved")).toBeTruthy();
});

test("shows the server's error detail", async () => {
  respond(404, { detail: "Replay session not found or expired. Restart the replay." });
  await render(<ChatPanel base="http://api" sessionId="sess-1234567890123456" />);
  await fireEvent.press(screen.getByText("What is field tilt?"));
  expect(await screen.findByText(/Replay session not found/)).toBeTruthy();
});

test("does nothing without a session", async () => {
  await render(<ChatPanel base="http://api" sessionId={null} />);
  expect(screen.getByText("Start a replay to ask questions.")).toBeTruthy();
  await fireEvent.press(screen.getByText("What is field tilt?"));
  await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
});

test("trace line formatting", () => {
  expect(traceLine({ text: "x" })).toBeNull();
  expect(
    traceLine({
      text: "x",
      tools_used: [
        { tool: "get_match_stats", args: {} },
        { tool: "compare_periods", args: { start_min: 0, end_min: 45 } },
      ],
    }),
  ).toBe("used: get_match_stats() → compare_periods(0, 45)");
});
