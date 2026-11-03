# Match momentum proxy and momentum shifts

Sources: Touchline `docs/xt-model.md` ("Active match-momentum proxy"); Touchline+ `app/shifts.py` documentation; Opta's public explanation of match momentum, https://theanalyst.com/articles/what-is-match-momentum .

## Momentum proxy
The momentum chart records each team's highest location-grid xT in each period-minute, using the destination of completed open-play passes and carries and the starting location of shots. Each minute peak is capped to 0.1. The current and previous three minutes are averaged with a 60-second half-life. The chart shows home minus away: home above the line, away below. It resets every period. It is a proxy for recent attacking threat, not a scoring or win probability.

## Momentum shifts
Touchline+ declares a momentum shift when the team leading the last five minutes of positive xT added changes and the new gap stays at least 0.03 for at least three match minutes. Shifts are at least five minutes apart and reset each period. Each shift lists the top three actions by xT added, grouped by possession into sequences, and the players involved.

## Missing data
If eligible actions have missing coordinates, that team's window is marked incomplete and the chart leaves a gap rather than inventing a value. Missing values are unknown, not zero.
