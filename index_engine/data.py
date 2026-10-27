"""Market data layer.

Two interchangeable sources produce the same `MarketData` container:

* `load_yahoo`   – real NSE data via yfinance (split-adjusted closes, cash dividends,
                   volume, shares outstanding), cached to parquet/CSV.
* `make_synthetic` – a reproducible multi-factor market simulator (market + sector
                   factors, GARCH volatility, fat-tailed shocks, dividends, buybacks,
                   illiquid names) so the engine runs and is testable fully offline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import IndexConfig

log = logging.getLogger(__name__)


@dataclass
class MarketData:
    prices: pd.DataFrame      # date x ticker, close (split-adjusted, NOT dividend-adjusted)
    dividends: pd.DataFrame   # date x ticker, cash dividend per share on ex-date (0 otherwise)
    shares: pd.DataFrame      # date x ticker, shares outstanding
    volume: pd.DataFrame      # date x ticker, shares traded
    iwf: pd.Series            # ticker -> investable weight factor (free-float fraction)
    sectors: pd.Series        # ticker -> sector
    benchmark: pd.Series      # date -> benchmark price-return level
    source: str = "unknown"

    def __post_init__(self) -> None:
        idx = self.prices.index
        for name in ("dividends", "shares", "volume"):
            df = getattr(self, name).reindex(index=idx, columns=self.prices.columns)
            setattr(self, name, df)
        self.dividends = self.dividends.fillna(0.0)
        self.volume = self.volume.fillna(0.0)
        self.shares = self.shares.ffill().bfill()
        self.benchmark = self.benchmark.reindex(idx).ffill()
        self.iwf = self.iwf.reindex(self.prices.columns).fillna(1.0)
        self.sectors = self.sectors.reindex(self.prices.columns)

    @property
    def tickers(self) -> list[str]:
        return list(self.prices.columns)

    def float_market_cap(self) -> pd.DataFrame:
        return self.prices * self.shares * self.iwf

    def traded_value(self) -> pd.DataFrame:
        return self.prices * self.volume


# --------------------------------------------------------------------------- synthetic
def make_synthetic(cfg: IndexConfig) -> MarketData:
    """Simulate a realistic large-cap equity market for the configured universe."""
    rng = np.random.default_rng(cfg.synthetic_seed)
    dates = pd.bdate_range(pd.Timestamp(cfg.start_date) - pd.offsets.BDay(300), cfg.end_date)
    T = len(dates)
    tickers = list(cfg.universe)
    sectors = pd.Series(cfg.universe)
    sec_names = sorted(sectors.unique())
    N, S = len(tickers), len(sec_names)

    # --- market factor with GARCH(1,1) volatility and a stress episode --------------
    omega, alpha, beta = 9e-7, 0.08, 0.90
    var = np.empty(T)
    mkt = np.empty(T)
    var[0] = omega / (1 - alpha - beta)
    mu_daily = 0.12 / 252
    z = rng.standard_t(df=5, size=T) / np.sqrt(5 / 3)  # unit-variance Student-t
    stress = np.zeros(T)
    s0 = int(T * 0.42)                                 # a crash ~40% into the sample
    stress[s0:s0 + 25] = -0.012
    stress[s0 + 25:s0 + 90] = 0.004                    # partial V-shaped recovery
    for t in range(T):
        if t > 0:
            var[t] = omega + alpha * mkt[t - 1] ** 2 + beta * var[t - 1]
        shock_scale = 1.6 if s0 <= t < s0 + 25 else 1.0
        mkt[t] = mu_daily + stress[t] + np.sqrt(var[t]) * z[t] * shock_scale

    sec_ret = rng.normal(0.0, 0.004, size=(T, S))
    sec_ret += rng.normal(0.0, 0.03 / 252, size=S)     # persistent sector drift differences
    sec_idx = sectors.map({s: i for i, s in enumerate(sec_names)}).to_numpy()

    betas = rng.uniform(0.7, 1.3, N)
    idio_vol = rng.uniform(0.15, 0.35, N) / np.sqrt(252)
    alpha_i = rng.normal(0.0, 0.05, N) / 252
    idio = rng.standard_t(df=4, size=(T, N)) / np.sqrt(2) * idio_vol
    rets = alpha_i + betas * mkt[:, None] + sec_ret[:, sec_idx] + idio
    rets = np.clip(rets, -0.35, 0.35)

    # --- dividends: quarterly, yield 0-3%, price drops by the dividend on ex-date ------
    div_yield = rng.uniform(0.0, 0.03, N)
    ex_mask = np.zeros((T, N), dtype=bool)
    q_ends = dates.to_series().groupby(dates.to_period("Q")).nth(30).index  # ~mid-quarter
    for j in range(N):
        offset = rng.integers(0, 15)
        pos = np.clip(dates.get_indexer(q_ends) + offset, 0, T - 1)
        ex_mask[pos, j] = True

    prices = np.empty((T, N))
    divs = np.zeros((T, N))
    prices[0] = rng.lognormal(mean=6.5, sigma=1.0, size=N)  # ~INR 100 - 5000
    for t in range(1, T):
        p = prices[t - 1] * (1.0 + rets[t])
        d = np.where(ex_mask[t], prices[t - 1] * div_yield / 4, 0.0)
        divs[t] = d
        prices[t] = np.maximum(p - d, 0.01)

    # --- shares outstanding: Pareto-like initial caps, occasional buybacks / issuance --
    init_cap = rng.pareto(1.8, N) * 1.5e12 + 1.0e12                 # INR market caps
    shares0 = init_cap / prices[0]
    events = rng.random((T, N)) < 1 / 500
    changes = np.where(events, rng.uniform(-0.03, 0.05, (T, N)), 0.0)
    shares = shares0 * np.cumprod(1.0 + changes, axis=0)

    # --- volume: turnover-ratio model, with a few deliberately illiquid names -------
    base_turn = rng.uniform(0.001, 0.005, N)
    base_turn[rng.choice(N, size=4, replace=False)] = 0.00002
    volume = shares * base_turn * rng.lognormal(0.0, 0.5, (T, N)) * (1 + 8 * np.abs(rets))

    # --- late listings: a few names only start trading partway through ----------------
    late = rng.choice(N, size=3, replace=False)
    for j in late:
        start = rng.integers(int(T * 0.2), int(T * 0.6))
        prices[:start, j] = np.nan
        volume[:start, j] = np.nan
        divs[:start, j] = 0.0

    iwf = pd.Series(np.round(rng.uniform(0.35, 0.95, N), 2), index=tickers)

    P = pd.DataFrame(prices, index=dates, columns=tickers)
    D = pd.DataFrame(divs, index=dates, columns=tickers)
    SH = pd.DataFrame(shares, index=dates, columns=tickers)
    V = pd.DataFrame(volume, index=dates, columns=tickers)

    # Benchmark: a broad float-cap index of the whole universe with tracking noise.
    fmc = (P * SH * iwf).shift(1)
    w = fmc.div(fmc.sum(axis=1), axis=0)
    bench_ret = (w * P.pct_change(fill_method=None)).sum(axis=1) + rng.normal(0, 0.0015, T)
    bench = 10000.0 * (1 + bench_ret.fillna(0)).cumprod()

    return MarketData(P, D, SH, V, iwf, sectors, bench, source="synthetic")


# ------------------------------------------------------------------------------ yahoo
def load_yahoo(cfg: IndexConfig, refresh: bool = False) -> MarketData:
    """Download (or read from cache) real NSE data via yfinance."""
    import yfinance as yf  # imported lazily so offline use doesn't need it

    cache = Path(cfg.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    files = {k: cache / f"{k}.csv" for k in ("prices", "dividends", "volume", "shares", "benchmark")}
    tickers = list(cfg.universe)
    hist_start = (pd.Timestamp(cfg.start_date) - pd.DateOffset(years=2)).strftime("%Y-%m-%d")

    if refresh or not all(f.exists() for f in files.values()):
        log.info("Downloading %d tickers from Yahoo Finance...", len(tickers))
        raw = yf.download(tickers, start=hist_start, end=cfg.end_date, auto_adjust=False,
                          actions=True, group_by="column", progress=False, threads=True)
        raw.index = pd.to_datetime(raw.index).tz_localize(None)
        grab = lambda f: raw[f].reindex(columns=tickers) if f in raw.columns.get_level_values(0) \
            else pd.DataFrame(np.nan, index=raw.index, columns=tickers)
        prices = grab("Close")              # split-adjusted, not dividend-adjusted
        dividends = grab("Dividends").fillna(0.0)
        volume = grab("Volume")
        shares = _shares_history(tickers, prices.index, grab("Stock Splits"))
        bench = yf.download(cfg.benchmark_ticker, start=hist_start, end=cfg.end_date,
                            auto_adjust=False, progress=False)["Close"].squeeze()
        bench.index = pd.to_datetime(bench.index).tz_localize(None)
        missing = [t for t in tickers if prices[t].notna().sum() == 0]
        if missing:
            log.warning("No price data for %s (renamed/delisted?) - excluded", missing)
        for name, df in [("prices", prices), ("dividends", dividends), ("volume", volume),
                         ("shares", shares), ("benchmark", bench.to_frame("benchmark"))]:
            df.to_csv(files[name])

    read = lambda k: pd.read_csv(files[k], index_col=0, parse_dates=True)
    prices = read("prices").dropna(axis=1, how="all")
    cols = prices.columns
    iwf = pd.Series(1.0, index=cols)  # see README: free-float factors need an NSE data feed
    return MarketData(
        prices=prices,
        dividends=read("dividends").reindex(columns=cols),
        shares=read("shares").reindex(columns=cols),
        volume=read("volume").reindex(columns=cols),
        iwf=iwf,
        sectors=pd.Series(cfg.universe).reindex(cols),
        benchmark=read("benchmark")["benchmark"],
        source="yahoo",
    )


def _shares_history(tickers, index, splits: pd.DataFrame | None) -> pd.DataFrame:
    """Best-effort point-in-time shares outstanding on the same split-adjusted basis as
    Yahoo's `Close`. Falls back to the current share count when history is unavailable."""
    import yfinance as yf

    out = {}
    for t in tickers:
        tk = yf.Ticker(t)
        current = None
        try:
            current = float(tk.fast_info["shares"])
        except Exception:  # noqa: BLE001 - yfinance raises many exception types
            pass
        series = None
        try:
            hist = tk.get_shares_full(start=index[0].strftime("%Y-%m-%d"))
            if hist is not None and len(hist):
                hist.index = pd.to_datetime(hist.index).tz_localize(None).normalize()
                hist = hist[~hist.index.duplicated(keep="last")].sort_index()
                series = hist.reindex(index, method="ffill")
                if splits is not None and t in splits:
                    # restate historic share counts onto today's split-adjusted basis
                    sf = splits[t].replace(0, 1.0).fillna(1.0)
                    future_factor = sf[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
                    series = series * future_factor.reindex(index).fillna(1.0)
                if current and (series.dropna() / current).between(0.33, 3).mean() < 0.8:
                    series = None  # inconsistent history: don't trust it
        except Exception:  # noqa: BLE001
            series = None
        if series is None:
            series = pd.Series(current if current else np.nan, index=index)
        out[t] = series
    return pd.DataFrame(out, index=index).ffill().bfill()


def load_market_data(cfg: IndexConfig, refresh: bool = False) -> MarketData:
    if cfg.source == "synthetic":
        return make_synthetic(cfg)
    if cfg.source == "yahoo":
        return load_yahoo(cfg, refresh=refresh)
    raise ValueError(f"unknown data source {cfg.source!r}")
