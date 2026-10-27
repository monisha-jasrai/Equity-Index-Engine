"""Target-weight schemes, including iterative single-stock + sector capping."""
from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-12


def cap_weights(w: pd.Series, sectors: pd.Series, stock_cap: float, sector_cap: float,
                max_iter: int = 500) -> pd.Series:
    """Impose a single-stock cap and a sector cap, redistributing excess weight pro rata
    to the names / sectors still below their caps. Iterates until both constraints hold
    (alternating projections; converges for any feasible cap set)."""
    w = (w / w.sum()).astype(float).copy()
    sec = sectors.reindex(w.index)
    if stock_cap * len(w) < 1 - 1e-9:
        raise ValueError("stock cap infeasible for this many constituents")
    if sector_cap * sec.nunique() < 1 - 1e-9:
        raise ValueError("sector cap infeasible for this many sectors")

    for _ in range(max_iter):
        # 1) single-stock cap
        over = w > stock_cap + EPS
        if over.any():
            excess = (w[over] - stock_cap).sum()
            w[over] = stock_cap
            sec_tot = w.groupby(sec).sum()
            room = (~over) & (w < stock_cap - EPS) & sec.map(sec_tot < sector_cap - EPS)
            _spread(w, room, excess, stock_cap)
        # 2) sector cap
        sec_tot = w.groupby(sec).sum()
        over_s = sec_tot[sec_tot > sector_cap + EPS]
        if len(over_s):
            excess = 0.0
            for s, tot in over_s.items():
                m = sec == s
                w[m] *= sector_cap / tot
                excess += tot - sector_cap
            open_sec = ~sec.isin(over_s.index) & sec.map(w.groupby(sec).sum() < sector_cap - EPS)
            room = open_sec & (w < stock_cap - EPS)
            _spread(w, room, excess, stock_cap)
        sec_tot = w.groupby(sec).sum()
        if (w <= stock_cap + 1e-9).all() and (sec_tot <= sector_cap + 1e-9).all():
            return w / w.sum()
    raise RuntimeError("capping did not converge")


def _spread(w: pd.Series, room: pd.Series, excess: float, stock_cap: float) -> None:
    """Add `excess` pro rata to names in `room`; fall back to any name below its cap."""
    if not room.any() or w[room].sum() <= EPS:
        room = w < stock_cap - EPS
    if room.any() and w[room].sum() > EPS:
        w[room] += excess * w[room] / w[room].sum()


def target_weights(scheme: str, tickers: list[str], float_mcap: pd.Series,
                   returns_hist: pd.DataFrame, sectors: pd.Series,
                   stock_cap: float, sector_cap: float) -> pd.Series:
    fmc = float_mcap.reindex(tickers).astype(float)
    if scheme == "market_cap":
        w = fmc
    elif scheme == "capped_market_cap":
        return cap_weights(fmc, sectors, stock_cap, sector_cap)
    elif scheme == "equal":
        w = pd.Series(1.0, index=tickers)
    elif scheme == "sqrt_cap":
        w = np.sqrt(fmc)
    elif scheme == "inverse_vol":
        vol = returns_hist[tickers].std()
        vol = vol.fillna(vol.median()).clip(lower=1e-4)
        w = 1.0 / vol
    else:
        raise ValueError(scheme)
    return w / w.sum()


def concentration(w: pd.Series) -> dict[str, float]:
    """Herfindahl index and effective number of constituents."""
    w = w[w > 0] / w.sum()
    hhi = float((w ** 2).sum())
    top10 = float(w.sort_values(ascending=False).head(10).sum())
    return {"hhi": hhi, "effective_n": 1.0 / hhi, "top10_weight": top10, "max_weight": float(w.max())}
