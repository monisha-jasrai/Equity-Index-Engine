"""Return attribution.

* Brinson-Fachler sector attribution of the index vs. a parent benchmark, computed per
  holding period (between rebalances, where index shares are fixed, so buy-and-hold
  period returns are exact) and linked across periods with Carino smoothing so the
  effects sum to the cumulative active return.
* Constituent and sector contribution to index return.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import MarketData
from .engine import BacktestResult


def _period_returns(prices: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    return prices.loc[end] / prices.loc[start] - 1


def _carino_k(r_p: float, r_b: float) -> float:
    if np.isclose(r_p, r_b):
        return 1.0 / (1.0 + r_p)
    return (np.log1p(r_p) - np.log1p(r_b)) / (r_p - r_b)


def brinson_fachler(portfolio: BacktestResult, benchmark: BacktestResult,
                    md: MarketData) -> dict[str, pd.DataFrame]:
    prices = md.prices.ffill()
    sectors = md.sectors
    end = portfolio.levels.index[-1]
    p_reb = {r.date: r for r in portfolio.rebalances}
    b_reb = {r.date: r for r in benchmark.rebalances}
    dates = sorted(set(p_reb) & set(b_reb))

    rows = []
    for k, d in enumerate(dates):
        nxt = dates[k + 1] if k + 1 < len(dates) else end
        if nxt <= d:
            continue
        R = _period_returns(prices, d, nxt)
        wp = p_reb[d].effective_weights
        wb = b_reb[d].effective_weights
        rp_tot = float((wp * R[wp.index]).sum())
        rb_tot = float((wb * R[wb.index]).sum())
        wp_s = wp.groupby(sectors[wp.index]).sum()
        wb_s = wb.groupby(sectors[wb.index]).sum()
        rp_s = (wp * R[wp.index]).groupby(sectors[wp.index]).sum() / wp_s
        rb_s = (wb * R[wb.index]).groupby(sectors[wb.index]).sum() / wb_s
        for s in sorted(set(wp_s.index) | set(wb_s.index)):
            wps, wbs = wp_s.get(s, 0.0), wb_s.get(s, 0.0)
            rbs = rb_s.get(s, 0.0)
            rps = rp_s.get(s, rbs)
            rows.append({
                "start": d, "end": nxt, "sector": s,
                "w_index": wps, "w_bench": wbs, "r_index": rps, "r_bench": rbs,
                "allocation": (wps - wbs) * (rbs - rb_tot),
                "selection": wbs * (rps - rbs),
                "interaction": (wps - wbs) * (rps - rbs),
                "R_index": rp_tot, "R_bench": rb_tot,
            })
    df = pd.DataFrame(rows)

    # Carino linking
    per = df.groupby("start")[["R_index", "R_bench"]].first()
    Rp = float((1 + per["R_index"]).prod() - 1)
    Rb = float((1 + per["R_bench"]).prod() - 1)
    K = _carino_k(Rp, Rb)
    kt = per.apply(lambda x: _carino_k(x["R_index"], x["R_bench"]), axis=1)
    scale = df["start"].map(kt / K)
    for e in ("allocation", "selection", "interaction"):
        df[e + "_linked"] = df[e] * scale

    by_sector = df.groupby("sector")[["allocation_linked", "selection_linked", "interaction_linked"]].sum()
    by_sector.columns = ["allocation", "selection", "interaction"]
    by_sector["total"] = by_sector.sum(axis=1)
    by_sector = by_sector.sort_values("total", ascending=False)
    totals = pd.Series({
        "index_return": Rp, "benchmark_return": Rb, "active_return": Rp - Rb,
        "allocation": by_sector["allocation"].sum(), "selection": by_sector["selection"].sum(),
        "interaction": by_sector["interaction"].sum(),
    })
    totals["residual"] = totals["active_return"] - totals[["allocation", "selection", "interaction"]].sum()
    return {"periods": df, "by_sector": by_sector, "totals": totals.to_frame("value")}


def contributions(res: BacktestResult, md: MarketData) -> dict[str, pd.DataFrame]:
    """Daily w_{t-1} * r_t contributions (price return), summed over the backtest."""
    r = md.prices.ffill().pct_change(fill_method=None).reindex(res.weights.index).fillna(0.0)
    w_prev = res.weights.shift(1).fillna(0.0)
    contrib = (w_prev * r).iloc[1:]
    stock = contrib.sum().sort_values(ascending=False)
    stock = stock[(stock != 0) | (res.weights.sum() > 0)]
    days_held = (res.weights > 0).sum()
    stock_df = pd.DataFrame({
        "sector": md.sectors.reindex(stock.index),
        "contribution": stock,
        "avg_weight": res.weights[stock.index].where(res.weights[stock.index] > 0).mean(),
        "days_in_index": days_held.reindex(stock.index),
    })
    stock_df = stock_df[stock_df["days_in_index"] > 0]
    sector = contrib.T.groupby(md.sectors.reindex(contrib.columns)).sum().T.sum()
    return {"stocks": stock_df, "sectors": sector.sort_values(ascending=False).to_frame("contribution")}
