"""The 41 explanations, pinned to their tables (B-01 T3: SD3; AC7-AC9, AC12, AC13; PD1, PD2).

The spec is the fixture: its "The table" is parsed here, and the two JSON files
the web renders must hold exactly its names and paragraphs. A word changed in
either place alone fails, so a change to a text is a change to the spec (SD3).

B-03 (T3: SD10, SD11; AC14, AC16; PD2) adds E34-E39 from its own table, and
amends E9 by one substitution applied here to B-01's row, which stays the
record of what B-01 shipped.

B-06 (T17: SD3; AC3; PD17) adds E40-E41, "Wallet verplicht" and "Rood staan tot".
Its spec gives no text; the owner approved the wording in the B-06 plan's own
"The table" at the audit, so that plan is the source here.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import TypedDict, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "docs" / "specs" / "phase-b-01-settings-explained.md"
B03_SPEC = REPO_ROOT / "docs" / "specs" / "phase-b-03-brownian-settings.md"
B06_PLAN = REPO_ROOT / "docs" / "plans" / "phase-b-06-wallet-payments.md"
SETTINGS_JSON = REPO_ROOT / "web" / "src" / "features" / "settings" / "explanations.json"
MANIPULATION_JSON = REPO_ROOT / "web" / "src" / "features" / "manipulation" / "explanations.json"

SETTINGS_IDS = {f"E{n}" for n in (*range(1, 21), *range(33, 42))}
MANIPULATION_IDS = {f"E{n}" for n in range(21, 33)}

_ROW = re.compile(r"^\*\*(E\d+) — ")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_FIELD = re.compile(r"^\*\*E\d+ — `(\w+)`")


class Row:
    def __init__(self, field: str | None, name: str, paragraphs: list[str]) -> None:
        self.field = field
        self.name = name
        self.paragraphs = paragraphs

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Row) and (self.name, self.paragraphs) == (
            other.name,
            other.paragraphs,
        )

    def __repr__(self) -> str:
        return f"Row({self.name!r}, {self.paragraphs!r})"


def parse_spec_table(text: str) -> dict[str, Row]:
    """`## The table`: per `**E<n> — …**` line, its last bold run and the `> ` lines under it.

    The field is the backticked name on the row line, when there is one (E1-E26).
    `Bron:` lines and prose between rows are ignored.
    """
    section = text[text.index("\n## The table\n") :]
    end = section.find("\n## ", 1)
    lines = section[: end if end != -1 else None].splitlines()
    rows: dict[str, Row] = {}
    i = 0
    while i < len(lines):
        match = _ROW.match(lines[i])
        if match is None:
            i += 1
            continue
        row_id = match.group(1)
        assert row_id not in rows, f"{row_id} appears twice"
        name = _BOLD.findall(lines[i])[-1]
        field = _FIELD.match(lines[i])
        i += 1
        while i < len(lines) and lines[i] == "":
            i += 1
        paragraphs = []
        while i < len(lines) and lines[i].startswith("> "):
            paragraphs.append(lines[i][2:])
            i += 1
        assert paragraphs, f"{row_id} has no explanation"
        rows[row_id] = Row(field.group(1) if field else None, name, paragraphs)
    return rows


class Entry(TypedDict):
    id: str
    name: str
    paragraphs: list[str]


def _load(path: Path) -> dict[str, Entry]:
    return cast(dict[str, Entry], json.loads(path.read_text(encoding="utf-8")))


# B-03 SD11: E9 names the noise's clock, which is now a control of its own.
E9_OLD = "en de ruis loopt op een eigen klok."
E9_NEW = "en de ruis loopt op een eigen klok (Ritme ruis)."


def _amended(rows: dict[str, Row]) -> dict[str, Row]:
    """B-01's rows as they ship after B-03: E9's first paragraph with SD11's substitution."""
    e9 = rows["E9"]
    first, *rest = e9.paragraphs
    return {**rows, "E9": Row(e9.field, e9.name, [first.replace(E9_OLD, E9_NEW), *rest])}


SPEC_ROWS = parse_spec_table(SPEC.read_text(encoding="utf-8"))
B03_TEXT = B03_SPEC.read_text(encoding="utf-8")
B03_ROWS = parse_spec_table(B03_TEXT)
B06_ROWS = parse_spec_table(B06_PLAN.read_text(encoding="utf-8"))
EXPECTED_ROWS = {**_amended(SPEC_ROWS), **B03_ROWS, **B06_ROWS}
SETTINGS = _load(SETTINGS_JSON)
MANIPULATION = _load(MANIPULATION_JSON)


def _by_id() -> dict[str, tuple[str, Entry]]:
    entries = [*SETTINGS.items(), *MANIPULATION.items()]
    return {entry["id"]: (key, entry) for key, entry in entries}


def test_the_spec_table_has_e1_to_e33() -> None:
    assert list(SPEC_ROWS) == [f"E{n}" for n in range(1, 34)]


def test_the_b03_table_has_e34_to_e39_each_a_field_row() -> None:
    """B-03 SD10: one row per noise param, keyed by its field (PD3)."""
    assert list(B03_ROWS) == [f"E{n}" for n in range(34, 40)]
    assert [row.field for row in B03_ROWS.values()] == [
        "bm_enabled",
        "bm_sigma_y",
        "bm_dt_minutes",
        "flow_vol_amp",
        "flow_beta",
        "y_clip",
    ]


