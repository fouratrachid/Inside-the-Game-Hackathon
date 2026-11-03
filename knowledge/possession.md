# Possession estimate

Sources: Touchline README ("Top statistics"); Touchline `app/analytics.py` (`possession_seconds`, method `event_time`).

## Definition
Touchline estimates possession from event time. Between two consecutive events in the same period, the elapsed seconds are credited to the team recorded in StatsBomb's `possession_team` field for the earlier event.

## Exclusions
Time after explicit stoppages is not credited: half ends, injury stoppages, referee ball drops, fouls committed, offsides and balls going out of play. Period breaks are skipped and penalty shoot-outs are excluded.

## Limitations
This is an estimate, not an official possession figure from ball tracking. Long gaps between recorded events can over-credit one team. Use it to compare teams within a match rather than across data providers.
