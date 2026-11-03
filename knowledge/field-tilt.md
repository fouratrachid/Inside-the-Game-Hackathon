# Field tilt

Sources: Touchline README ("Top statistics"); Touchline `app/analytics.py` (`final_third_passes`, `field_tilt`).

## Definition
Field tilt is each team's share of completed passes that start in the attacking third. In StatsBomb coordinates, where both teams attack increasing x, the attacking third is x from 80 to 120 on the 120-long pitch. If the home team has completed 30 attacking-third passes and the away team 10, home field tilt is 75 percent.

## What it tells you
Field tilt describes territorial control: which team is spending more of its passing time near the opponent's goal. It is more focused than possession because it ignores passing in a team's own half.

## Limitations
Field tilt counts passes only, so a team that attacks with carries or long balls can be under-represented. Early in a match the sample is tiny and the percentage swings sharply. It is unknown (null) until at least one completed attacking-third pass exists.
