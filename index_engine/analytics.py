"""Performance, risk and benchmark-relative analytics on daily return series."""
from __future__ import annotations

import numpy as np
import pandas as pd


def cagr(r: pd.Series, ppy: int = 252) -> float:
    growth = float((1 + r).prod())
    years = len(r) / ppy
    return growth ** (1 / years) - 1 if years > 0 else np.nan


def ann_vol(r: pd.Series, ppy: int = 252) -> float:
    return float(r.std(ddof=1) * np.sqrt(ppy))


def drawdown(r: pd.Series) -> pd.Series:
    wealth = (1 + r).cumprod()
    return wealth / wealth.cummax() - 1


def max_drawdown_details(r: pd.Series) -> dict:
    dd = drawdown(r)
    trough = dd.idxmin()
    peak = (1 + r).cumprod().loc[:trough].idxmax()
    after = dd.loc[trough:]
    rec = after[after >= -1e-12]
    recovery = rec.index[0] if len(rec) else None
    return {"max_drawdown": float(dd.min()), "peak": peak, "trough": trough, "recovery": recovery,
            "days_to_recover": (len(dd.loc[trough:recovery]) - 1) if recovery is not None else None}


def sharpe(r: pd.Series, rf: float = 0.0, ppy: int = 252) -> float:
    ex = r - rf / ppy
    return float(ex.mean() / ex.std(ddof=1) * np.sqrt(ppy))


def sortino(r: pd.Series, rf: float = 0.0, ppy: int = 252) -> float:
    ex = r - rf / ppy
    downside = np.sqrt((np.minimum(ex, 0) ** 2).mean()) * np.sqrt(ppy)
    return float(ex.mean() * ppy / downside)


def historical_var_cvar(r: pd.Series, level: float = 0.95) -> tuple[float, float]:
    q = r.quantile(1 - level)
    return float(-q), float(-r[r <= q].mean())


def relative_stats(r: pd.Series, b: pd.Series, rf: float = 0.0, ppy: int = 252) -> dict:
    r, b = r.align(b, join="inner")
    ex_r, ex_b = r - rf / ppy, b - rf / ppy
    cov = np.cov(ex_r, ex_b, ddof=1)
    beta = cov[0, 1] / cov[1, 1]
    alpha = (ex_r.mean() - beta * ex_b.mean()) * ppy           # Jensen's alpha (annual)
    active = r - b
    te = active.std(ddof=1) * np.sqrt(ppy)
    up, down = b > 0, b < 0
    return {
        "beta": float(beta),
        "alpha_annual": float(alpha),
        "correlation": float(np.corrcoef(r, b)[0, 1]),
        "tracking_error": float(te),
        "active_return": float(cagr(r, ppy) - cagr(b, ppy)),
        "information_ratio": float(active.mean() * ppy / te) if te > 0 else np.nan,
        "up_capture": float(r[up].mean() / b[up].mean()),
        "down_capture": float(r[down].mean() / b[down].mean()),
        "hit_rate_monthly": float(((1 + r).resample("ME").prod() > (1 + b).resample("ME").prod()).mean()),
    }


def summary(r: pd.Series, rf: float = 0.0, ppy: int = 252, bench: pd.Series | None = None) -> dict:
    dd = max_drawdown_details(r)
    var95, cvar95 = historical_var_cvar(r)
    c = cagr(r, ppy)
    out = {
        "cagr": c,
        "volatility": ann_vol(r, ppy),
        "sharpe": sharpe(r, rf, ppy),
        "sortino": sortino(r, rf, ppy),
        "max_drawdown": dd["max_drawdown"],
        "calmar": c / abs(dd["max_drawdown"]) if dd["max_drawdown"] < 0 else np.nan,
        "var_95_1d": var95,
        "cvar_95_1d": cvar95,
        "skew": float(r.skew()),
        "excess_kurtosis": float(r.kurt()),
        "best_month": float((1 + r).resample("ME").prod().max() - 1),
        "worst_month": float((1 + r).resample("ME").prod().min() - 1),
    }
    if bench is not None:
        out.update(relative_stats(r, bench, rf, ppy))
    return out


def rolling_relative(r: pd.Series, b: pd.Series, window: int = 252, ppy: int = 252) -> pd.DataFrame:
    r, b = r.align(b, join="inner")
    active = r - b
    beta = r.rolling(window).cov(b) / b.rolling(window).var()
    te = active.rolling(window).std() * np.sqrt(ppy)
    roll_ret = lambda x: (1 + x).rolling(window).apply(np.prod, raw=True) - 1
    return pd.DataFrame({
        "beta": beta,
        "tracking_error": te,
        "excess_return": roll_ret(r) - roll_ret(b),
        "volatility": r.rolling(window).std() * np.sqrt(ppy),
    }).dropna()


def calendar_returns(levels: pd.DataFrame) -> pd.DataFrame:
    yearly = levels.resample("YE").last()
    first = levels.iloc[[0]]
    yearly = pd.concat([first, yearly])
    out = yearly.pct_change().dropna()
    out.index = out.index.year
    return out


def block_bootstrap_active(r: pd.Series, b: pd.Series, n: int = 2000, block: int = 20,
                           ppy: int = 252, seed: int = 0) -> dict:
    """Moving-block bootstrap of annualised active return; preserves autocorrelation and
    volatility clustering that an i.i.d. bootstrap would destroy."""
    r, b = r.align(b, join="inner")
    a = (r - b).to_numpy()
    T = len(a)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(T / block))
    starts = rng.integers(0, T - block, size=(n, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)).reshape(n, -1)[:, :T]
    means = a[idx].mean(axis=1) * ppy
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"active_mean_annual": float(a.mean() * ppy), "ci_95_low": float(lo),
            "ci_95_high": float(hi), "p_active_positive": float((means > 0).mean())}
