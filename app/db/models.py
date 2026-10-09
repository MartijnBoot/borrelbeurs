"""The schema as SQLAlchemy 2.0 declarative models, column-for-column with the migrations.

The migrations in `db/migrations/versions/` are the source of truth; these models
mirror them so the repositories have typed tables to query, and
`tests/integration/test_migrations.py` fails if the two ever drift apart.

Every euro amount is an integer number of cents (`*_cents`, AC9, PD3). The only
float columns are the demand coefficients `a`, `d`, `s0`, `c` and an order line's
diagnostic `p_cont`, none of which is money. Revenue is stored once, as
`OrderLine.line_total_cents` (AC11).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One borrel's market. At most one is `live` at a time (SD6)."""

    __tablename__ = "run"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'live', 'ended')", name="run_status_check"),
        CheckConstraint("run_seed >= 0", name="run_run_seed_check"),
        CheckConstraint("quote_grace_versions >= 0", name="run_quote_grace_versions_check"),
        CheckConstraint("candle_interval_ms > 0", name="run_candle_interval_ms_check"),
        CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 100", name="run_name_check"),
        Index(
            "run_one_live",
            text("(true)"),
            unique=True,
            postgresql_where=text("status = 'live'"),
        ),
    )

    run_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))
    run_seed: Mapped[int] = mapped_column(BigInteger)
    tick_interval_ms: Mapped[int] = mapped_column(Integer, server_default=text("1000"))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quote_grace_versions: Mapped[int] = mapped_column(Integer, server_default=text("2"))
    candle_interval_ms: Mapped[int] = mapped_column(Integer, server_default=text("60000"))
    name: Mapped[str] = mapped_column(Text)


