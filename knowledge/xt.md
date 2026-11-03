# Expected threat (xT) and the 12x8 grid

Sources: Touchline `docs/xt-model.md`; Karun Singh, "Introducing Expected Threat (xT)", https://karun.in/blog/expected-threat.html ; socceraction `ExpectedThreat.rate`, https://github.com/ML-KULeuven/socceraction .

## Definition
Expected threat (xT) values a location on the pitch by how likely possession there is to lead to a goal within the next few actions. Moving the ball from a low-threat zone to a high-threat zone adds xT; moving it backwards can subtract xT.

## The 12x8 grid model
Touchline uses Karun Singh's public pretrained grid with twelve columns along the pitch length and eight rows across its width, stored unchanged in `app/models/open_xt_12x8_v1.json`. StatsBomb's 120 by 80 coordinates map directly onto the grid; both teams attack increasing x. No interpolation is applied, and no replay events train or update the grid.

## Action xT (xT added)
For each completed pass (including open-play crosses) and each carry, action xT is the end cell's value minus the start cell's value. Failed passes, set-piece restarts, shots and take-ons are excluded. Touchline+ sums positive action xT per team or player as "xT added".

## Limitations
xT ignores defenders, game state and the cost of losing the ball. It is a fan-facing attacking progression indicator, not a validated prediction, VAEP or StatsBomb's proprietary on-ball value (OBV).
