"""Divisor-based index calculation with periodic reconstitution and rebalancing.

Index level (price return), exactly as exchange index providers compute it:

    Level_t = sum_i( q_i * P_i,t ) / Divisor

where q_i = shares_i * IWF_i * CF_i are the *index shares* (shares outstanding x
investable weight factor x capping factor), frozen between rebalances.

At each rebalance the constituent set and q_i change, so the divisor is reset to keep
the level continuous:

    Divisor_new = Divisor_old * MV_new / MV_old          (MV measured at the same close)

Three series are produced:
    PR  – price return (official index level)
    TR  – gross total return (cash dividends reinvested across the index on ex-date)
    NET – investable TR net of transaction costs on rebalance turnover
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import FREQUENCIES, IndexConfig
from .data import MarketData
from .universe import select_constituents
from .weighting import concentration, target_weights


@dataclass
class Rebalance:
    date: pd.Timestamp
    ref_date: pd.Timestamp
    constituents: list[str]
    additions: list[str]
    deletions: list[str]
    target_weights: pd.Series
    effective_weights: pd.Series
    index_shares: pd.Series
    capping_factors: pd.Series
    divisor_before: float
    divisor_after: float
    level: float
    one_way_turnover: float
    cost: float
    n_eligible: int
    concentration: dict


@dataclass
class BacktestResult:
    name: str
    scheme: str
    levels: pd.DataFrame            # columns PR, TR, NET
    divisor: pd.Series
    weights: pd.DataFrame           # end-of-day drifted weights
    rebalances: list[Rebalance] = field(default_factory=list)

    @property
    def returns(self) -> pd.DataFrame:
        return self.levels.pct_change().dropna()

    def sector_weights(self, sectors: pd.Series) -> pd.DataFrame:
        return self.weights.T.groupby(sectors.reindex(self.weights.columns)).sum().T

    def rebalance_table(self) -> pd.DataFrame:
        rows = [{
            "date": r.date.date(), "ref_date": r.ref_date.date(), "n": len(r.constituents),
            "eligible": r.n_eligible, "adds": len(r.additions), "dels": len(r.deletions),
            "additions": ", ".join(a.replace(".NS", "") for a in r.additions),
            "deletions": ", ".join(d.replace(".NS", "") for d in r.deletions),
            "one_way_turnover": r.one_way_turnover, "cost_bps": r.cost * 1e4,
            "divisor": r.divisor_after, "level": r.level,
            "max_weight": r.concentration["max_weight"],
            "effective_n": r.concentration["effective_n"],
        } for r in self.rebalances]
        return pd.DataFrame(rows).set_index("date")


def rebalance_positions(dates: pd.DatetimeIndex, start: str, frequency: str) -> list[int]:
    """Row positions of the last trading day of each rebalance month on/after `start`."""
    step = FREQUENCIES[frequency]
    s = pd.Series(np.arange(len(dates)), index=dates)
    month_ends = s.groupby(dates.to_period("M")).last()
    picks = [int(p) for per, p in month_ends.items()
             if per.month % step == 0 and dates[p] >= pd.Timestamp(start)]
    if not picks:
        raise ValueError("no rebalance dates in range")
    return picks


def run_backtest(md: MarketData, cfg: IndexConfig, scheme: str | None = None,
                 name: str | None = None) -> BacktestResult:
    scheme = scheme or cfg.scheme
    prices = md.prices.ffill()
    P = prices.to_numpy()
    Dv = md.dividends.to_numpy()
    dates = prices.index
    tickers = np.array(md.tickers)
    fmc_all = md.float_market_cap()
    rets_all = md.prices.pct_change(fill_method=None)

    rb_pos = rebalance_positions(dates, cfg.start_date, cfg.frequency)
    end_pos = len(dates) - 1
    if rb_pos[-1] == end_pos:
        rb_pos = rb_pos[:-1]  # a rebalance on the final day has no holding period

    n_days = end_pos - rb_pos[0] + 1
    pr = np.empty(n_days)
    tr = np.empty(n_days)
    net = np.empty(n_days)
    div_series = np.empty(n_days)
    W = np.zeros((n_days, len(tickers)))

    q = np.zeros(len(tickers))
    divisor = np.nan
    current: list[str] = []
    rebalances: list[Rebalance] = []
    col = {t: i for i, t in enumerate(tickers)}

    for k, R in enumerate(rb_pos):
        ref = max(0, R - cfg.reference_lag_days)
        sel = select_constituents(md, cfg, ref, current)
        cons = sel.constituents
        if scheme == "capped_market_cap" and len(cons) * cfg.single_stock_cap < 1:
            raise RuntimeError(
                f"Only {len(cons)} stocks were eligible on {dates[ref].date()}, too few for a "
                f"{cfg.single_stock_cap:.0%} stock cap. This usually means the data download was "
                f"incomplete ({len(sel.excluded)} excluded, e.g. "
                f"{dict(list(sel.excluded.items())[:3])}). Wait 10-15 minutes and rerun with --refresh.")
        hist = rets_all.iloc[max(0, ref - cfg.vol_lookback_days + 1): ref + 1]
        fmc_ref = fmc_all.iloc[ref]
        w_t = target_weights(scheme, cons, fmc_ref, hist, md.sectors,
                             cfg.single_stock_cap, cfg.sector_cap)

        # Capping factor: scales each name's float shares so weights hit target at ref.
        w_mc = fmc_ref[cons] / fmc_ref[cons].sum()
        cf = (w_t / w_mc)
        cf = cf / cf.max()                          # convention: largest CF = 1
        q_new = np.zeros(len(tickers))
        idx = [col[t] for t in cons]
        q_new[idx] = (md.shares.iloc[ref][cons] * md.iwf_at(ref)[cons] * cf).to_numpy()

        p_R = P[R]
        mv_new = np.nansum(q_new * p_R)
        i = R - rb_pos[0]
        if k == 0:
            level = cfg.base_value
            d_before = np.nan
            divisor = mv_new / level
            w_drift = np.zeros(len(tickers))
            tr_level = net_level = level
            turnover, cost = 0.0, 0.0              # index launch: no turnover charged
        else:
            mv_old = np.nansum(q * p_R)
            level = mv_old / divisor
            d_before = divisor
            divisor = divisor * mv_new / mv_old    # continuity: level unchanged
            w_drift = np.nan_to_num(q * p_R / mv_old)
            tr_level, net_level = tr[i], net[i]
        w_eff = np.nan_to_num(q_new * p_R / mv_new)
        if k > 0:
            traded = np.abs(w_eff - w_drift).sum()
            turnover = traded / 2
            cost = traded * cfg.transaction_cost_bps / 1e4
            net_level *= (1 - cost)

        pr[i], tr[i], net[i], div_series[i] = level, tr_level, net_level, divisor
        W[i] = w_eff

        stop = rb_pos[k + 1] if k + 1 < len(rb_pos) else end_pos
        # vectorised daily path for the holding period (R, stop]
        seg = slice(R + 1, stop + 1)
        mv = np.nansum(q_new * P[seg], axis=1)
        mv_prev = np.concatenate([[mv_new], mv[:-1]])
        gross = np.nansum(q_new * (P[seg] + Dv[seg]), axis=1) / mv_prev
        j = slice(i + 1, stop - rb_pos[0] + 1)
        pr[j] = mv / divisor
        tr[j] = tr_level * np.cumprod(gross)
        net[j] = net_level * np.cumprod(gross)
        div_series[j] = divisor
        W[j] = np.nan_to_num(q_new * P[seg] / mv[:, None])

        rebalances.append(Rebalance(
            date=dates[R], ref_date=dates[ref], constituents=cons,
            additions=sel.additions, deletions=sel.deletions,
            target_weights=w_t, effective_weights=pd.Series(w_eff[idx], index=cons),
            index_shares=pd.Series(q_new[idx], index=cons), capping_factors=cf,
            divisor_before=d_before, divisor_after=divisor, level=level,
            one_way_turnover=turnover, cost=cost, n_eligible=len(sel.eligible),
            concentration=concentration(w_t),
        ))
        q, current = q_new, cons

    out_dates = dates[rb_pos[0]: end_pos + 1]
    levels = pd.DataFrame({"PR": pr, "TR": tr, "NET": net}, index=out_dates)
    return BacktestResult(
        name=name or scheme, scheme=scheme, levels=levels,
        divisor=pd.Series(div_series, index=out_dates, name="divisor"),
        weights=pd.DataFrame(W, index=out_dates, columns=tickers),
        rebalances=rebalances,
    )
