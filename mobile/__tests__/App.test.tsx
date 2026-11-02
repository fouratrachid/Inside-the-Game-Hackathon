import { act, fireEvent, render, screen } from "@testing-library/react-native";

import App from "../App";
import { shift, update } from "./fixtures";

type Listener = (event: { data: string | null }) => void;

// A controllable stand-in for react-native-sse's EventSource.
const mockSources: MockEventSource[] = [];
class MockEventSource {
  listeners: Record<string, Listener[]> = {};
  closed = false;
  constructor(public url: string) {
    mockSources.push(this);
  }
  addEventListener(name: string, listener: Listener) {
    (this.listeners[name] ??= []).push(listener);
  }
  removeAllEventListeners() {
    this.listeners = {};
  }
  close() {
    this.closed = true;
  }
  emit(name: string, data: unknown) {
    for (const listener of this.listeners[name] ?? []) listener({ data: JSON.stringify(data) });
  }
}
jest.mock("react-native-sse", () => ({
  __esModule: true,
  default: jest.fn().mockImplementation((url: string) => new MockEventSource(url)),
}));

const match = {
  match_id: 1,
  match_date: "Fictional exhibition",
  home_team: { id: 101, name: "Northbridge FC" },
  away_team: { id: 202, name: "Southbank United" },
};

const fetchMock = jest.fn();
beforeEach(() => {
  mockSources.length = 0;
  fetchMock.mockReset();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

test("pick a match, follow the stream, see a shift and ask with the session id", async () => {
  fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => [match] });
  await render(<App base="http://api" />);
  await fireEvent.press(await screen.findByTestId("match-1"));
  expect(mockSources[0].url).toBe("http://api/matches/1/stream?speed=10&insights=false");

  await act(() => {
    mockSources[0].emit("match", { ...match, session_id: "sess-abcdefghijklmnop" });
    mockSources[0].emit("update", update(12, 0.05, [1, 0]));
    mockSources[0].emit("momentum_shift", shift);
  });
  expect(screen.getByTestId("score")).toHaveTextContent("1 – 0");
  expect(screen.getByTestId("shift-note-shift-1")).toBeTruthy();
  expect(screen.getByTestId("shift-marker-shift-1")).toBeTruthy();

  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => ({ text: "Northbridge are on top.", provider: "Offline rule-based baseline" }),
  });
  await fireEvent.press(screen.getByText("Who has created the better chances so far?"));
  expect(await screen.findByText("Northbridge are on top.")).toBeTruthy();
  expect(JSON.parse(fetchMock.mock.calls[1][1].body).session_id).toBe("sess-abcdefghijklmnop");

  await act(() => mockSources[0].emit("complete", { match_id: 1 }));
  expect(mockSources[0].closed).toBe(true);
  expect(screen.getByTestId("clock")).toHaveTextContent(/Full time/);
});

test("stream errors are shown and stop replay returns to the picker", async () => {
  fetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => [match] });
  await render(<App base="http://api" />);
  await fireEvent.press(await screen.findByTestId("match-1"));
  await act(() => mockSources[0].emit("error", null));
  expect(screen.getByText("Connection interrupted. Restart the replay.")).toBeTruthy();
  await fireEvent.press(screen.getByText("Stop replay"));
  expect(await screen.findByText("Pick a match")).toBeTruthy();
});

test("explains when the server cannot be reached", async () => {
  fetchMock.mockRejectedValueOnce(new Error("network"));
  await render(<App base="http://api" />);
  expect(await screen.findByText("Could not reach http://api. Is the server running?")).toBeTruthy();
});
