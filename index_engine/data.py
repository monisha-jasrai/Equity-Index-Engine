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
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import IndexConfig

log = logging.getLogger(__name__)


# provenance codes for each (date, ticker) share count
PIT = "point_in_time"            # a share count reported on or before that date
BACKFILLED = "backfilled"        # before the first reported count: later value copied back (look-ahead)
CURRENT = "current_fallback"     # no history at all: today's count used for every date (look-ahead)
SHAREHOLDING = "shareholding_file"  # from the user's shareholding-pattern file (e.g. Capitaline)
SYNTHETIC = "synthetic"


@dataclass
class MarketData:
    prices: pd.DataFrame      # date x ticker, close (split-adjusted, NOT dividend-adjusted)
    dividends: pd.DataFrame   # date x ticker, cash dividend per share on ex-date (0 otherwise)
    shares: pd.DataFrame      # date x ticker, shares outstanding (on the price series' split basis)
    volume: pd.DataFrame      # date x ticker, shares traded
    iwf: pd.Series | pd.DataFrame  # investable weight factor: per ticker, or date x ticker
    sectors: pd.Series        # ticker -> sector
    benchmark: pd.Series      # date -> benchmark price-return level
    source: str = "unknown"
    shares_source: pd.DataFrame | None = None  # date x ticker provenance code (see above)
    iwf_source: str = "assumed_one"            # assumed_one | synthetic | shareholding_file
    iwf_known: pd.DataFrame | None = None      # set in __post_init__

    def __post_init__(self) -> None:
        idx, cols = self.prices.index, self.prices.columns
        for name in ("dividends", "shares", "volume"):
            setattr(self, name, getattr(self, name).reindex(index=idx, columns=cols))
        self.dividends = self.dividends.fillna(0.0)
        self.volume = self.volume.fillna(0.0)
        if self.shares_source is None:
            code = SYNTHETIC if self.source == "synthetic" else PIT
            self.shares_source = pd.DataFrame(code, index=idx, columns=cols)
        self.shares_source = self.shares_source.reindex(index=idx, columns=cols).ffill().fillna(BACKFILLED)
        before_first = self.shares.ffill().isna() & self.shares.bfill().notna()
        self.shares_source = self.shares_source.mask(before_first, BACKFILLED)
        self.shares = self.shares.ffill().bfill()
        self.benchmark = self.benchmark.reindex(idx).ffill()
        if isinstance(self.iwf, pd.DataFrame):
            raw = self.iwf.reindex(index=idx, columns=cols)
            self.iwf_known = raw.notna()               # False where IWF defaulted to 1
            self.iwf = raw.ffill().fillna(1.0)
        else:
            known = self.iwf_source != "assumed_one"
            self.iwf = self.iwf.reindex(cols).fillna(1.0)
            self.iwf_known = pd.DataFrame(known, index=idx, columns=cols)
        self.sectors = self.sectors.reindex(cols)

    @property
    def tickers(self) -> list[str]:
        return list(self.prices.columns)

    @property
    def is_free_float(self) -> bool:
        """True only when IWFs come from real free-float data (or the simulator)."""
        return self.iwf_source in ("synthetic", "shareholding_file")

    @property
    def weighting_basis(self) -> str:
        if self.iwf_source == "shareholding_file":
            return "free-float market cap (IWF = 1 − promoter holding, point-in-time)"
        if self.iwf_source == "synthetic":
            return "free-float market cap (simulated IWFs)"
        return "full market cap (IWF = 1: no historical free-float data)"

    def iwf_at(self, pos: int) -> pd.Series:
        return self.iwf.iloc[pos] if isinstance(self.iwf, pd.DataFrame) else self.iwf

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

    return MarketData(P, D, SH, V, iwf, sectors, bench, source="synthetic", iwf_source="synthetic")


