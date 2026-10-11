"""Golden fixtures: v1's price series, captured before `exchange/` was rewritten (Phase 1 T1).

**The numeric pin.** numpy picks its SIMD kernels by CPU, and the kernels round differently in
the last digit, so fixtures captured on one CPU fail on another (CI's runner vs a laptop). The
dispatch is pinned to the baseline kernels here, before anything imports numpy: this package
is imported first by the capture CLI, and `tests/conftest.py` imports it first for pytest.
The fixtures are captured, and replayed, on Linux under this pin (`scripts/golden_linux.sh`):
the C maths library differs on Windows, so the numbers do not carry over.
"""

import os
import platform

PINNED_CPU_FEATURES = ("AVX2", "FMA3", "AVX512F", "AVX512_SKX")

# numpy warns about feature names its build does not know, so only x86 gets the pin.
if platform.machine().lower() in {"x86_64", "amd64"}:
    os.environ["NPY_DISABLE_CPU_FEATURES"] = " ".join(PINNED_CPU_FEATURES)
