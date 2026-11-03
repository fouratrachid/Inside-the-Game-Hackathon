"""Choose the match source: StatsBomb open data, the synthetic match, or both.

`both` lists the fictional synthetic match first and appends the StatsBomb catalogue when it
can be fetched, so a hosted demo always has something to replay even if GitHub is unreachable.
"""

import logging

import httpx

from app.source import StatsBombSource
from app.synthetic import SyntheticSource

logger = logging.getLogger(__name__)


class CombinedSource:
    def __init__(self):
        self.synthetic = SyntheticSource()
        self.statsbomb = StatsBombSource()

    async def matches(self) -> list[dict]:
        matches = await self.synthetic.matches()
        try:
            matches += await self.statsbomb.matches()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("StatsBomb catalogue unavailable: %s", type(error).__name__)
        return matches

    async def events(self, match_id: int) -> list[dict]:
        synthetic_ids = {m["match_id"] for m in await self.synthetic.matches()}
        if match_id in synthetic_ids:
            return await self.synthetic.events(match_id)
        return await self.statsbomb.events(match_id)


def build_source(settings):
    return {
        "statsbomb": StatsBombSource,
        "synthetic": SyntheticSource,
        "both": CombinedSource,
    }[settings.source]()
