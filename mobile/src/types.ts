/** Shapes of the Touchline+ server's SSE events and chat API (subset used by the app). */

export interface Team {
  id: number;
  name: string;
}

export interface Match {
  match_id: number;
  match_date: string;
  home_team: Team;
  away_team: Team;
  session_id?: string;
  source?: string;
}

export interface ReplayEvent {
  id: string;
  period: number;
  minute: number;
  second: number;
  type: { name: string };
  team?: Team;
  player?: { id?: number; name: string };
}

export interface Momentum {
  home: number | null;
  away: number | null;
  net_difference: number | null;
  period: number;
}

export interface Update {
  event: ReplayEvent;
  score: Record<string, number>;
  momentum: Momentum;
  shot_summary: Record<string, { shots: number; xg: number }>;
}

export interface MomentumShift {
  id: string;
  minute: number;
  period: number;
  since_minute: number;
  from_team: Team | null;
  to_team: Team;
  magnitude: number;
  sequences: string[][];
  players: string[];
  narration: string;
  cited_event_ids: string[];
}

export interface ChatAnswer {
  text: string;
  provider?: string;
  orchestrator?: string;
  tools_used?: { tool: string; args: Record<string, unknown> }[];
  evidence?: { id: string; minute: number; action: string }[];
  cited_sources?: string[];
  as_of?: { minute: number; second: number; period: number };
}
