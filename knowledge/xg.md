# Expected goals (xG)

Sources: StatsBomb Open Data documentation (Events v4, `shot.statsbomb_xg`), https://github.com/statsbomb/open-data/tree/master/doc ; Touchline README "Shot map" section.

## Definition
Expected goals (xG) is the probability, from 0 to 1, that a shot becomes a goal, estimated from the shot's characteristics such as distance and angle to goal, body part, shot type and the position of defenders and the goalkeeper. A shot with 0.25 xG would be scored about one time in four by an average finisher.

## How Touchline uses xG
Touchline does not compute its own xG for real matches. It shows StatsBomb's supplied `statsbomb_xg` value for each shot and sums them per team as match-to-date xG. Penalty shoot-out shots are excluded. In the fictional synthetic match, xG is an illustrative distance heuristic and is not calibrated.

## Reading xG carefully
xG describes chance quality, not finishing or luck on its own. A team can lead in xG and still trail on the scoreboard. Over a single match, xG totals are noisy; a few high-xG chances can dominate the total. xG says nothing about events that did not end in a shot.
