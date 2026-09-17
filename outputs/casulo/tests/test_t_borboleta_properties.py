from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

try:
    from hypothesis import given, settings, strategies as st
except ImportError as exc:
    raise unittest.SkipTest("Hypothesis não instalado; use o extra dev") from exc

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from casulo.t import ArtifactBuilder
from casulo.t.runner import load_artifact


PROPERTY_TEMPORARY = tempfile.TemporaryDirectory()
ARTIFACT = ArtifactBuilder().build(
    ROOT / "examples" / "t" / "balanco_hidrico.t",
    Path(PROPERTY_TEMPORARY.name) / "property-artifact",
).output_dir


@settings(max_examples=40, deadline=None)
@given(
    precipitation=st.floats(
        min_value=0,
        max_value=1_000_000,
        allow_nan=False,
        allow_infinity=False,
    ),
    evapotranspiration=st.floats(
        min_value=0,
        max_value=1_000,
        allow_nan=False,
        allow_infinity=False,
    ),
    surface_flow=st.floats(
        min_value=0,
        max_value=1_000_000,
        allow_nan=False,
        allow_infinity=False,
    ),
    base_flow=st.floats(
        min_value=0,
        max_value=1_000_000,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_scalar_and_fused_batch_are_semantically_equivalent(
    precipitation: float,
    evapotranspiration: float,
    surface_flow: float,
    base_flow: float,
) -> None:
    payload = {
        "precipitation": precipitation,
        "evapotranspiration": evapotranspiration,
        "surface_flow": surface_flow,
        "base_flow": base_flow,
    }
    loaded = load_artifact(ARTIFACT)
    scalar = loaded.namespace["execute"](
        "WaterBalance",
        payload,
        use_cache=False,
    )
    batch = loaded.namespace["execute_batch"](
        "WaterBalance",
        [payload],
        use_cache=False,
    )["items"][0]
    assert scalar == batch
