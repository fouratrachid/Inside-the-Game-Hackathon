# Passing networks

Sources: Touchline `app/passing.py`; Touchline README ("Passing network").

## Definition
A passing network shows each player at the average location of their passes and receptions, with lines between players whose thickness reflects how often they passed to each other. Touchline builds it live from completed passes already replayed.

## Window
The network describes the current window only: it resets after substitutions or sending-offs, so it is not a full-match player total. The window's start and reason are recorded with each team's network.

## Reading it
Central, well-connected players are hubs of build-up play. Positions are averages of recorded event locations, not tracking data, so they show tendencies rather than formations.
