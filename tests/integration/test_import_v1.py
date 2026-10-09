"""The v1 import CLI (T13).

AC19, AC20; AC10, AC15, AC16 end to end; SD5, SD6, SD15.

`main` reads its database from the environment through `get_settings()`, as
it does in production, so each test points `DATABASE_URL` at the scratch
database and clears the settings cache on both sides.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.cli.import_v1 import main
from app.core.config import Settings, get_settings
from app.db.mapping import params_to_json, spec_from_rows
from app.db.models import Base
from app.db.news import list_news
from app.db.runs import active_drinks
from app.db.session import create_engine
from exchange import MarketSpec, Params
from tests.engine.golden.replay import spec_from_config

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_CONFIG_PATH = REPO_ROOT / "legacy" / "v1" / "config" / "exchange_config.json"
LIVE_NEWS_PATH = REPO_ROOT / "legacy" / "v1" / "static" / "news.json"
TABLES = tuple(table.name for table in Base.metadata.sorted_tables)
ARRAYS = ("p_min", "p_max", "p0", "a", "d", "s0", "c")


@pytest.fixture
def scratch(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Iterator[str]:
    """`main`'s environment, pointed at the per-test scratch database."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield database_url
    get_settings.cache_clear()


def _live() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(LIVE_CONFIG_PATH.read_text(encoding="utf-8"))
    return data


def _write(path: Path, data: Any) -> Path:
    path.write_bytes(json.dumps(data).encode("utf-8"))
    return path


def _engine(settings: Settings, url: str) -> AsyncEngine:
    return create_engine(settings.model_copy(update={"database_url": url}))


