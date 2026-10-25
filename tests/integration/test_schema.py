"""The migrated schema, inspected: money is integer cents, revenue lives in one place.

AC9 and AC11 are claims about the *schema*, so these tests read
`information_schema.columns` from the migrated scratch database rather than the
models. The constraint tests write by direct SQL, as in `test_migrations.py`.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Iterable

import pytest
from sqlalchemy import pool, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

PHASE_2_TABLES = frozenset(
    {
        "run",
        "run_config_revision",
        "drink",
        "engine_state",
        "price_tick",
        "order",
        "order_line",
        "news",
    }
)
PHASE_3_TABLES = frozenset({"auth_key", "market_event"})
PHASE_4_TABLES = frozenset({"theme"})
PHASE_6_TABLES = frozenset({"asset"})
PHASE_7_TABLES = frozenset({"product", "export"})
PHASE_8_TABLES = frozenset({"schema_compat"})
B_04_TABLES = frozenset({"settings_profile"})
B_05_TABLES = frozenset({"wallet", "wallet_entry", "wallet_settings"})

# PD4: SD5's three columns plus the singleton key; Phase 6 adds the custom
# theme (SD28) and one pointer per image slot (SD29).
THEME_COLUMNS = frozenset(
    {
        "id",
        "preset",
        "revision",
        "updated_at",
        "custom_tokens",
        "custom_font",
        "bg_asset_id",
        "header_asset_id",
        "logo_asset_id",
        "promo_asset_id",
    }
)

# AC6c (schema half): an access key's secret is stored only as its argon2id hash.
AUTH_KEY_COLUMNS = frozenset(
    {"key_id", "label", "role", "secret_hash", "created_at", "revoked_at", "last_used_at"}
)

INTEGER_TYPES = frozenset({"integer", "bigint"})
FLOAT_TYPES = frozenset({"real", "double precision", "numeric", "money"})

# Float columns that are not money: demand coefficients, and the continuous
# price an order line records as a diagnostic beside the cents it charged.
NON_MONEY_FLOATS = frozenset(
    {
        ("drink", "a"),
        ("drink", "d"),
        ("drink", "s0"),
        ("drink", "c"),
        ("order_line", "p_cont"),
    }
)

REVENUE_PATTERN = re.compile(r"revenue|total|earn", re.IGNORECASE)
THE_REVENUE_COLUMN = ("order_line", "line_total_cents")
# Phase 7 SD6: an export records the total its file contains, a checksum built
# from `order_line` in the export's snapshot. No query reads revenue from it.
EXPORT_FILE_TOTAL = ("export", "total_cents")

Column = tuple[str, str, str]  # table, column, data type


async def _columns(url: str) -> list[Column]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT table_name, column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
                )
            )
            return [(str(t), str(c), str(d)) for t, c, d in result]
    finally:
        await engine.dispose()


def money_violations(columns: Iterable[Column]) -> list[str]:
    """Every `*_cents` column that is not an integer, and every float that is not allowlisted."""
    faults = []
    for table, column, data_type in columns:
        if column.endswith("_cents") and data_type not in INTEGER_TYPES:
            faults.append(f"{table}.{column} is {data_type}, not integer cents")
        if data_type in FLOAT_TYPES and (table, column) not in NON_MONEY_FLOATS:
            faults.append(f"{table}.{column} is {data_type}; a euro amount must be integer cents")
    return faults


def test_the_application_tables_are_the_ones_inspected(database_url: str) -> None:
    """Anti-vacuity: the inspection below reaches every table, Phase 2 SD4 through B-05."""
    tables = {table for table, _, _ in asyncio.run(_columns(database_url))}

    assert tables == (
        PHASE_2_TABLES
        | PHASE_3_TABLES
        | PHASE_4_TABLES
        | PHASE_6_TABLES
        | PHASE_7_TABLES
        | PHASE_8_TABLES
        | B_04_TABLES
        | B_05_TABLES
    )


def test_every_money_column_is_integer_cents(database_url: str) -> None:
    """AC9 (D-09)."""
    columns = asyncio.run(_columns(database_url))

    assert money_violations(columns) == []
    assert {(t, c) for t, c, _ in columns} >= NON_MONEY_FLOATS, "allowlist names a lost column"


@pytest.mark.parametrize(
    ("injected", "fault"),
    [
        (("order", "price", "numeric"), "order.price is numeric"),
        (("drink", "bar_price_cents", "double precision"), "not integer cents"),
        (("run", "fee", "money"), "run.fee is money"),
        (("order_line", "unit_price_cents", "numeric"), "not integer cents"),
    ],
)
def test_the_money_detector_flags_an_injected_column(injected: Column, fault: str) -> None:
    """The detector is not vacuous: a future `price NUMERIC` would fail AC9."""
    faults = money_violations([("drink", "a", "double precision"), injected])

    assert any(fault in f for f in faults), faults


def test_revenue_is_stored_only_as_order_line_totals(database_url: str) -> None:
    """AC11 (D-10): no other table or column stores revenue."""
    columns = asyncio.run(_columns(database_url))
    revenue_like = {(t, c) for t, c, _ in columns if REVENUE_PATTERN.search(c)}

    assert revenue_like == {THE_REVENUE_COLUMN, EXPORT_FILE_TOTAL}


def _in_transaction(url: str, body: Callable[[AsyncConnection], Awaitable[None]]) -> None:
    async def scenario() -> None:
        engine = create_async_engine(url, poolclass=pool.NullPool)
        try:
            async with engine.begin() as connection:
                await body(connection)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


async def _run_and_drink(connection: AsyncConnection) -> tuple[int, int]:
    run_id: int = (
        await connection.execute(
            text("INSERT INTO run (name, run_seed, params) VALUES ('B', 1, '{}') RETURNING run_id")
        )
    ).scalar_one()
    drink_id: int = (
        await connection.execute(
            text(
                "INSERT INTO drink (run_id, slot, name, name_key, p_min_cents, p0_cents, "
                "p_max_cents, a, d, s0, c, bar_price_cents) VALUES (:run_id, 0, 'Bier', 'bier', "
                "150, 260, 500, 0, 0, 0, 0, 260) RETURNING drink_id"
            ),
            {"run_id": run_id},
        )
    ).scalar_one()
    return int(run_id), int(drink_id)


async def _order(connection: AsyncConnection, run_id: int, key: str) -> int:
    result = await connection.execute(
        text(
            'INSERT INTO "order" (run_id, idempotency_key, version, wall_ts_ms) '
            "VALUES (:run_id, :key, 1, 0) RETURNING order_id"
        ),
        {"run_id": run_id, "key": key},
    )
    return int(result.scalar_one())


async def _line(
    connection: AsyncConnection, order_id: int, drink_id: int, *, qty: int, unit: int, total: int
) -> None:
    await connection.execute(
        text(
            "INSERT INTO order_line (order_id, drink_id, qty, unit_price_cents, "
            "line_total_cents, p_cont) VALUES (:order_id, :drink_id, :qty, :unit, :total, 2.6)"
        ),
        {"order_id": order_id, "drink_id": drink_id, "qty": qty, "unit": unit, "total": total},
    )


def test_a_capitalised_news_level_is_rejected_by_the_database(database_url: str) -> None:
    """AC16 (database half), SD13."""

    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await connection.execute(
            text("INSERT INTO news (run_id, ts_ms, level, text) VALUES (:r, 1, 'Info', 'x')"),
            {"r": run_id},
        )

    with pytest.raises(IntegrityError, match="news_level_check"):
        _in_transaction(database_url, write)


def test_the_four_lowercase_news_levels_are_accepted(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        for level in ("info", "success", "warning", "danger"):
            await connection.execute(
                text("INSERT INTO news (run_id, ts_ms, level, text) VALUES (:r, 1, :l, 'x')"),
                {"r": run_id, "l": level},
            )

    _in_transaction(database_url, write)


def test_an_unknown_tick_source_is_rejected(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await connection.execute(
            text(
                "INSERT INTO price_tick (run_id, version, source, prices, wall_ts_ms) "
                "VALUES (:r, 0, 'bogus', '{}', 0)"
            ),
            {"r": run_id},
        )

    with pytest.raises(IntegrityError, match="price_tick_source_check"):
        _in_transaction(database_url, write)


def test_the_known_tick_sources_are_accepted(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        for version, source in enumerate(
            ("tick", "order", "jump", "idle", "reset", "gap", "config")
        ):
            await connection.execute(
                text(
                    "INSERT INTO price_tick (run_id, version, source, prices, wall_ts_ms) "
                    "VALUES (:r, :v, :s, '{}', 0)"
                ),
                {"r": run_id, "v": version, "s": source},
            )

    _in_transaction(database_url, write)


def test_a_duplicate_idempotency_key_is_rejected(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await _order(connection, run_id, "k-1")
        await _order(connection, run_id, "k-1")

    with pytest.raises(IntegrityError, match="idempotency_key"):
        _in_transaction(database_url, write)


def test_a_line_total_must_equal_qty_times_unit_price(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, drink_id = await _run_and_drink(connection)
        order_id = await _order(connection, run_id, "k-1")
        await _line(connection, order_id, drink_id, qty=2, unit=260, total=500)

    with pytest.raises(IntegrityError, match="order_line_total_check"):
        _in_transaction(database_url, write)


def test_a_consistent_line_is_accepted(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, drink_id = await _run_and_drink(connection)
        order_id = await _order(connection, run_id, "k-1")
        await _line(connection, order_id, drink_id, qty=2, unit=260, total=520)

    _in_transaction(database_url, write)


@pytest.mark.parametrize(("qty", "unit"), [(0, 260), (-1, 260), (1, -10)])
def test_a_line_needs_a_positive_qty_and_a_non_negative_price(
    database_url: str, qty: int, unit: int
) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, drink_id = await _run_and_drink(connection)
        order_id = await _order(connection, run_id, "k-1")
        await _line(connection, order_id, drink_id, qty=qty, unit=unit, total=qty * unit)

    with pytest.raises(IntegrityError, match=r"order_line_(qty|unit_price_cents)_check"):
        _in_transaction(database_url, write)


def test_one_drink_appears_once_per_order(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, drink_id = await _run_and_drink(connection)
        order_id = await _order(connection, run_id, "k-1")
        await _line(connection, order_id, drink_id, qty=1, unit=260, total=260)
        await _line(connection, order_id, drink_id, qty=1, unit=260, total=260)

    with pytest.raises(IntegrityError, match="order_line_order_id_drink_id_key"):
        _in_transaction(database_url, write)


# Phase 3 (T2): auth_key, market_event, order's actor and receipt, run's grace and candles.


def test_auth_key_holds_no_column_for_a_plaintext_secret(database_url: str) -> None:
    """AC6c (schema half), SD5: exactly SD5's columns; the secret only as its hash."""
    columns = {(c, d) for t, c, d in asyncio.run(_columns(database_url)) if t == "auth_key"}

    assert {c for c, _ in columns} == AUTH_KEY_COLUMNS
    assert ("secret_hash", "text") in columns


