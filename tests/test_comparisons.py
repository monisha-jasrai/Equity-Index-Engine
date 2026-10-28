"""Tests for like-for-like benchmark comparisons, the TRI loader and the rules bridge."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from index_engine import analytics as an
from index_engine.config import load_config
from index_engine.data import MarketData, load_benchmark_tri, make_synthetic
from index_engine.engine import run_backtest
from index_engine.pipeline import parent_universe, period_robustness, rules_bridge, run

CFG_PATH = Path(__file__).resolve().parents[1] / "config" / "india_large_cap_40.yaml"


@pytest.fixture(scope="module")
def cfg():
    return load_config(CFG_PATH, source="synthetic", start_date="2018-01-01", end_date="2021-12-31",
                       bootstrap_samples=200)


@pytest.fixture(scope="module")
def md(cfg):
    return make_synthetic(cfg)


def test_bridge_steps_sum_to_total_gap(md, cfg):
    capped = run_backtest(md, cfg)
    uncapped = run_backtest(md, cfg, scheme="market_cap")
    parent = parent_universe(md, cfg)
    nifty = md.benchmark.reindex(capped.levels.index).pct_change().dropna()
    br = rules_bridge(nifty, parent.returns["PR"], uncapped.returns["PR"], capped.returns["PR"], cfg)
    steps = br[br["kind"] == "step"]["value"].sum()
    total = br.loc["Total gap (index − NIFTY)", "value"]
    assert steps == pytest.approx(total, abs=1e-12)
    assert br.loc["Index", "value"] - br.loc["NIFTY 50", "value"] == pytest.approx(total, abs=1e-12)
    assert (br.loc[br["kind"] != "level", "ci_low"] <= br.loc[br["kind"] != "level", "ci_high"]).all()


def test_period_robustness_years():
    idx = pd.bdate_range("2020-01-01", "2022-12-31")
    b = pd.Series(0.0004, index=idx)
    r = b.copy()
    r[r.index.year == 2021] += 0.001          # all the active return in one year
    rob = period_robustness(r, b, 252)
    assert rob["best_year"] == 2021
    assert rob["years_positive"] == 1
    assert rob["active_ex_best_year"] == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("csv", [
    "Date,Total Returns Index\n01 Jan 2020,\"20,000.5\"\n02 Jan 2020,20100\n",
    "date,close\n2020-01-01,20000.5\n2020-01-02,20100\n",
])
def test_tri_loader_handles_common_formats(tmp_path, csv):
    rows = csv.splitlines()
    body = rows[1:] * 1
    # extend to > 20 rows with increasing dates
    dates = pd.bdate_range("2020-01-01", periods=30)
    header = rows[0]
    if "Total" in header:
        lines = [f'{d.strftime("%d %b %Y")},"{20000 + i:,}"' for i, d in enumerate(dates)]
    else:
        lines = [f"{d.date()},{20000 + i}" for i, d in enumerate(dates)]
    f = tmp_path / "tri.csv"
    f.write_text(header + "\n" + "\n".join(lines) + "\n")
    s = load_benchmark_tri(f)
    assert len(s) == 30 and s.iloc[0] == 20000 and s.index[0] == pd.Timestamp("2020-01-01")


def test_total_return_not_benchmarked_without_tri(md, cfg, tmp_path):
    no_tri = MarketData(md.prices, md.dividends, md.shares, md.volume, md.iwf, md.sectors,
                        md.benchmark, source="synthetic", iwf_source="synthetic")
    import index_engine.pipeline as pl
    orig = pl.load_market_data
    pl.load_market_data = lambda *a, **k: no_tri
    try:
        res = run(cfg, tmp_path / "out")
    finally:
        pl.load_market_data = orig
    assert "beta" in res["stats"]["Index PR"]          # PR vs PR comparison exists
    assert "beta" not in res["stats"]["Index TR"]      # TR is never compared with a price index
    assert "Benchmark TRI" not in res["stats"]
    text = (tmp_path / "out" / "report.md").read_text()
    assert "Total return is not compared with a benchmark" in text


def test_total_return_benchmarked_against_tri(md, cfg, tmp_path):
    res = run(cfg, tmp_path / "out2")
    assert "Benchmark TRI" in res["stats"]
    assert "beta" in res["stats"]["Index NET"]
    assert (tmp_path / "out2" / "charts" / "growth_tr.png").exists()