def test_the_b06_table_has_e40_and_e41_each_a_field_row() -> None:
    """B-06 PD17: one row per run column, keyed by its field."""
    assert list(B06_ROWS) == ["E40", "E41"]
    assert [row.field for row in B06_ROWS.values()] == ["wallet_required", "credit_limit_cents"]
    assert [row.name for row in B06_ROWS.values()] == ["Wallet verplicht", "Rood staan tot (€)"]


def test_e9_s_amendment_applies_once_and_b03_states_it() -> None:
    """B-03 SD11, AC16: a later edit to B-01's E9 sentence must fail here, not pass silently."""
    assert SPEC_ROWS["E9"].paragraphs[0].count(E9_OLD) == 1, "B-03 SD11 no longer applies"
    assert "eigen klok (Ritme ruis)." in B03_TEXT
    assert EXPECTED_ROWS["E9"] != SPEC_ROWS["E9"]
    assert EXPECTED_ROWS["E9"].paragraphs[1:] == SPEC_ROWS["E9"].paragraphs[1:]


def test_each_feature_holds_its_own_rows() -> None:
    """PD2: settings holds E1-E20, E33, B-03's E34-E39 and B-06's E40-E41; manipulation
    E21-E32."""
    assert {entry["id"] for entry in SETTINGS.values()} == SETTINGS_IDS
    assert {entry["id"] for entry in MANIPULATION.values()} == MANIPULATION_IDS
    assert len(SETTINGS) == len(SETTINGS_IDS)
    assert len(MANIPULATION) == len(MANIPULATION_IDS)


def test_every_name_and_paragraph_is_the_spec_s_exactly() -> None:
    """AC7, SD3: character for character, one paragraph per `> ` line (B-03 AC14, AC16)."""
    by_id = _by_id()
    assert set(by_id) == set(EXPECTED_ROWS)
    for row_id, row in EXPECTED_ROWS.items():
        _, entry = by_id[row_id]
        assert set(entry) == {"id", "name", "paragraphs"}, row_id
        assert Row(None, entry["name"], entry["paragraphs"]) == row, row_id


def test_a_field_row_is_keyed_by_its_field() -> None:
    """PD1: the key is the field the spec names, so each field has one entry (AC9)."""
    by_id = _by_id()
    for row_id, row in EXPECTED_ROWS.items():
        if row.field is not None:
            assert by_id[row_id][0] == row.field, row_id


def test_the_other_rows_have_the_plan_s_keys() -> None:
    by_id = _by_id()
    keys = {row_id: by_id[row_id][0] for row_id, row in EXPECTED_ROWS.items() if row.field is None}
    assert keys == {
        "E27": "event_duration_s",
        "E28": "crash",
        "E29": "correction",
        "E30": "bubble",
        "E31": "jump_target",
        "E32": "jump_duration_s",
        "E33": "anchor_s0",
    }


def test_no_name_contains_an_emoji() -> None:
    """AC8: no character of Unicode category So (symbols such as emoji) in a new name."""
    for row_id, (_, entry) in _by_id().items():
        name = entry["name"]
        assert [c for c in name if unicodedata.category(c) == "So"] == [], row_id
        assert "️" not in name, row_id


def test_the_refresh_explanation_says_it_is_not_the_update_rate() -> None:
    """AC12 (D-22)."""
    entry = SETTINGS["refresh_minutes"]
    assert entry["name"] == "Ritme stille drankjes (min)"
    assert any("Dit is niet hoe vaak de prijzen verversen" in p for p in entry["paragraphs"])


def test_the_auto_calibrate_explanation_says_live_zetten_only() -> None:
    """AC13 (D-21): no init, no reset; it acts at Live zetten only."""
    entry = SETTINGS["auto_calibrate_s0"]
    text = " ".join([entry["name"], *entry["paragraphs"]])
    assert "init" not in text
    assert "reset" not in text
    assert "alleen bij Live zetten" in text


def test_the_anchor_explanation_says_current_prices() -> None:
    """AC13 (D-21): the anchor uses the current prices, not p0."""
    assert any("huidige koers" in p for p in SETTINGS["anchor_s0"]["paragraphs"])


_SAMPLE = """# Spec

## The table

Intro, ignored.

**E1 — `step_quant`.** Was "🧱 Tickgrootte". **Prijsstap (€)**

> Eerste regel.
> Eerste borrel: 0,10.

Bron: `exchange/pricing.py:32-42`.

**E2 — the jump target.** Was "Doelprijs (€)". **Doelprijs (€)** (unchanged)

> Alleen een regel.

## In scope

**E3 — `x`.** **Not in the table**

> Ignored.
"""


def test_the_parser_reads_a_small_table() -> None:
    rows = parse_spec_table(_SAMPLE)
    assert list(rows) == ["E1", "E2"]
    assert rows["E1"].field == "step_quant"
    assert rows["E1"] == Row(None, "Prijsstap (€)", ["Eerste regel.", "Eerste borrel: 0,10."])
    assert rows["E2"].field is None
    assert rows["E2"] == Row(None, "Doelprijs (€)", ["Alleen een regel."])


def test_a_changed_word_does_not_compare_equal() -> None:
    changed = parse_spec_table(_SAMPLE.replace("Eerste regel.", "Eerste zin."))
    assert changed["E1"] != parse_spec_table(_SAMPLE)["E1"]