# ------------------------------------------------------------------------------ yahoo
def load_yahoo(cfg: IndexConfig, refresh: bool = False) -> MarketData:
    """Download (or read from cache) real NSE data via yfinance."""
    cache = Path(cfg.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    names = ("prices", "dividends", "volume", "shares", "shares_source", "splits", "benchmark")
    files = {k: cache / f"{k}.csv" for k in names}
    tickers = list(cfg.universe)
    hist_start = (pd.Timestamp(cfg.start_date) - pd.DateOffset(years=2)).strftime("%Y-%m-%d")

    if refresh or not all(f.exists() for f in files.values()):
        import yfinance as yf  # imported lazily so offline use doesn't need it

        log.info("Downloading %d tickers from Yahoo Finance (in small batches)...", len(tickers))
        fields = _download_prices(yf, tickers, hist_start, cfg.end_date)
        prices = fields["Close"]            # split-adjusted, not dividend-adjusted
        dividends = fields["Dividends"].fillna(0.0)
        volume = fields["Volume"]
        splits = fields["Stock Splits"].fillna(0.0)
        bench = _retry(lambda: yf.download(cfg.benchmark_ticker, start=hist_start, end=cfg.end_date,
                                           auto_adjust=False, progress=False)["Close"].squeeze(),
                       ok=lambda b: b is not None and len(b) > 0, what="benchmark")
        if bench is None:
            raise RuntimeError("Could not download the benchmark from Yahoo. Wait a few minutes "
                               "and rerun with --refresh.")
        bench.index = pd.to_datetime(bench.index).tz_localize(None)
        missing = [t for t in tickers if prices[t].notna().sum() == 0]
        if missing:
            log.warning("No price data after retries for %s - excluded", missing)
        have = [t for t in tickers if t not in missing]
        log.info("Fetching share counts for %d tickers (one at a time, ~1-2 min)...", len(have))
        shares, shares_src = _shares_history(have, prices.index, splits[have])
        shares = shares.reindex(columns=tickers)
        shares_src = shares_src.reindex(columns=tickers)
        no_shares = [t for t in have if shares[t].isna().all()]
        if no_shares:
            log.warning("No share count available for %s - these will be excluded", no_shares)
        usable = len(have) - len(no_shares)
        if usable < len(tickers) - 5:
            log.warning("Only %d of %d tickers downloaded fully. Yahoo is probably rate-limiting; "
                        "wait 10-15 minutes and rerun with --refresh for complete data.",
                        usable, len(tickers))
        for name, df in [("prices", prices), ("dividends", dividends), ("volume", volume),
                         ("shares", shares), ("shares_source", shares_src), ("splits", splits),
                         ("benchmark", bench.to_frame("benchmark"))]:
            df.to_csv(files[name])

    read = lambda k: pd.read_csv(files[k], index_col=0, parse_dates=True)
    prices = read("prices").dropna(axis=1, how="all")
    cols = prices.columns
    shares = read("shares").reindex(columns=cols)
    shares_src = read("shares_source").reindex(columns=cols)
    splits = read("splits").reindex(columns=cols).fillna(0.0)
    iwf: pd.Series | pd.DataFrame = pd.Series(1.0, index=cols)
    iwf_source = "assumed_one"

    if cfg.shareholding_file:
        sh_shares, sh_iwf = load_shareholding(cfg.shareholding_file, prices.index, cols,
                                              cfg.shareholding_lag_days)
        sh_shares = restate_to_current_basis(sh_shares, splits)
        have = sh_shares.notna()
        shares = shares.where(~have, sh_shares)
        shares_src = shares_src.where(~have, SHAREHOLDING)
        iwf = sh_iwf
        iwf_source = "shareholding_file"
        log.info("Shareholding file applied: %.0f%% of stock-days have point-in-time data",
                 100 * have.to_numpy().mean())

    return MarketData(
        prices=prices,
        dividends=read("dividends").reindex(columns=cols),
        shares=shares,
        volume=read("volume").reindex(columns=cols),
        iwf=iwf,
        sectors=pd.Series(cfg.universe).reindex(cols),
        benchmark=read("benchmark")["benchmark"],
        source="yahoo",
        shares_source=shares_src,
        iwf_source=iwf_source,
    )


def split_factor_after(splits: pd.DataFrame) -> pd.DataFrame:
    """For each date, the product of split ratios that occur strictly AFTER it.
    Multiplying an as-reported share count by this restates it to today's basis."""
    sf = splits.replace(0, 1.0).fillna(1.0)
    return sf[::-1].cumprod()[::-1].shift(-1).fillna(1.0)


def restate_to_current_basis(shares: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    f = split_factor_after(splits.reindex(index=shares.index, columns=shares.columns).fillna(0.0))
    return shares * f


def load_shareholding(path: str | Path, index: pd.DatetimeIndex, tickers,
                      lag_days: int = 21) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read a shareholding-pattern file (e.g. a Capitaline export) with columns
    date, ticker, shares_outstanding, promoter_holding_pct.

    * `date` is the quarter-end the pattern refers to. Listed companies publish it about
      three weeks later, so each record becomes usable only `lag_days` calendar days
      after `date` (no look-ahead).
    * IWF = 1 − promoter holding. NSE also excludes some other locked-in holdings, so this
      is an approximation of the official factor.
    * Dates before a company's first record stay NaN (the caller keeps the Yahoo value
      and its provenance), never back-filled.
    """
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    need = {"date", "ticker", "shares_outstanding", "promoter_holding_pct"}
    if not need <= set(df.columns):
        raise ValueError(f"shareholding file needs columns {sorted(need)}, got {list(df.columns)}")
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df.loc[~df["ticker"].str.contains(r"\.", regex=True), "ticker"] += ".NS"
    df["available"] = pd.to_datetime(df["date"]) + pd.Timedelta(days=lag_days)
    df["iwf"] = (1 - df["promoter_holding_pct"].astype(float) / 100).clip(0.05, 1.0)
    out_sh, out_iwf = {}, {}
    for t in tickers:
        g = df[df["ticker"] == t].sort_values("available")
        if g.empty:
            out_sh[t] = pd.Series(np.nan, index=index)
            out_iwf[t] = pd.Series(np.nan, index=index)
            continue
        g = g.drop_duplicates("available", keep="last").set_index("available")
        out_sh[t] = g["shares_outstanding"].astype(float).reindex(index, method="ffill")
        out_iwf[t] = g["iwf"].reindex(index, method="ffill")
    return pd.DataFrame(out_sh, index=index), pd.DataFrame(out_iwf, index=index)


def _retry(fn, ok=lambda x: True, what="request", attempts=4, base_sleep=2.0):
    """Call fn() until ok(result) holds, backing off between attempts (Yahoo rate-limits)."""
    for i in range(attempts):
        try:
            res = fn()
            if ok(res):
                return res
        except Exception as e:  # noqa: BLE001 - yfinance raises many exception types
            log.debug("%s failed (attempt %d): %s", what, i + 1, e)
        if i < attempts - 1:
            time.sleep(base_sleep * (2 ** i))
    return None


def _download_prices(yf, tickers, start, end, batch=10) -> dict[str, pd.DataFrame]:
    """Download in small batches, then retry any ticker that came back empty, one at a time."""
    fields = ("Close", "Dividends", "Volume", "Stock Splits")
    parts = {f: [] for f in fields}

    def fetch(group):
        raw = yf.download(group, start=start, end=end, auto_adjust=False, actions=True,
                          group_by="column", progress=False, threads=False)
        if raw is None or raw.empty:
            return None
        raw.index = pd.to_datetime(raw.index).tz_localize(None)
        if not isinstance(raw.columns, pd.MultiIndex):  # single ticker, flat columns
            raw.columns = pd.MultiIndex.from_product([raw.columns, group])
        return raw

    def add(raw, group):
        lvl0 = raw.columns.get_level_values(0)
        for f in fields:
            df = raw[f] if f in lvl0 else pd.DataFrame(np.nan, index=raw.index, columns=group)
            parts[f].append(df.reindex(columns=group))

    for i in range(0, len(tickers), batch):
        group = tickers[i:i + batch]
        raw = _retry(lambda: fetch(group), ok=lambda r: r is not None, what=f"batch {group[0]}..")
        if raw is not None:
            add(raw, group)
        time.sleep(1.0)

    out = {f: (pd.concat(parts[f], axis=1) if parts[f] else pd.DataFrame()) for f in fields}
    out = {f: df.loc[:, ~df.columns.duplicated()].reindex(columns=tickers) for f, df in out.items()}
    for t in [t for t in tickers if out["Close"][t].notna().sum() == 0]:
        log.info("Retrying %s on its own...", t)
        raw = _retry(lambda: fetch([t]), ok=lambda r: r is not None and r["Close"].notna().any().any(),
                     what=t)
        if raw is not None:
            idx = out["Close"].index.union(raw.index)
            for f in fields:
                out[f] = out[f].reindex(idx)
                if f in raw.columns.get_level_values(0):
                    out[f][t] = raw[f][t].reindex(idx)
        time.sleep(1.0)
    return out


def _shares_history(tickers, index, splits: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Best-effort shares outstanding on the same split-adjusted basis as Yahoo's `Close`,
    plus a provenance code per date: point-in-time where a reported count exists, otherwise
    back-filled or today's count (both look-ahead, and flagged as such in the report)."""
    import yfinance as yf

    def current_count(tk):
        return float(tk.fast_info["shares"])

    def history(tk):
        h = tk.get_shares_full(start=index[0].strftime("%Y-%m-%d"))
        return h if h is not None and len(h) else None

    out, src = {}, {}
    for t in tickers:
        tk = yf.Ticker(t)
        current = _retry(lambda: current_count(tk), ok=lambda x: x and x > 0, what=f"{t} shares", attempts=3)
        hist = _retry(lambda: history(tk), ok=lambda h: h is not None, what=f"{t} share history", attempts=3)
        series = None
        if hist is not None:
            hist.index = pd.to_datetime(hist.index).tz_localize(None).normalize()
            hist = hist[~hist.index.duplicated(keep="last")].sort_index()
            series = hist.reindex(index, method="ffill")
            if t in splits:
                series = series * split_factor_after(splits[[t]])[t].reindex(index).fillna(1.0)
            if current and (series.dropna() / current).between(0.33, 3).mean() < 0.8:
                series = None  # inconsistent history: don't trust it
        if series is None:
            out[t] = pd.Series(current if current else np.nan, index=index)
            src[t] = pd.Series(CURRENT, index=index)
        else:
            out[t] = series
            src[t] = pd.Series(np.where(series.notna(), PIT, BACKFILLED), index=index)
        time.sleep(0.3)
    return pd.DataFrame(out, index=index).ffill().bfill(), pd.DataFrame(src, index=index)


def load_market_data(cfg: IndexConfig, refresh: bool = False) -> MarketData:
    if cfg.source == "synthetic":
        return make_synthetic(cfg)
    if cfg.source == "yahoo":
        return load_yahoo(cfg, refresh=refresh)
    raise ValueError(f"unknown data source {cfg.source!r}")