class RunConfigRevision(Base):
    """Every configuration a run has had, numbered from 1."""

    __tablename__ = "run_config_revision"
    __table_args__ = (CheckConstraint("revision >= 1", name="run_config_revision_revision_check"),)

    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("run.run_id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    author: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    """A drink's identity across runs and renames, the analytics key (Phase 7 SD1).

    `name_key` is the key the product was created with; it is not unique.
    """

    __tablename__ = "product"

    product_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name_key: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Drink(Base):
    """A drink in a run. Identity is `drink_id`, never `slot` (D-24).

    `slot` is the drink's position in the engine's arrays; `name_key` is
    `name.strip().casefold()`, computed in Python (PD6) because Postgres'
    `lower()` depends on the collation. `product_id` is nullable at the
    database only for a rolled-back image's inserts (Phase 7 SD13); the app
    always sets it.
    """

    __tablename__ = "drink"
    __table_args__ = (
        CheckConstraint("slot >= 0", name="drink_slot_check"),
        CheckConstraint(
            "p_min_cents < p0_cents AND p0_cents < p_max_cents", name="drink_prices_check"
        ),
        CheckConstraint("bar_price_cents >= 0", name="drink_bar_price_cents_check"),
        UniqueConstraint("run_id", "slot", name="drink_run_id_slot_key"),
        Index(
            "drink_name_live",
            "run_id",
            "name_key",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index(
            "drink_product_live",
            "run_id",
            "product_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
    )

    drink_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("run.run_id"))
    slot: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    name_key: Mapped[str] = mapped_column(Text)
    p_min_cents: Mapped[int] = mapped_column(Integer)
    p0_cents: Mapped[int] = mapped_column(Integer)
    p_max_cents: Mapped[int] = mapped_column(Integer)
    a: Mapped[float] = mapped_column(Double)
    d: Mapped[float] = mapped_column(Double)
    s0: Mapped[float] = mapped_column(Double)
    c: Mapped[float] = mapped_column(Double)
    bar_price_cents: Mapped[int] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("product.product_id", name="drink_product_id_fkey")
    )


class EngineState(Base):
    """A live run's `exchange.EngineState`, keyed by `drink_id` (SD8).

    The five per-drink and jump columns are `json`, which keeps the text as
    written, not `jsonb`, which would lose `-0.0` (PD7). `app/db/codec.py`
    writes and reads them.
    """

    __tablename__ = "engine_state"

    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("run.run_id"), primary_key=True)
    y: Mapped[Any] = mapped_column(JSON)
    cum_orders: Mapped[Any] = mapped_column(JSON)
    flow_ema: Mapped[Any] = mapped_column(JSON)
    last_order_ts: Mapped[Any] = mapped_column(JSON)
    jumps: Mapped[Any] = mapped_column(JSON)
    last_idle_ms: Mapped[int] = mapped_column(BigInteger)
    last_bm_ms: Mapped[int] = mapped_column(BigInteger)
    rng_counter: Mapped[int] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(BigInteger)
    tick_index: Mapped[int] = mapped_column(BigInteger)
    t_round: Mapped[int] = mapped_column(BigInteger)
    wall_ts_ms: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceTick(Base):
    """One row per accepted transition: `{drink_id: {"p_cont", "p_q"}}` (SD10)."""

    __tablename__ = "price_tick"
    __table_args__ = (
        CheckConstraint(
            "source IN ('tick', 'order', 'jump', 'idle', 'reset', 'gap', 'config')",
            name="price_tick_source_check",
        ),
    )

    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("run.run_id"), primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    prices: Mapped[dict[str, Any]] = mapped_column(JSONB)
    wall_ts_ms: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    """An accepted order. Its money is in its lines, never here (PD4, AC11).

    `actor_key_id` and `response` (the receipt as returned, Phase 3 SD20) are
    NULL on Phase 2's imported and test orders.
    """

    __tablename__ = "order"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="order_idempotency_key_key"),
        Index("order_run_wall_ts", "run_id", "wall_ts_ms"),
    )

    order_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("run.run_id"))
    idempotency_key: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(BigInteger)
    wall_ts_ms: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_key_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("auth_key.key_id"))
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class OrderLine(Base):
    """One drink in an order, at the price charged, in cents.

    `bar_price_cents` is the drink's bar price when the line sold (Phase 7 SD5,
    D-20); nullable at the database only for a rolled-back image (SD13).
    """

    __tablename__ = "order_line"
    __table_args__ = (
        CheckConstraint("qty > 0", name="order_line_qty_check"),
        CheckConstraint("unit_price_cents >= 0", name="order_line_unit_price_cents_check"),
        CheckConstraint("line_total_cents = qty * unit_price_cents", name="order_line_total_check"),
        CheckConstraint("bar_price_cents >= 0", name="order_line_bar_price_cents_check"),
        UniqueConstraint("order_id", "drink_id", name="order_line_order_id_drink_id_key"),
    )

    order_line_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("order.order_id", ondelete="CASCADE")
    )
    drink_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("drink.drink_id"))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    line_total_cents: Mapped[int] = mapped_column(Integer)
    p_cont: Mapped[float] = mapped_column(Double)
    bar_price_cents: Mapped[int | None] = mapped_column(Integer)


class News(Base):
    """A ticker item. `level` is one of four lowercase values (SD13)."""

    __tablename__ = "news"
    __table_args__ = (
        CheckConstraint(
            "level IN ('info', 'success', 'warning', 'danger')", name="news_level_check"
        ),
    )

    news_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("run.run_id"))
    ts_ms: Mapped[int] = mapped_column(BigInteger)
    level: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthKey(Base):
    """An access key, minted by CLI (Phase 3 SD5). The secret is stored only as
    its argon2id hash (AC6c)."""

    __tablename__ = "auth_key"
    __table_args__ = (
        CheckConstraint("role IN ('display', 'bar', 'admin')", name="auth_key_role_check"),
        CheckConstraint("char_length(label) BETWEEN 1 AND 100", name="auth_key_label_check"),
    )

    key_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    secret_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketEvent(Base):
    """A crash, bubble or correction (Phase 3 SD23). Active while `ended_at` is NULL."""

    __tablename__ = "market_event"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('crash', 'bubble', 'correction')", name="market_event_kind_check"
        ),
        CheckConstraint("t_end_ms > t_start_ms", name="market_event_times_check"),
        Index("market_event_active", "run_id", postgresql_where=text("ended_at IS NULL")),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("run.run_id"))
    kind: Mapped[str] = mapped_column(Text)
    drink_ids: Mapped[list[int]] = mapped_column(JSONB)
    t_start_ms: Mapped[int] = mapped_column(BigInteger)
    t_end_ms: Mapped[int] = mapped_column(BigInteger)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Asset(Base):
    """An uploaded image (Phase 6 SD29), at most 5 MB, served at `/assets/{asset_id}`."""

    __tablename__ = "asset"
    __table_args__ = (
        CheckConstraint(
            "content_type IN ('image/png', 'image/jpeg', 'image/webp', 'image/gif')",
            name="asset_content_type_check",
        ),
        CheckConstraint(
            "bytes BETWEEN 1 AND 5242880 AND bytes = octet_length(data)",
            name="asset_bytes_check",
        ),
    )

    asset_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    content_type: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Export(Base):
    """A run's xlsx export, built by the worker into `data` (Phase 7 SD6).

    `total_cents` and `line_count` describe the file's contents, checked against
    the run when it is built; revenue itself stays in `order_line`.
    """

    __tablename__ = "export"
    __table_args__ = (
        CheckConstraint("kind IN ('manual', 'final')", name="export_kind_check"),
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name="export_status_check"
        ),
        CheckConstraint("data IS NULL OR bytes = octet_length(data)", name="export_bytes_check"),
        CheckConstraint("status <> 'done' OR data IS NOT NULL", name="export_done_check"),
    )

    export_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("run.run_id", name="export_run_id_fkey")
    )
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(Text)
    # `nullable` is explicit: the `bytes` column below shadows the builtin in this
    # class body, so the annotation alone does not tell SQLAlchemy it is optional.
    data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    sha256: Mapped[str | None] = mapped_column(Text)
    bytes: Mapped[int | None] = mapped_column(Integer)
    line_count: Mapped[int | None] = mapped_column(Integer)
    total_cents: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Theme(Base):
    """The one active display theme (Phase 4 SD5). A single row, `id = 1` (PD4);
    no row means Blauw at revision 0. Phase 6 adds the custom tokens and font
    (SD28) and one image pointer per slot (SD29)."""

    __tablename__ = "theme"
    __table_args__ = (
        CheckConstraint("id = 1", name="theme_id_check"),
        CheckConstraint(
            "preset IN ('oudgeld', 'blauw', 'groen', 'paars', 'rood', 'custom')",
            name="theme_preset_check",
        ),
        CheckConstraint("revision >= 1", name="theme_revision_check"),
        CheckConstraint("custom_font IN ('inter', 'garamond')", name="theme_custom_font_check"),
        CheckConstraint(
            "preset <> 'custom' OR (custom_tokens IS NOT NULL AND custom_font IS NOT NULL)",
            name="theme_custom_check",
        ),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=False, server_default=text("1")
    )
    preset: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    custom_tokens: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    custom_font: Mapped[str | None] = mapped_column(Text)
    bg_asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("asset.asset_id", name="theme_bg_asset_id_fkey")
    )
    header_asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("asset.asset_id", name="theme_header_asset_id_fkey")
    )
    logo_asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("asset.asset_id", name="theme_logo_asset_id_fkey")
    )
    promo_asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("asset.asset_id", name="theme_promo_asset_id_fkey")
    )