def _query(settings: Settings, url: str, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    async def run() -> list[tuple[Any, ...]]:
        engine = _engine(settings, url)
        try:
            async with engine.connect() as conn:
                return [tuple(row) for row in await conn.execute(text(sql), params)]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _counts(settings: Settings, url: str) -> dict[str, int]:
    sql = " UNION ALL ".join(f"SELECT '{t}', count(*) FROM \"{t}\"" for t in TABLES)
    return {name: int(count) for name, count in _query(settings, url, sql)}


def _run_rows(settings: Settings, url: str, run_id: int) -> list[tuple[Any, ...]]:
    """Every row belonging to `run_id`, in every table it reaches, as JSON text."""
    return _query(
        settings,
        url,
        "SELECT 'run', row_to_json(t)::text FROM run t WHERE run_id = :r"
        " UNION ALL SELECT 'drink', row_to_json(t)::text FROM drink t WHERE run_id = :r"
        " UNION ALL SELECT 'news', row_to_json(t)::text FROM news t WHERE run_id = :r"
        " UNION ALL SELECT 'rev', row_to_json(t)::text FROM run_config_revision t"
        " WHERE run_id = :r ORDER BY 1, 2",
        r=run_id,
    )


def _imported_run(capsys: pytest.CaptureFixture[str], *argv: str) -> int:
    assert main(list(argv)) == 0
    return int(capsys.readouterr().out.strip())


def _drinks_and_news(settings: Settings, url: str, run_id: int) -> tuple[Any, Any, Any]:
    async def run() -> tuple[Any, Any, Any]:
        engine = _engine(settings, url)
        try:
            async with engine.connect() as conn:
                drinks = await active_drinks(conn, run_id)
                news = await list_news(conn, run_id)
                params: dict[str, Any] = (
                    await conn.execute(
                        text("SELECT params FROM run WHERE run_id = :r"), {"r": run_id}
                    )
                ).scalar_one()
            return drinks, news, params
        finally:
            await engine.dispose()

    return asyncio.run(run())


def assert_specs_equal(left: MarketSpec, right: MarketSpec) -> None:
    """`MarketSpec` is `eq=False`; compare it field by field, bitwise."""
    assert left.names == right.names
    for key in ARRAYS:
        a, b = getattr(left, key), getattr(right, key)
        assert a.dtype == b.dtype == np.float64, key
        assert a.view(np.uint64).tobytes() == b.view(np.uint64).tobytes(), key
    assert left.params == right.params


def test_the_real_v1_files_import_as_one_draft_run(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC19."""
    live = _live()

    run_id = _imported_run(capsys, "--config", str(LIVE_CONFIG_PATH), "--news", str(LIVE_NEWS_PATH))

    # Phase 6 SD2: the run is named after the config file's stem.
    assert _query(settings, scratch, "SELECT run_id, status, name FROM run") == [
        (run_id, "draft", LIVE_CONFIG_PATH.stem)
    ]
    drinks, news, stored_params = _drinks_and_news(settings, scratch, run_id)
    assert [d.name for d in drinks] == live["names"]
    assert [d.slot for d in drinks] == list(range(len(live["names"])))
    for key in ("p_min", "p0", "p_max"):
        assert [getattr(d, f"{key}_cents") for d in drinks] == [
            round(euros * 100) for euros in live[key]
        ], key
    for key in ("a", "d", "s0", "c"):
        assert [getattr(d, key) for d in drinks] == live[key], key
    # The live file has no bar_price key and the repo no sidecar: every bar price is p0.
    assert [d.bar_price_cents for d in drinks] == [d.p0_cents for d in drinks]
    assert news == ()
    params = Params.from_dict(live["params"])
    assert Params.from_dict(stored_params) == params

    [(revision, config, author)] = _query(
        settings,
        scratch,
        "SELECT revision, config, author FROM run_config_revision WHERE run_id = :r",
        r=run_id,
    )
    assert (revision, author) == (1, "import_v1")
    assert config["params"] == params_to_json(params)
    assert [d["name"] for d in config["drinks"]] == live["names"]
    assert [d["bar_price_cents"] for d in config["drinks"]] == [d.p0_cents for d in drinks]

    spec, _ = spec_from_rows(drinks, Params.from_dict(stored_params))
    assert_specs_equal(spec, spec_from_config(live))
    # Draft only: the import never goes live (SD6).
    assert _counts(settings, scratch)["engine_state"] == 0


def test_bar_price_precedence_and_news_levels_hold_end_to_end(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    config = {**_live(), "bar_price": {"Bier": 3.1, "Wijn": 5.0}}
    config_path = _write(tmp_path / "exchange_config.json", config)
    sidecar_path = _write(tmp_path / "bar_prices.json", {"Bier": 2.0})
    news_path = _write(
        tmp_path / "news.json",
        [
            {"id": "a", "ts_ms": 200, "level": "Danger", "text": "Op!"},
            {"id": "b", "ts_ms": 100, "level": "INFO", "text": "Open"},
        ],
    )

    run_id = _imported_run(
        capsys,
        "--config",
        str(config_path),
        "--news",
        str(news_path),
        "--bar-prices",
        str(sidecar_path),
    )

    drinks, news, _ = _drinks_and_news(settings, scratch, run_id)
    # Bier: sidecar over the config's key; Wijn: the config's key over p0; the rest p0.
    assert [d.bar_price_cents for d in drinks] == [200, 500, 600, 150, 360, 970]
    assert [(n.ts_ms, n.level, n.text) for n in news] == [
        (100, "info", "Open"),
        (200, "danger", "Op!"),
    ]


def test_two_imports_make_two_independent_draft_runs(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """AC20: the second import leaves the first run's rows byte-identical."""
    news_path = _write(
        tmp_path / "news.json", [{"id": "a", "ts_ms": 1, "level": "info", "text": "x"}]
    )
    argv = ("--config", str(LIVE_CONFIG_PATH), "--news", str(news_path))

    first = _imported_run(capsys, *argv)
    before = _run_rows(settings, scratch, first)
    second = _imported_run(capsys, *argv)

    assert first != second
    assert _run_rows(settings, scratch, first) == before
    assert _query(settings, scratch, "SELECT run_id, status FROM run ORDER BY run_id") == [
        (first, "draft"),
        (second, "draft"),
    ]
    assert _counts(settings, scratch)["drink"] == 2 * len(_live()["names"])


def _inexact_cent(tmp_path: Path) -> list[str]:
    live = _live()
    live["p0"][0] = 2.605
    return ["--config", str(_write(tmp_path / "config.json", live))]


def _duplicate_name(tmp_path: Path) -> list[str]:
    live = _live()
    live["names"][1] = " bier"
    return ["--config", str(_write(tmp_path / "config.json", live))]


def _unknown_level(tmp_path: Path) -> list[str]:
    news = [{"id": "a", "ts_ms": 1, "level": "notice", "text": "x"}]
    return [
        "--config",
        str(LIVE_CONFIG_PATH),
        "--news",
        str(_write(tmp_path / "news.json", news)),
    ]


@pytest.mark.parametrize(
    "make_argv",
    [
        pytest.param(_inexact_cent, id="inexact-cent"),
        pytest.param(_duplicate_name, id="duplicate-name"),
        pytest.param(_unknown_level, id="unknown-level"),
    ],
)
def test_bad_input_exits_2_and_writes_nothing(
    scratch: str,
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    make_argv: Any,
) -> None:
    _imported_run(capsys, "--config", str(LIVE_CONFIG_PATH))
    before = _counts(settings, scratch)

    assert main(make_argv(tmp_path)) == 2

    assert "invalid input" in capsys.readouterr().err
    assert _counts(settings, scratch) == before


def test_a_database_failure_after_the_drinks_exits_1_and_writes_nothing(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _imported_run(capsys, "--config", str(LIVE_CONFIG_PATH))
    before = _counts(settings, scratch)
    news_path = _write(
        tmp_path / "news.json", [{"id": "a", "ts_ms": 1, "level": "info", "text": "x"}]
    )
    drinks_inserted = 0

    def fail_after_drinks(*args: Any) -> None:
        nonlocal drinks_inserted
        statement: str = args[2]
        if statement.startswith("INSERT INTO drink"):
            drinks_inserted += 1
        elif statement.startswith("INSERT INTO news"):
            raise OperationalError(statement, {}, Exception("injected"))

    event.listen(Engine, "before_cursor_execute", fail_after_drinks)
    try:
        status = main(["--config", str(LIVE_CONFIG_PATH), "--news", str(news_path)])
    finally:
        event.remove(Engine, "before_cursor_execute", fail_after_drinks)

    assert status == 1
    assert drinks_inserted == len(_live()["names"])
    assert "database error" in capsys.readouterr().err
    assert _counts(settings, scratch) == before


def test_an_import_gives_every_drink_a_product(
    scratch: str, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """Phase 7 SD1, AC10: the import adds through `add_drink`, which resolves products."""
    run_id = _imported_run(capsys, "--config", str(LIVE_CONFIG_PATH))

    rows = _query(
        settings,
        scratch,
        "SELECT drink.name, product.name FROM drink "
        "LEFT JOIN product USING (product_id) WHERE run_id = :r ORDER BY slot",
        r=run_id,
    )
    assert [drink for drink, _ in rows] == _live()["names"]
    assert [product for _, product in rows] == [drink for drink, _ in rows]
