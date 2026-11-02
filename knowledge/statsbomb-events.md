# StatsBomb event types and fields used by Touchline

Sources: StatsBomb Open Data documentation, Events v4.0.0, https://github.com/statsbomb/open-data/tree/master/doc ; Hudl StatsBomb open data terms.

## Coordinates
StatsBomb uses a 120 by 80 pitch with the origin at the top-left. Each team's events are recorded attacking increasing x, in both halves. Touchline rotates only for display.

## Event fields
Every event has an `id`, `index` (match order), `period`, `timestamp` within the period, `minute`, `second`, `type`, `team`, `player` (where relevant), `location`, `possession` (a running possession number) and `possession_team`.

## Event types used
- **Pass**: `pass.end_location`, `pass.recipient`, `pass.outcome` (absent when completed), `pass.type` (Corner, Free Kick, Goal Kick, Kick Off, Throw-in).
- **Carry**: `carry.end_location`, a player moving with the ball.
- **Shot**: `shot.statsbomb_xg`, `shot.outcome` (Goal, Saved, Off T, Blocked, Post, Wayward, Saved to Post), `shot.body_part`, `shot.type`, `shot.freeze_frame` (recorded positions of other players at the moment of the shot).
- **Duel** with type Tackle, **Ball Recovery**, **Pressure**, **Foul Committed**, **Substitution**, **Half Start**, **Half End**, **Own Goal Against**.

## Possession sequences
Events sharing the same `possession` number belong to one spell of possession; Touchline+ uses this field to rebuild the chain of actions that led to a shot or a momentum shift.

## Attribution
Data provided by Hudl StatsBomb Open Data under its user agreement. Touchline streams historical events; it does not redistribute the data files.
