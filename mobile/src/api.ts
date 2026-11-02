import type { ChatAnswer, Match } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function json<T>(response: Response): Promise<T> {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : "Request failed. Try again.";
    throw new ApiError(detail, response.status);
  }
  return data as T;
}

export async function fetchMatches(base: string): Promise<Match[]> {
  return json<Match[]>(await fetch(`${base}/matches`));
}

/** Ask the match. Only the session id is sent: the server builds the context itself. */
export async function askQuestion(
  base: string,
  sessionId: string,
  question: string,
  mode: "simple" | "analyst" = "simple",
): Promise<ChatAnswer> {
  const response = await fetch(`${base}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, mode, session_id: sessionId }),
  });
  return json<ChatAnswer>(response);
}

export function streamUrl(base: string, matchId: number, speed: number): string {
  return `${base}/matches/${matchId}/stream?speed=${speed}&insights=false`;
}
