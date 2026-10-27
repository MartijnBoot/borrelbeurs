"""The API harness: the real app over `TestClient`, on a scratch database and a fake clock.

**Fixtures are borrowed, not copied.** `scratch_database` and `database_url` are
imported from `tests/integration/conftest.py` (plan R17), so `tests/api` uses
the same migrated `bb_test_<hex>` database per session and empty tables per
test. Never the developer's own database.

**The app** is `create_app(clock=FakeClock(...), run_migrations=False)` (plan
PD16): the scratch database is migrated once per session, and a fake clock keeps
versions and session expiry deterministic. `DATABASE_URL` is pointed at the
scratch database and `get_settings`' cache cleared, so the lifespan reads it.

**https://testserver**, so the `Secure` session cookie round-trips, and a
same-origin `Origin` on every request by default (SD9); a test that wants none,
or a foreign one, overrides it.

**Cheap key hashes, here only** (B-11 SD7). Every test mints a key and logs in
with it, two argon2 hashes at production parameters: 11.3 % of this directory's
wall time in the plan's profile. `cheap_key_hash` swaps `_KEY_PARAMS` for
minimal ones. Every hash a test here makes and looks up goes through `key_hash`
in this one process, so both sides agree; what a test checks does not change.
Nowhere else (`tests/meta/test_argon2_swap.py`): `tests/unit` pins the real
parameters and a known-answer hash, and `tests/integration`, the real-app
harness and e2e hash in real processes with real parameters.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.api import security
from app.api.security import IssuedKey, issue_key
from app.core.config import Settings, get_settings
from app.db.keys import Role
from app.db.runs import add_drink, create_draft_run, go_live
from app.db.session import create_engine
from app.main import create_app
from exchange import Params
from tests.integration.conftest import database_url, scratch_database
from tests.support.clock import FakeClock

__all__ = ["database_url", "scratch_database"]

BASE_URL = "https://testserver"
T0 = 1_759_312_800_000

MintKey = Callable[..., str]
IssueKey = Callable[..., IssuedKey]
Login = Callable[..., TestClient]


@pytest.fixture(autouse=True)
def cheap_key_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """argon2id at its minimum cost for `key_hash`: one pass, 8 KiB, one lane (see above)."""
    cheap = {**security._KEY_PARAMS, "time_cost": 1, "memory_cost": 8, "parallelism": 1}
    monkeypatch.setattr(security, "_KEY_PARAMS", cheap)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0)


@pytest.fixture
def api_env(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    """The lifespan's environment, pointed at the per-test scratch database."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


@pytest.fixture
def client(api_env: str, clock: FakeClock) -> Iterator[TestClient]:
    app = create_app(clock=clock, run_migrations=False)
    with TestClient(app, base_url=BASE_URL, headers={"origin": BASE_URL}) as test_client:
        yield test_client


@pytest.fixture
def live_run(api_env: str, settings: Settings) -> int:
    """A live run of three drinks in the scratch database, made before the app boots."""

    async def scenario() -> int:
        engine = create_engine(settings.model_copy(update={"database_url": api_env}))
        try:
            async with engine.begin() as conn:
                run_id = await create_draft_run(
                    conn, name="Borrel", params=Params(step_quant=0.1), run_seed=7
                )
                for slot, name in enumerate(("Bier", "Wijn", "Fris")):
                    await add_drink(
                        conn,
                        run_id,
                        name=name,
                        slot=slot,
                        p_min_cents=150,
                        p0_cents=260,
                        p_max_cents=500,
                        a=1.0,
                        d=0.1,
                        s0=1.0,
                        c=0.1,
                        bar_price_cents=260,
                    )
            await go_live(engine, run_id, now_ms=T0)
            return run_id
        finally:
            await engine.dispose()

    return asyncio.run(scenario())


@pytest.fixture
def live_client(live_run: int, client: TestClient) -> TestClient:
    """`client`, booted after `live_run` exists, so the holder rehydrates it."""
    return client


@pytest.fixture
def advance(client: TestClient, clock: FakeClock) -> Callable[[int], None]:
    """Move the fake clock on the app's own event loop (plan R3).

    The ticker and the lock watchdog sleep on it inside `TestClient`'s portal
    thread; `FakeClock` is not thread-safe, so advancing it from the test thread
    would wake their futures off-loop.
    """

    def move(ms: int) -> None:
        client.portal.call(clock.advance, ms)  # type: ignore[union-attr]

    return move


@pytest.fixture
def issued_key(api_env: str, settings: Settings) -> IssueKey:
    """Mint a key through `issue_key`, the way `app.cli.keys create` does; its `key_id` and key."""

    def issue(role: Role = "bar", label: str = "test key") -> IssuedKey:
        async def scenario() -> IssuedKey:
            engine = create_engine(settings.model_copy(update={"database_url": api_env}))
            try:
                async with engine.begin() as conn:
                    return await issue_key(conn, role=role, label=label)
            finally:
                await engine.dispose()

        return asyncio.run(scenario())

    return issue


@pytest.fixture
def mint_key(issued_key: IssueKey) -> MintKey:
    """`issued_key`, the raw key only."""

    def mint(role: Role = "bar", label: str = "test key") -> str:
        return issued_key(role, label).key

    return mint


@pytest.fixture
def login(client: TestClient, mint_key: MintKey) -> Login:
    """Mint a key for `role` and log `client` in with it; the client, now carrying the cookie."""

    def log_in(role: Role = "bar", label: str = "test key") -> TestClient:
        response = client.post("/api/auth/login", json={"key": mint_key(role, label)})
        assert response.status_code == 200, response.text
        return client

    return log_in
