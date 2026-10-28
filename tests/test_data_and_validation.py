"""Tests for data provenance, point-in-time shareholding inputs and run-time validation."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from index_engine.attribution import brinson_fachler
from index_engine.config import load_config
from index_engine.data import (BACKFILLED, CURRENT, PIT, MarketData, load_shareholding,
                               make_synthetic, restate_to_current_basis)
from index_engine.engine import run_backtest
from index_engine.pipeline import parent_universe
from index_engine.validation import provenance, run_checks

CFG_PATH = Path(__file__).resolve().parents[1] / "config" / "india_large_cap_40.yaml"


@pytest.fixture(scope="module")
def cfg():
    return load_config(CFG_PATH, source="synthetic", start_date="2018-01-01", end_date="2021-12-31")


@pytest.fixture(scope="module")
def md(cfg):
    return make_synthetic(cfg)


def test_all_runtime_checks_pass_on_synthetic(md, cfg):
    res = run_backtest(md, cfg)
    attr = brinson_fachler(res, parent_universe(md, cfg), md)
    checks = run_checks(res, md, cfg, attr)
    failed = [c.name for c in checks if not c.passed]
    assert not failed, failed
    assert {c.name for c in checks} >= {
        "Weights sum to 100%", "Single-stock cap respected", "Sector cap respected",
        "Divisor keeps level continuous", "Dividends reconcile (TR − PR)",
        "Costs reconcile (NET vs TR)", "Attribution sums to active return"}


def test_dividend_check_catches_a_broken_total_return(md, cfg):
    res = run_backtest(md, cfg)
    res.levels["TR"] = res.levels["PR"]  # pretend dividends were dropped
    attr = brinson_fachler(res, parent_universe(md, cfg), md)
    check = {c.name: c for c in run_checks(res, md, cfg, attr)}["Dividends reconcile (TR − PR)"]
    assert not check.passed


def test_full_market_cap_is_not_labelled_free_float(md):
    plain = MarketData(md.prices, md.dividends, md.shares, md.volume, pd.Series(1.0, index=md.tickers),
                       md.sectors, md.benchmark, source="yahoo")
    assert not plain.is_free_float
    assert "full market cap" in plain.weighting_basis
    assert md.is_free_float  # the simulator does provide IWFs


def test_provenance_flags_look_ahead_share_counts(md, cfg):
    src = pd.DataFrame(PIT, index=md.prices.index, columns=md.tickers)
    src.iloc[:, :10] = CURRENT
    src.iloc[: len(src) // 2, 10:20] = BACKFILLED
    flagged = MarketData(md.prices, md.dividends, md.shares, md.volume, md.iwf, md.sectors,
                         md.benchmark, source="yahoo", shares_source=src)
    prov = provenance(run_backtest(flagged, cfg), flagged, cfg)
    assert prov["shares_current_fallback_weight"] > 0
    assert prov["shares_backfilled_weight"] > 0
    total = (prov["shares_point_in_time_weight"] + prov["shares_backfilled_weight"]
             + prov["shares_current_fallback_weight"])
    assert total == pytest.approx(1.0)


def test_shareholding_file_is_point_in_time(tmp_path):
    f = tmp_path / "sh.csv"
    pd.DataFrame({
        "date": ["2020-03-31", "2020-06-30"],
        "ticker": ["ABC", "ABC"],
        "shares_outstanding": [100.0, 120.0],
        "promoter_holding_pct": [60.0, 55.0],
    }).to_csv(f, index=False)
    idx = pd.bdate_range("2020-01-01", "2020-09-30")
    shares, iwf = load_shareholding(f, idx, ["ABC.NS"], lag_days=21)
    # nothing is known before the first pattern is published (no back-fill)
    assert shares.loc["2020-04-20", "ABC.NS"] != shares.loc["2020-04-20", "ABC.NS"]  # NaN
    # usable from 21 days after quarter-end, never before
    assert shares.loc["2020-04-21", "ABC.NS"] == 100.0
    assert shares.loc["2020-07-20", "ABC.NS"] == 100.0
    assert shares.loc["2020-07-21", "ABC.NS"] == 120.0
    assert iwf.loc["2020-08-03", "ABC.NS"] == pytest.approx(0.45)


def test_shareholding_file_missing_columns_raises(tmp_path):
    f = tmp_path / "bad.csv"
    pd.DataFrame({"date": ["2020-03-31"], "ticker": ["ABC"]}).to_csv(f, index=False)
    with pytest.raises(ValueError):
        load_shareholding(f, pd.bdate_range("2020-01-01", periods=5), ["ABC.NS"])


def test_as_reported_shares_restated_for_later_splits():
    idx = pd.bdate_range("2020-01-01", periods=6)
    shares = pd.DataFrame({"X": [100.0] * 3 + [200.0] * 3}, index=idx)  # 2:1 split on day 4
    splits = pd.DataFrame({"X": [0, 0, 0, 2.0, 0, 0]}, index=idx)
    restated = restate_to_current_basis(shares, splits)
    assert np.allclose(restated["X"], 200.0)
