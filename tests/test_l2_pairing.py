"""L2 unit and real-data pairing tests.

These tests use the frozen L1 artefacts produced by ``scripts/02`` and
``scripts/03``.  They fail if the measured pair counts or delay definitions
drift.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pyroharmonize import config
from pyroharmonize.l2 import (
    DELAY_BIN_LABELS,
    REFERENCE_LST_H,
    delay_bin,
    local_solar_time,
    pixel_flags,
    region_weights,
)

PAIRS_PATH = config.PROCESSED_DIR / "pairs_aqua_snpp.parquet"
TERRA_PATH = config.PROCESSED_DIR / "pairs_terra_snpp.parquet"
NOAA20_PATH = config.PROCESSED_DIR / "pairs_noaa20_snpp.parquet"


@pytest.fixture(scope="module")
def pairs() -> pd.DataFrame:
    if not PAIRS_PATH.is_file():
        pytest.fail(f"missing {PAIRS_PATH}; run scripts\\03_run_analysis.py --force")
    return pd.read_parquet(PAIRS_PATH)


def test_local_solar_time_uses_zero_padded_hhmm() -> None:
    # 118 must mean 01:18 UTC, not 11:08.
    times = pd.Series(["0118", "1300", "0000"])
    longitudes = pd.Series([0.0, 15.0, 180.0])
    result = local_solar_time(times, longitudes)
    assert result.iloc[0] == pytest.approx(1.3)
    assert result.iloc[1] == pytest.approx(14.0)
    assert result.iloc[2] == pytest.approx(12.0)


def test_local_solar_time_wraps_midnight() -> None:
    assert local_solar_time(pd.Series(["2300"]), pd.Series([30.0])).iloc[0] == pytest.approx(1.0)


def test_pixel_flags_count_each_rule() -> None:
    flags = pixel_flags(
        pd.Series(["0", "2", "0", "0"]),
        pd.Series([10.0, 5.0, 0.0, -1.0]),
        pd.Series(["D", "D", "D", "N"]),
    )
    assert flags.tolist() == [0, 1, 2, 6]
    assert int((flags != 0).sum()) == 3


def test_delay_bins_are_pre_registered() -> None:
    delays = pd.Series([-0.5, 0.0, 0.1, 0.5, 1.2, 1.9, 2.5, 3.6])
    bins = delay_bin(delays)
    assert bins.iloc[0] == "(-3, 0]"
    assert bins.iloc[1] == "(-3, 0]"
    assert bins.iloc[2] == "(0, 0.5]"
    assert bins.iloc[3] == "(0, 0.5]"
    assert bins.iloc[4] == "(1, 1.5]"
    assert bins.iloc[5] == "(1.5, 2]"
    assert bins.iloc[6] == "(2, 3.5]"
    assert pd.isna(bins.iloc[7])


def test_region_weights_are_capped() -> None:
    regions = pd.Series(["A"] * 10 + ["B"] * 30)
    weights = region_weights(pd.Series(np.zeros(40)), regions)
    assert weights.iloc[0] == pytest.approx(2.0)
    assert weights.iloc[20] == pytest.approx(2.0 / 3.0)


def test_measured_pair_counts(pairs: pd.DataFrame) -> None:
    assert len(pairs) == 6313
    assert pairs["region"].value_counts().to_dict() == {
        "Southern_Africa": 3971,
        "Amazon": 1798,
        "Australia": 427,
        "California": 117,
    }
    assert pd.read_parquet(TERRA_PATH).shape[0] == 3847
    assert pd.read_parquet(NOAA20_PATH).shape[0] == 9822


def test_pair_key_is_unique(pairs: pd.DataFrame) -> None:
    key = ["region", "sample_window_start", "acquisition_date", "cell_lat", "cell_lon"]
    assert not pairs.duplicated(key).any()


def test_delay_definitions_are_consistent(pairs: pd.DataFrame) -> None:
    expected = pairs["lst_aqua"] - REFERENCE_LST_H
    assert np.allclose(pairs["delay_ref"], expected)
    expected_pair = pairs["lst_aqua"] - pairs["lst_snpp"]
    assert np.allclose(pairs["delay_pair"], expected_pair)
    assert set(pairs["delay_bin"] if "delay_bin" in pairs else delay_bin(pairs["delay_ref"]).dropna()) <= set(DELAY_BIN_LABELS)