async def _auth_key(connection: AsyncConnection, *, role: str = "bar", label: str = "Bar 1") -> int:
    result = await connection.execute(
        text(
            "INSERT INTO auth_key (label, role, secret_hash) "
            "VALUES (:label, :role, '$argon2id$x') RETURNING key_id"
        ),
        {"label": label, "role": role},
    )
    return int(result.scalar_one())


def test_the_four_roles_are_accepted(database_url: str) -> None:
    """B-05 SD7 adds `kassa`."""

    async def write(connection: AsyncConnection) -> None:
        for role in ("display", "bar", "admin", "kassa"):
            await _auth_key(connection, role=role)

    _in_transaction(database_url, write)


def test_an_unknown_role_is_rejected(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        await _auth_key(connection, role="Admin")

    with pytest.raises(IntegrityError, match="auth_key_role_check"):
        _in_transaction(database_url, write)


@pytest.mark.parametrize("label", ["", "x" * 101], ids=["empty", "101-chars"])
def test_a_key_label_is_one_to_a_hundred_characters(database_url: str, label: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        await _auth_key(connection, label=label)

    with pytest.raises(IntegrityError, match="auth_key_label_check"):
        _in_transaction(database_url, write)


async def _market_event(
    connection: AsyncConnection, run_id: int, *, kind: str = "crash", start: int = 0, end: int = 1
) -> None:
    await connection.execute(
        text(
            "INSERT INTO market_event (run_id, kind, drink_ids, t_start_ms, t_end_ms) "
            "VALUES (:r, :kind, '[1]', :start, :end)"
        ),
        {"r": run_id, "kind": kind, "start": start, "end": end},
    )


def test_the_three_event_kinds_are_accepted(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        for kind in ("crash", "bubble", "correction"):
            await _market_event(connection, run_id, kind=kind)

    _in_transaction(database_url, write)


def test_an_unknown_event_kind_is_rejected(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await _market_event(connection, run_id, kind="boom")

    with pytest.raises(IntegrityError, match="market_event_kind_check"):
        _in_transaction(database_url, write)


@pytest.mark.parametrize("end", [1000, 999])
def test_an_event_must_end_after_it_starts(database_url: str, end: int) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await _market_event(connection, run_id, start=1000, end=end)

    with pytest.raises(IntegrityError, match="market_event_times_check"):
        _in_transaction(database_url, write)


def test_an_event_belongs_to_an_existing_run(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        await _market_event(connection, -1)

    with pytest.raises(IntegrityError, match="market_event_run_id_fkey"):
        _in_transaction(database_url, write)


def test_active_events_are_indexed_per_run(database_url: str) -> None:
    """The ticker and rehydrate look up `ended_at IS NULL` events of one run."""
    found: list[str] = []

    async def read(connection: AsyncConnection) -> None:
        result = await connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'market_event_active'")
        )
        found.extend(str(row[0]) for row in result)

    _in_transaction(database_url, read)

    assert len(found) == 1
    assert "(run_id)" in found[0]
    assert "ended_at IS NULL" in found[0]


def test_an_order_may_carry_its_actor_and_receipt(database_url: str) -> None:
    """SD20: both are nullable (Phase 2's orders have neither), and stored when given."""

    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        key_id = await _auth_key(connection)
        await _order(connection, run_id, "k-legacy")
        await connection.execute(
            text(
                'INSERT INTO "order" (run_id, idempotency_key, version, wall_ts_ms, '
                "actor_key_id, response) VALUES (:r, 'k-new', 2, 0, :a, '{\"order_id\": 1}')"
            ),
            {"r": run_id, "a": key_id},
        )

    _in_transaction(database_url, write)


def test_an_orders_actor_must_be_an_existing_key(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await connection.execute(
            text(
                'INSERT INTO "order" (run_id, idempotency_key, version, wall_ts_ms, actor_key_id) '
                "VALUES (:r, 'k-1', 1, 0, -1)"
            ),
            {"r": run_id},
        )

    with pytest.raises(IntegrityError, match="order_actor_key_id_fkey"):
        _in_transaction(database_url, write)


def test_a_run_defaults_to_two_grace_versions_and_minute_candles(database_url: str) -> None:
    """SD18, SD25: existing and new runs take the defaults."""
    found: list[tuple[int, int]] = []

    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        result = await connection.execute(
            text("SELECT quote_grace_versions, candle_interval_ms FROM run WHERE run_id = :r"),
            {"r": run_id},
        )
        row = result.one()
        found.append((int(row[0]), int(row[1])))

    _in_transaction(database_url, write)

    assert found == [(2, 60_000)]


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("quote_grace_versions", -1, "run_quote_grace_versions_check"),
        ("candle_interval_ms", 0, "run_candle_interval_ms_check"),
    ],
)
def test_run_grace_and_candle_interval_are_bounded(
    database_url: str, column: str, value: int, constraint: str
) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await connection.execute(
            text(f"UPDATE run SET {column} = :v WHERE run_id = :r"), {"v": value, "r": run_id}
        )

    with pytest.raises(IntegrityError, match=constraint):
        _in_transaction(database_url, write)


def test_zero_grace_versions_is_allowed(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await connection.execute(
            text("UPDATE run SET quote_grace_versions = 0 WHERE run_id = :r"), {"r": run_id}
        )

    _in_transaction(database_url, write)


def test_the_theme_table_has_exactly_pd4s_columns(database_url: str) -> None:
    """SD5 + PD4 (+ Phase 6 SD28/SD29): any further column is a data-model change."""
    columns = {c for t, c, _ in asyncio.run(_columns(database_url)) if t == "theme"}

    assert columns == THEME_COLUMNS


def test_the_theme_row_defaults_to_id_1_and_now(database_url: str) -> None:
    found: list[tuple[int, bool]] = []

    async def write(connection: AsyncConnection) -> None:
        await connection.execute(text("INSERT INTO theme (preset, revision) VALUES ('blauw', 1)"))
        row = (await connection.execute(text("SELECT id, updated_at IS NOT NULL FROM theme"))).one()
        found.append((int(row[0]), bool(row[1])))

    _in_transaction(database_url, write)

    assert found == [(1, True)]


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        ("INSERT INTO theme (id, preset, revision) VALUES (2, 'blauw', 1)", "theme_id_check"),
        ("INSERT INTO theme (preset, revision) VALUES ('eigen', 1)", "theme_preset_check"),
        ("INSERT INTO theme (preset, revision) VALUES ('blauw', 0)", "theme_revision_check"),
    ],
    ids=["second-row", "unknown-preset", "revision-0"],
)
def test_the_theme_row_is_constrained(database_url: str, statement: str, constraint: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        await connection.execute(text(statement))

    with pytest.raises(IntegrityError, match=constraint):
        _in_transaction(database_url, write)


def test_the_five_presets_are_accepted(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        for preset in ("oudgeld", "blauw", "groen", "paars", "rood"):
            await connection.execute(
                text(
                    "INSERT INTO theme (preset, revision) VALUES (:p, 1) "
                    "ON CONFLICT (id) DO UPDATE SET preset = excluded.preset"
                ),
                {"p": preset},
            )

    _in_transaction(database_url, write)


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_a_run_name_is_one_to_a_hundred_characters_after_trim(database_url: str, name: str) -> None:
    """Phase 6 SD2: the name is required."""

    async def write(connection: AsyncConnection) -> None:
        await connection.execute(
            text("INSERT INTO run (name, run_seed, params) VALUES (:n, 1, '{}')"), {"n": name}
        )

    with pytest.raises(IntegrityError, match="run_name_check"):
        _in_transaction(database_url, write)


def test_a_run_needs_a_name(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        await connection.execute(text("INSERT INTO run (run_seed, params) VALUES (1, '{}')"))

    with pytest.raises(IntegrityError, match="name"):
        _in_transaction(database_url, write)


def test_a_custom_theme_needs_its_tokens_and_font(database_url: str) -> None:
    """Phase 6 SD28."""

    async def write(connection: AsyncConnection) -> None:
        await connection.execute(text("INSERT INTO theme (preset, revision) VALUES ('custom', 1)"))

    with pytest.raises(IntegrityError, match="theme_custom_check"):
        _in_transaction(database_url, write)


def test_a_custom_theme_with_tokens_and_font_is_accepted(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        await connection.execute(
            text(
                "INSERT INTO theme (preset, revision, custom_tokens, custom_font) "
                """VALUES ('custom', 1, '{"bg": "#000"}', 'garamond')"""
            )
        )

    _in_transaction(database_url, write)


def test_an_unknown_custom_font_is_rejected(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        await connection.execute(
            text("INSERT INTO theme (preset, revision, custom_font) VALUES ('blauw', 1, 'comic')")
        )

    with pytest.raises(IntegrityError, match="theme_custom_font_check"):
        _in_transaction(database_url, write)


@pytest.mark.parametrize(
    ("content_type", "data", "size", "constraint"),
    [
        ("image/png", b"\x89PNG", 5, "asset_bytes_check"),
        ("image/png", b"", 0, "asset_bytes_check"),
        ("image/svg+xml", b"<svg", 4, "asset_content_type_check"),
    ],
    ids=["bytes-mismatch", "empty", "svg"],
)
def test_an_asset_is_checked_against_its_data(
    database_url: str, content_type: str, data: bytes, size: int, constraint: str
) -> None:
    """Phase 6 SD29: four image types, 1..5 MB, `bytes` is the data's own length."""

    async def write(connection: AsyncConnection) -> None:
        await connection.execute(
            text("INSERT INTO asset (content_type, sha256, data, bytes) VALUES (:t, 'x', :d, :b)"),
            {"t": content_type, "d": data, "b": size},
        )

    with pytest.raises(IntegrityError, match=constraint):
        _in_transaction(database_url, write)


def test_a_theme_slot_points_at_an_existing_asset(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        asset_id: int = (
            await connection.execute(
                text(
                    "INSERT INTO asset (content_type, sha256, data, bytes) "
                    "VALUES ('image/png', 'x', :d, 4) RETURNING asset_id"
                ),
                {"d": b"\x89PNG"},
            )
        ).scalar_one()
        await connection.execute(
            text("INSERT INTO theme (preset, revision, logo_asset_id) VALUES ('blauw', 1, :a)"),
            {"a": asset_id},
        )
        await connection.execute(text("UPDATE theme SET promo_asset_id = :a"), {"a": asset_id + 1})

    with pytest.raises(IntegrityError, match="theme_promo_asset_id_fkey"):
        _in_transaction(database_url, write)


# B-05 (T1): the wallet, its ledger and its settings (plan PD4).


async def _wallet(connection: AsyncConnection, name: str = "Jan") -> int:
    result = await connection.execute(
        text(
            "INSERT INTO wallet (name, name_key, qr_token, short_code, cookie_hash) "
            "VALUES (:name, :key, :token, :code, :hash) RETURNING wallet_id"
        ),
        {
            "name": name,
            "key": name.strip().casefold(),
            "token": f"t-{name}",
            "code": f"C{name}",
            "hash": f"h-{name}",
        },
    )
    return int(result.scalar_one())


async def _entry(
    connection: AsyncConnection,
    wallet_id: int,
    kind: str,
    amount: int,
    *,
    run_id: int | None = None,
    reverses: int | None = None,
    counterpart: int | None = None,
    order_id: int | None = None,
    refunds: int | None = None,
) -> int:
    result = await connection.execute(
        text(
            "INSERT INTO wallet_entry (wallet_id, kind, amount_cents, run_id, "
            "reverses_entry_id, counterpart_entry_id, order_id, refunds_entry_id) "
            "VALUES (:w, :kind, :amount, :run, :rev, :cp, :order, :refunds) RETURNING entry_id"
        ),
        {
            "w": wallet_id,
            "kind": kind,
            "amount": amount,
            "run": run_id,
            "rev": reverses,
            "cp": counterpart,
            "order": order_id,
            "refunds": refunds,
        },
    )
    return int(result.scalar_one())


def test_a_live_and_a_deleted_wallet_are_accepted(database_url: str) -> None:
    """SD15, AC47: alive with all five identifying columns, deleted with none."""

    async def write(connection: AsyncConnection) -> None:
        await _wallet(connection)
        await connection.execute(text("INSERT INTO wallet (deleted_at) VALUES (now())"))

    _in_transaction(database_url, write)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO wallet (name, deleted_at) VALUES ('Jan', now())",
        "INSERT INTO wallet (name, name_key, short_code, cookie_hash) "
        "VALUES ('Jan', 'jan', 'C', 'h')",
        "INSERT INTO wallet (deleted_at, cookie_hash) VALUES (now(), 'h')",
    ],
    ids=["deleted-with-a-name", "live-without-a-token", "deleted-with-a-cookie-hash"],
)
def test_a_wallet_is_either_whole_or_blank(database_url: str, statement: str) -> None:
    """AC47: a deleted row holds no name, token, short code or cookie hash."""

    async def write(connection: AsyncConnection) -> None:
        await connection.execute(text(statement))

    with pytest.raises(IntegrityError, match="wallet_deleted_check"):
        _in_transaction(database_url, write)


@pytest.mark.parametrize("name", ["   ", "x" * 41], ids=["blank", "41-chars"])
def test_a_wallet_name_is_one_to_forty_characters_after_trim(database_url: str, name: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        await _wallet(connection, name)

    with pytest.raises(IntegrityError, match="wallet_name_check"):
        _in_transaction(database_url, write)


@pytest.mark.parametrize("column", ["name_key", "qr_token", "short_code", "cookie_hash"])
def test_two_live_wallets_may_not_share_a_name_or_a_code(database_url: str, column: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        first = await _wallet(connection, "Jan")
        second = await _wallet(connection, "Piet")
        await connection.execute(
            text(
                f"UPDATE wallet SET {column} = (SELECT {column} FROM wallet WHERE wallet_id = :a) "
                "WHERE wallet_id = :b"
            ),
            {"a": first, "b": second},
        )

    with pytest.raises(IntegrityError, match=f"wallet_{column}"):
        _in_transaction(database_url, write)


def test_deleted_wallets_free_their_name_and_codes(database_url: str) -> None:
    """SD3: NULLs are distinct, so many blank rows coexist and a name is reusable."""

    async def write(connection: AsyncConnection) -> None:
        old = await _wallet(connection, "Jan")
        await connection.execute(
            text(
                "UPDATE wallet SET name = NULL, name_key = NULL, qr_token = NULL, "
                "short_code = NULL, cookie_hash = NULL, deleted_at = now() WHERE wallet_id = :w"
            ),
            {"w": old},
        )
        await connection.execute(text("INSERT INTO wallet (deleted_at) VALUES (now())"))
        await _wallet(connection, "Jan")

    _in_transaction(database_url, write)


def test_the_seven_entry_kinds_with_their_signs_are_accepted(database_url: str) -> None:
    """B-06 PD2, PD3: a payment or refund of 0, and a debt closed or moved."""

    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        wallet_id = await _wallet(connection)
        topup = await _entry(connection, wallet_id, "topup", 1500)
        await _entry(connection, wallet_id, "reversal", -1500, reverses=topup)
        out = await _entry(connection, wallet_id, "move_out", -500)
        await _entry(connection, wallet_id, "move_in", 500, counterpart=out)
        await _entry(connection, wallet_id, "closing", -500)
        for amount, key in ((-840, "k-1"), (0, "k-2")):
            order_id = await _order(connection, run_id, key)
            payment = await _entry(connection, wallet_id, "payment", amount, order_id=order_id)
            await _entry(connection, wallet_id, "refund", -amount, refunds=payment)
        await _entry(connection, wallet_id, "closing", 210)
        debt_out = await _entry(connection, wallet_id, "move_out", 210)
        await _entry(connection, wallet_id, "move_in", -210, counterpart=debt_out)

    _in_transaction(database_url, write)


@pytest.mark.parametrize(
    ("kind", "amount"),
    [
        ("topup", -100),
        ("topup", 0),
        ("reversal", 100),
        ("payment", 1),
        ("refund", -1),
        ("move_in", 0),
        ("move_out", 0),
        ("closing", 0),
    ],
)
def test_an_entrys_sign_is_fixed_by_its_kind(database_url: str, kind: str, amount: int) -> None:
    async def write(connection: AsyncConnection) -> None:
        wallet_id = await _wallet(connection)
        topup = await _entry(connection, wallet_id, "topup", 1000)
        payment = await _entry(connection, wallet_id, "payment", -100)
        await _entry(
            connection,
            wallet_id,
            kind,
            amount,
            reverses=topup if kind == "reversal" else None,
            counterpart=topup if kind == "move_in" else None,
            refunds=payment if kind == "refund" else None,
        )

    with pytest.raises(IntegrityError, match="wallet_entry_amount_check"):
        _in_transaction(database_url, write)


def test_an_unknown_entry_kind_is_rejected(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        wallet_id = await _wallet(connection)
        await _entry(connection, wallet_id, "purchase", -100)

    # An unknown kind fails the sign rule too; Postgres names whichever it checks first.
    with pytest.raises(IntegrityError, match=r"wallet_entry_(kind|amount)_check"):
        _in_transaction(database_url, write)


def test_a_reversal_must_name_its_entry_and_only_a_reversal_may(database_url: str) -> None:
    async def bare_reversal(connection: AsyncConnection) -> None:
        wallet_id = await _wallet(connection)
        await _entry(connection, wallet_id, "reversal", -100)

    async def topup_naming_one(connection: AsyncConnection) -> None:
        wallet_id = await _wallet(connection)
        topup = await _entry(connection, wallet_id, "topup", 1000)
        await _entry(connection, wallet_id, "topup", 1000, reverses=topup)

    for body in (bare_reversal, topup_naming_one):
        with pytest.raises(IntegrityError, match="wallet_entry_reversal_check"):
            _in_transaction(database_url, body)


def test_a_move_in_must_name_its_counterpart(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        wallet_id = await _wallet(connection)
        await _entry(connection, wallet_id, "move_in", 100)

    with pytest.raises(IntegrityError, match="wallet_entry_counterpart_check"):
        _in_transaction(database_url, write)


def test_a_topup_is_reversed_at_most_once(database_url: str) -> None:
    """SD12: once per top-up, by a unique constraint."""

    async def write(connection: AsyncConnection) -> None:
        wallet_id = await _wallet(connection)
        topup = await _entry(connection, wallet_id, "topup", 1000)
        await _entry(connection, wallet_id, "reversal", -1000, reverses=topup)
        await _entry(connection, wallet_id, "reversal", -1000, reverses=topup)

    with pytest.raises(IntegrityError, match="wallet_entry_reverses_entry_id_key"):
        _in_transaction(database_url, write)


def test_an_entry_idempotency_key_is_unique(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        wallet_id = await _wallet(connection)
        for _ in range(2):
            await connection.execute(
                text(
                    "INSERT INTO wallet_entry (wallet_id, kind, amount_cents, idempotency_key) "
                    "VALUES (:w, 'topup', 1000, 'k-1')"
                ),
                {"w": wallet_id},
            )

    with pytest.raises(IntegrityError, match="wallet_entry_idempotency_key_key"):
        _in_transaction(database_url, write)


def test_deleting_a_run_keeps_its_wallet_entries_without_a_run(database_url: str) -> None:
    """SD13: `ON DELETE SET NULL`."""
    found: list[tuple[object, ...]] = []

    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await connection.execute(text("DELETE FROM drink WHERE run_id = :r"), {"r": run_id})
        wallet_id = await _wallet(connection)
        entry = await _entry(connection, wallet_id, "topup", 1000, run_id=run_id)
        await connection.execute(text("DELETE FROM run WHERE run_id = :r"), {"r": run_id})
        row = (
            await connection.execute(
                text("SELECT run_id, amount_cents FROM wallet_entry WHERE entry_id = :e"),
                {"e": entry},
            )
        ).one()
        found.append(tuple(row))

    _in_transaction(database_url, write)

    assert found == [(None, 1000)]


# B-06 (T1): payments, refunds, the run's switch and credit limit (plan PD3).


def test_a_refund_must_name_its_payment_and_only_a_refund_may(database_url: str) -> None:
    async def bare_refund(connection: AsyncConnection) -> None:
        wallet_id = await _wallet(connection)
        await _entry(connection, wallet_id, "refund", 100)

    async def topup_naming_one(connection: AsyncConnection) -> None:
        wallet_id = await _wallet(connection)
        payment = await _entry(connection, wallet_id, "payment", -100)
        await _entry(connection, wallet_id, "topup", 1000, refunds=payment)

    for body in (bare_refund, topup_naming_one):
        with pytest.raises(IntegrityError, match="wallet_entry_refund_check"):
            _in_transaction(database_url, body)


def test_a_payment_is_refunded_at_most_once(database_url: str) -> None:
    """SD9: once per payment, by a unique constraint."""

    async def write(connection: AsyncConnection) -> None:
        wallet_id = await _wallet(connection)
        payment = await _entry(connection, wallet_id, "payment", -840)
        await _entry(connection, wallet_id, "refund", 840, refunds=payment)
        await _entry(connection, wallet_id, "refund", 840, refunds=payment)

    with pytest.raises(IntegrityError, match="wallet_entry_refunds_entry_id_key"):
        _in_transaction(database_url, write)


def test_only_a_payment_may_name_an_order(database_url: str) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        order_id = await _order(connection, run_id, "k-1")
        wallet_id = await _wallet(connection)
        await _entry(connection, wallet_id, "topup", 1000, order_id=order_id)

    with pytest.raises(IntegrityError, match="wallet_entry_order_check"):
        _in_transaction(database_url, write)


def test_an_order_is_paid_at_most_once(database_url: str) -> None:
    """AC34: one payment per order, by a unique constraint."""

    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        order_id = await _order(connection, run_id, "k-1")
        wallet_id = await _wallet(connection)
        await _entry(connection, wallet_id, "payment", -260, order_id=order_id)
        await _entry(connection, wallet_id, "payment", -260, order_id=order_id)

    with pytest.raises(IntegrityError, match="wallet_entry_order_id_key"):
        _in_transaction(database_url, write)


def test_a_run_defaults_to_no_wallet_required_and_no_credit(database_url: str) -> None:
    """SD1, SD2: the server default is what existing runs are backfilled with."""
    found: list[tuple[bool, int]] = []

    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        row = (
            await connection.execute(
                text("SELECT wallet_required, credit_limit_cents FROM run WHERE run_id = :r"),
                {"r": run_id},
            )
        ).one()
        found.append((bool(row[0]), int(row[1])))

    _in_transaction(database_url, write)

    assert found == [(False, 0)]


@pytest.mark.parametrize("cents", [0, 50, 5000])
def test_a_credit_limit_on_the_grid_is_accepted(database_url: str, cents: int) -> None:
    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await connection.execute(
            text("UPDATE run SET credit_limit_cents = :c WHERE run_id = :r"),
            {"c": cents, "r": run_id},
        )

    _in_transaction(database_url, write)


@pytest.mark.parametrize("cents", [-50, 5050, 25])
def test_a_credit_limit_off_the_grid_is_rejected(database_url: str, cents: int) -> None:
    """SD2: €0,00 to €50,00 in €0,50 steps."""

    async def write(connection: AsyncConnection) -> None:
        run_id, _ = await _run_and_drink(connection)
        await connection.execute(
            text("UPDATE run SET credit_limit_cents = :c WHERE run_id = :r"),
            {"c": cents, "r": run_id},
        )

    with pytest.raises(IntegrityError, match="run_credit_limit_cents_check"):
        _in_transaction(database_url, write)


def test_deleting_a_run_keeps_its_payments_without_an_order_or_a_run(database_url: str) -> None:
    """SD10, AC24: `ON DELETE SET NULL` on both links; the row and its amount stay."""
    found: list[tuple[object, ...]] = []

    async def write(connection: AsyncConnection) -> None:
        run_id, drink_id = await _run_and_drink(connection)
        order_id = await _order(connection, run_id, "k-1")
        await _line(connection, order_id, drink_id, qty=1, unit=260, total=260)
        wallet_id = await _wallet(connection)
        payment = await _entry(
            connection, wallet_id, "payment", -260, run_id=run_id, order_id=order_id
        )
        await connection.execute(
            text("DELETE FROM order_line WHERE order_id = :o"), {"o": order_id}
        )
        await connection.execute(text('DELETE FROM "order" WHERE order_id = :o'), {"o": order_id})
        await connection.execute(text("DELETE FROM drink WHERE run_id = :r"), {"r": run_id})
        await connection.execute(text("DELETE FROM run WHERE run_id = :r"), {"r": run_id})
        row = (
            await connection.execute(
                text(
                    "SELECT order_id, run_id, amount_cents, wallet_id FROM wallet_entry "
                    "WHERE entry_id = :e"
                ),
                {"e": payment},
            )
        ).one()
        found.append((row[0], row[1], row[2], row[3] == wallet_id))

    _in_transaction(database_url, write)

    assert found == [(None, None, -260, True)]


def test_the_wallet_settings_row_defaults_to_id_1(database_url: str) -> None:
    found: list[int] = []

    async def write(connection: AsyncConnection) -> None:
        await connection.execute(
            text(
                "INSERT INTO wallet_settings (signup_code, unfunded_days, inactive_months) "
                "VALUES (NULL, 1, 1)"
            )
        )
        await connection.execute(
            text(
                "UPDATE wallet_settings SET signup_code = 'ABC', unfunded_days = 365, "
                "inactive_months = 60"
            )
        )
        row = (await connection.execute(text("SELECT id FROM wallet_settings"))).one()
        found.append(int(row[0]))

    _in_transaction(database_url, write)

    assert found == [1]


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ("2, NULL, 30, 12", "wallet_settings_id_check"),
        ("1, NULL, 0, 12", "wallet_settings_unfunded_days_check"),
        ("1, NULL, 366, 12", "wallet_settings_unfunded_days_check"),
        ("1, NULL, 30, 0", "wallet_settings_inactive_months_check"),
        ("1, NULL, 30, 61", "wallet_settings_inactive_months_check"),
        ("1, '   ', 30, 12", "wallet_settings_signup_code_check"),
        ("1, repeat('x', 41), 30, 12", "wallet_settings_signup_code_check"),
    ],
    ids=["second-row", "days-0", "days-366", "months-0", "months-61", "blank-code", "code-41"],
)
def test_the_wallet_settings_are_bounded(database_url: str, values: str, constraint: str) -> None:
    """AC33 (database half)."""

    async def write(connection: AsyncConnection) -> None:
        await connection.execute(
            text(
                "INSERT INTO wallet_settings (id, signup_code, unfunded_days, inactive_months) "
                f"VALUES ({values})"
            )
        )

    with pytest.raises(IntegrityError, match=constraint):
        _in_transaction(database_url, write)
