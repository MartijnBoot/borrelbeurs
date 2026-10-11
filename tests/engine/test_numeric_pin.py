"""The golden numbers rest on one numeric environment (fix/golden-linux-pin).

numpy picks its SIMD kernels by CPU, and the kernels round differently in the last digit, so
fixtures captured on one CPU fail on another. `tests/engine/golden/__init__.py` pins the
dispatch to the baseline kernels before numpy loads; this is the check that it took effect.
"""

from __future__ import annotations

import importlib
import platform

import pytest

from tests.engine.golden import PINNED_CPU_FEATURES


@pytest.mark.skipif(
    platform.machine().lower() not in {"x86_64", "amd64"}, reason="the pin is x86 only"
)
def test_numpys_simd_dispatch_is_pinned_to_the_baseline() -> None:
    cpu_features = importlib.import_module("numpy.core._multiarray_umath").__cpu_features__
    enabled = [name for name in PINNED_CPU_FEATURES if cpu_features.get(name)]
    assert not enabled, (
        f"numpy still dispatches {enabled}: it was imported before the pin was set, so the "
        "golden numbers depend on this CPU"
    )
