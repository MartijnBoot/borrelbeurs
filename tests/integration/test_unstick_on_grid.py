"""What B-07 is for: a crashed drink leaves an on-grid floor at the first order (AC15).

The unstick rule moves a quote pinned at its bound one step, but only when the
quote is exactly on the bound (`exchange/steps.py`). A Minimumprijs on the
Prijsstap grid is a price the engine can quote, so the rule fires; one off the
grid (1,24 on a 0,10 step, stored before B-07) quotes 1,20 below it, and the
rule never fires. Idle drift and noise are off, so only the order moves the
price after the Marktcrash has ended.
"""

from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.runtime.manipulation import start_event
from exchange import Params
from tests.integration.test_place_order import Market, _market

QUIET = Params(step_quant=0.1, bm_enabled=False, idle_strength=0.0, idle_rise_strength=0.0)
CRASH_MS = 10_000


async def _crashed(m: Market) -> int:
    """Run a Marktcrash to its end; Bier's quote at the floor."""
    await start_event(m.holder, "crash", CRASH_MS, clock=m.clock)
    for _ in range(CRASH_MS // 1_000 + 2):
        await m.tick()
    assert m.holder.state is not None and m.holder.state.jumps == ()
    return m.live()[m.drinks[0]]


async def _after_one_order(m: Market) -> int:
    bier = m.drinks[0]
    await m.place(m.request("k-unstick-1", {bier: (1, m.live()[bier])}))
    return m.live()[bier]


def test_an_on_grid_floor_is_left_at_the_first_order(settings: Settings, database_url: str) -> None:
    async def scenario() -> tuple[int, int]:
        async with _market(settings, database_url, bounds=(120, 500), params=QUIET) as m:
            return await _crashed(m), await _after_one_order(m)

    floor, after = asyncio.run(scenario())

    assert floor == 120
    assert after > 120


def test_an_off_grid_floor_is_not_left_at_the_first_order(
    settings: Settings, database_url: str
) -> None:
    """The old behaviour, as the evidence of the difference: below the bound, and stuck."""

    async def scenario() -> tuple[int, int]:
        async with _market(settings, database_url, bounds=(124, 500), params=QUIET) as m:
            return await _crashed(m), await _after_one_order(m)

    floor, after = asyncio.run(scenario())

    assert floor == 120
    assert after == 120
