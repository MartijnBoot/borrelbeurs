"""`DEFAULT_PARAMS`: a new run with no earlier run starts from v1's saved settings.

v1's saved settings are the `params` of v1's `config/exchange_config.json`,
not v1's engine defaults (`Params()`, pinned to v1's engine by
`tests/engine/test_spec.py`), read from the copy in `tests/fixtures/v1/`.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.db.runs import DEFAULT_PARAMS
from exchange import Params

REPO_ROOT = Path(__file__).resolve().parents[2]
V1_CONFIG_PATH = REPO_ROOT / "tests" / "fixtures" / "v1" / "config" / "exchange_config.json"


def test_default_params_are_v1s_saved_settings() -> None:
    saved = json.loads(V1_CONFIG_PATH.read_text(encoding="utf-8"))["params"]
    assert Params.from_dict(saved) == DEFAULT_PARAMS


def test_default_params_differ_from_the_engine_defaults() -> None:
    assert Params() != DEFAULT_PARAMS
