"""Invariant tests: the properties a correct index calculator must satisfy."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from index_engine import analytics as an
from index_engine.attribution import brinson_fachler
from index_engine.config import load_config
from index_engine.data import make_synthetic
from index_engine.engine import rebalance_positions, run_backtest
from index_engine.pipeline import parent_universe
from index_engine.weighting import cap_weights

CFG_PATH = Path(__file__).resolve().parents[1] / "config" / "india_large_cap_40.yaml"


@pytest.fixture(scope="module")
def cfg():
    return load_config(CFG_PATH, source="synthetic", start_date="2018-01-01", end_date="2021-12-31")


@pytest.fixture(scope="module")
def md(cfg):
    return make_synthetic(cfg)


@pytest.fixture(scope="module")
def res(md, cfg):
    return run_backtest(md, cfg)


# ------------------------------------------------------------------ capping
def test_capping_respects_stock_and_sector_caps():
    rng = np.random.default_rng(1)
    w = pd.Series(rng.pareto(1.2, 40) + 0.01, index=[f"S{i}" for i in range(40)])
    sectors = pd.Series([f"sec{i % 6}" for i in range(40)], index=w.index)
    sectors.iloc[:12] = "sec0"  # make one sector heavy
    capped = cap_weights(w, sectors, 0.10, 0.30)
    assert capped.sum() == pytest.approx(1.0)
    assert capped.max() <= 0.10 + 1e-9
    assert capped.groupby(sectors).sum().max() <= 0.30 + 1e-9
    assert (capped > 0).all()


def test_capping_preserves_order_among_uncapped_names():
    w = pd.Series([0.5, 0.2, 0.15, 0.1, 0.05], index=list("ABCDE"))
    sectors = pd.Series(list("xyzuv"), index=w.index)
    capped = cap_weights(w, sectors, 0.25, 1.0)
    # A is capped; redistribution then pushes B over the cap too (cascading caps)
    assert capped["A"] == pytest.approx(0.25)
    assert capped["B"] == pytest.approx(0.25)
    # excess redistributed pro rata: ratios among still-uncapped names unchanged
    assert capped["C"] / capped["E"] == pytest.approx(0.15 / 0.05)
    assert capped["D"] / capped["E"] == pytest.approx(0.10 / 0.05)


def test_infeasible_caps_raise():
    w = pd.Series(1.0, index=list("ABC"))
    with pytest.raises(ValueError):
        cap_weights(w, pd.Series(list("xyz"), index=w.index), 0.2, 1.0)


# ------------------------------------------------------------------ index mechanics
def test_level_is_continuous_across_rebalances(res, md):
    """Divisor adjustment: re-pricing the new basket with the new divisor must reproduce the
    level computed from the old basket at the same close."""
    prices = md.prices.ffill()
    for r in res.rebalances[1:]:
        p = prices.loc[r.date, r.constituents]
        level_new_basket = (r.index_shares * p).sum() / r.divisor_after
        assert level_new_basket == pytest.approx(r.level, rel=1e-10)
        assert res.levels.loc[r.date, "PR"] == pytest.approx(r.level, rel=1e-10)


def test_weights_sum_to_one_and_respect_caps_at_rebalance(res, md, cfg):
    for r in res.rebalances:
        assert r.effective_weights.sum() == pytest.approx(1.0)
        assert r.target_weights.max() <= cfg.single_stock_cap + 1e-9
        assert r.target_weights.groupby(md.sectors[r.constituents]).sum().max() <= cfg.sector_cap + 1e-9
        assert len(r.constituents) == cfg.n_constituents
    assert np.allclose(res.weights.sum(axis=1), 1.0)


def test_total_return_beats_price_return_by_dividends(res):
    assert res.levels["TR"].iloc[-1] > res.levels["PR"].iloc[-1]
    assert (res.levels["NET"] <= res.levels["TR"] + 1e-9).all()


def test_zero_cost_net_equals_gross(md, cfg):
    r = run_backtest(md, cfg.with_overrides(transaction_cost_bps=0.0))
    assert np.allclose(r.levels["NET"], r.levels["TR"])


def test_no_look_ahead_selection_uses_reference_date(res, cfg):
    for r in res.rebalances:
        assert r.ref_date < r.date


def test_buffer_rule_reduces_turnover(md, cfg):
    no_buffer = run_backtest(md, cfg.with_overrides(retain_rank=cfg.n_constituents))
    with_buffer = run_backtest(md, cfg)
    t0 = no_buffer.rebalance_table()["one_way_turnover"].sum()
    t1 = with_buffer.rebalance_table()["one_way_turnover"].sum()
    assert t1 <= t0


def test_rebalance_calendar_quarterly():
    dates = pd.bdate_range("2020-01-01", "2020-12-31")
    pos = rebalance_positions(dates, "2020-01-01", "quarterly")
    assert [dates[p].month for p in pos] == [3, 6, 9, 12]
    assert all(dates[p] == dates[dates.month == dates[p].month][-1] for p in pos)


# ------------------------------------------------------------------ attribution
def test_brinson_effects_sum_to_active_return(res, md, cfg):
    parent = parent_universe(md, cfg)
    attr = brinson_fachler(res, parent, md)
    t = attr["totals"]["value"]
    assert abs(t["residual"]) < 1e-10
    pr_total = res.levels["PR"].iloc[-1] / res.levels["PR"].iloc[0] - 1
    assert t["index_return"] == pytest.approx(pr_total, rel=1e-9)


# ------------------------------------------------------------------ analytics
def test_analytics_on_known_series():
    idx = pd.bdate_range("2020-01-01", periods=252)
    r = pd.Series(0.001, index=idx)
    assert an.cagr(r) == pytest.approx(1.001 ** 252 - 1)
    b = pd.Series(np.random.default_rng(0).normal(0, 0.01, 252), index=idx)
    rel = an.relative_stats(2 * b, b)
    assert rel["beta"] == pytest.approx(2.0)
    assert rel["correlation"] == pytest.approx(1.0)


def test_max_drawdown():
    r = pd.Series([0.1, -0.5, 0.2, 1.0], index=pd.bdate_range("2020-01-01", periods=4))
    assert an.max_drawdown_details(r)["max_drawdown"] == pytest.approx(-0.5)
