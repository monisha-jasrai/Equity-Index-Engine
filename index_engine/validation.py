"""Run-time validation and data provenance.

Unit tests prove the engine's logic on controlled inputs. These checks run on every real
backtest and reconcile the *actual* outputs, so a data problem shows up in the report
instead of silently changing the results.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import IndexConfig
from .data import BACKFILLED, CURRENT, PIT, SHAREHOLDING, SYNTHETIC, MarketData
from .engine import BacktestResult


@dataclass
class Check:
    name: str
    measured: float
    tolerance: float
    passed: bool
    detail: str


def _check(name, measured, tol, detail, higher_is_bad=True) -> Check:
    ok = (measured <= tol) if higher_is_bad else (measured >= tol)
    return Check(name, float(measured), float(tol), bool(ok), detail)


def run_checks(res: BacktestResult, md: MarketData, cfg: IndexConfig, attr: dict) -> list[Check]:
    checks: list[Check] = []
    prices = md.prices.ffill()
    rebs = res.rebalances

    # 1. weights sum to 100%, daily and at every rebalance
    daily_err = float((res.weights.sum(axis=1) - 1).abs().max())
    reb_err = max(abs(r.target_weights.sum() - 1) for r in rebs)
    checks.append(_check("Weights sum to 100%", max(daily_err, reb_err), 1e-9,
                         f"max abs(Σw − 1) over {len(res.weights):,} days and {len(rebs)} rebalances"))

    # 2. caps
    if res.scheme == "capped_market_cap":
        max_w = max(r.target_weights.max() for r in rebs)
        max_s = max(r.target_weights.groupby(md.sectors[r.constituents]).sum().max() for r in rebs)
        checks.append(_check("Single-stock cap respected", max_w - cfg.single_stock_cap, 1e-9,
                             f"largest target weight {max_w:.4%} vs cap {cfg.single_stock_cap:.0%}"))
        checks.append(_check("Sector cap respected", max_s - cfg.sector_cap, 1e-9,
                             f"largest sector target {max_s:.4%} vs cap {cfg.sector_cap:.0%}"))

    # 3. divisor continuity
    errs = []
    for r in rebs[1:]:
        lvl_new = float((r.index_shares * prices.loc[r.date, r.constituents]).sum() / r.divisor_after)
        errs.append(abs(lvl_new / r.level - 1))
    checks.append(_check("Divisor keeps level continuous", max(errs) if errs else 0.0, 1e-10,
                         "max relative gap between old-basket and new-basket level at each rebalance"))

    # 4. dividends: TR − PR daily return must equal Σ q·D / Σ q·P(t−1), rebuilt independently
    D = md.dividends
    diffs, div_ret = [], []
    lv = res.levels
    reb_dates = [r.date for r in rebs] + [lv.index[-1]]
    for k, r in enumerate(rebs):
        seg = lv.loc[r.date:reb_dates[k + 1]]
        if len(seg) < 2:
            continue
        q = r.index_shares
        p = prices.loc[seg.index, q.index]
        mv_prev = (p.shift(1) * q).sum(axis=1).iloc[1:]
        dret = (D.loc[seg.index, q.index] * q).sum(axis=1).iloc[1:] / mv_prev
        pr = seg["PR"].pct_change().iloc[1:]
        tr = seg["TR"].pct_change().iloc[1:]
        diffs.append(((tr - pr) - dret).abs().max())
        div_ret.append(dret)
    div_ret = pd.concat(div_ret)
    ann_div = float(div_ret.sum() / (len(lv) / cfg.periods_per_year))
    checks.append(_check("Dividends reconcile (TR − PR)", max(diffs), 1e-12,
                         f"max daily gap vs dividends rebuilt from holdings; dividend yield ≈ {ann_div:.2%}/yr"))

    # 5. transaction costs: NET/TR at the end must equal Π(1 − cost) over rebalances
    expected = float(np.prod([1 - r.cost for r in rebs]))
    actual = float(lv["NET"].iloc[-1] / lv["TR"].iloc[-1])
    total_cost = 1 - expected
    checks.append(_check("Costs reconcile (NET vs TR)", abs(actual / expected - 1), 1e-10,
                         f"cumulative cost drag {total_cost:.3%} from {len(rebs) - 1} rebalances"))

    # 6. attribution adds up
    t = attr["totals"]["value"]
    pr_total = float(lv["PR"].iloc[-1] / lv["PR"].iloc[0] - 1)
    checks.append(_check("Attribution sums to active return", abs(t["residual"]), 1e-10,
                         f"allocation + selection + interaction − active = {t['residual']:.1e}"))
    checks.append(_check("Attribution index return = PR level", abs(t["index_return"] - pr_total), 1e-9,
                         f"{t['index_return']:.4%} vs {pr_total:.4%}"))

    # 7. no look-ahead in selection
    lag = min((md.prices.index.get_loc(r.date) - md.prices.index.get_loc(r.ref_date)) for r in rebs)
    checks.append(_check("Selection uses lagged data", lag, cfg.reference_lag_days,
                         f"minimum lag {lag} trading days (required ≥ {cfg.reference_lag_days})",
                         higher_is_bad=False))
    return checks


def provenance(res: BacktestResult, md: MarketData, cfg: IndexConfig) -> dict:
    """How much of the index weight, at each rebalance, rests on point-in-time inputs."""
    rows = []
    for r in res.rebalances:
        w = r.target_weights
        src = md.shares_source.loc[r.ref_date, w.index]
        known = md.iwf_known.loc[r.ref_date, w.index]
        rows.append({
            "pit_shares": float(w[src.isin([PIT, SHAREHOLDING, SYNTHETIC])].sum()),
            "backfilled_shares": float(w[src == BACKFILLED].sum()),
            "current_shares": float(w[src == CURRENT].sum()),
            "iwf_known": float(w[known].sum()),
        })
    df = pd.DataFrame(rows)
    excluded = [t for t in cfg.universe if t not in md.tickers]
    return {
        "shares_point_in_time_weight": float(df["pit_shares"].mean()),
        "shares_backfilled_weight": float(df["backfilled_shares"].mean()),
        "shares_current_fallback_weight": float(df["current_shares"].mean()),
        "iwf_known_weight": float(df["iwf_known"].mean()),
        "iwf_source": md.iwf_source,
        "weighting_basis": md.weighting_basis,
        "is_free_float": md.is_free_float,
        "universe": "fixed candidate list of current large caps (not historical index membership)",
        "n_candidates_with_data": len(md.tickers),
        "prices_volumes": "daily, point-in-time (split-adjusted closes)",
        "excluded_no_data": excluded,
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def run_log(cfg: IndexConfig, md: MarketData, res: BacktestResult, checks: list[Check],
            prov: dict, config_path: str | None, argv: list[str] | None) -> dict:
    import matplotlib
    import yaml

    versions = {"python": platform.python_version(), "numpy": np.__version__,
                "pandas": pd.__version__, "matplotlib": matplotlib.__version__, "pyyaml": yaml.__version__}
    try:
        import yfinance
        versions["yfinance"] = yfinance.__version__
    except Exception:  # noqa: BLE001
        pass
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        commit = None
    data_files = {}
    if md.source == "yahoo":
        for f in sorted(Path(cfg.cache_dir).glob("*.csv")):
            data_files[f.name] = _sha256(f)
        if cfg.shareholding_file and Path(cfg.shareholding_file).exists():
            data_files[Path(cfg.shareholding_file).name] = _sha256(Path(cfg.shareholding_file))
    return {
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": " ".join(argv) if argv else None,
        "git_commit": commit,
        "platform": platform.platform(),
        "versions": versions,
        "config_file": config_path,
        "config_sha256": _sha256(Path(config_path)) if config_path and Path(config_path).exists() else None,
        "config": {k: v for k, v in asdict(cfg).items() if k != "universe"},
        "data_source": md.source,
        "data_files_sha256": data_files,
        "period": [str(res.levels.index[0].date()), str(res.levels.index[-1].date())],
        "rebalances": len(res.rebalances),
        "provenance": prov,
        "checks_passed": f"{sum(c.passed for c in checks)}/{len(checks)}",
        "checks": [asdict(c) for c in checks],
    }


def write_run_log(log: dict, path: Path) -> None:
    path.write_text(json.dumps(log, indent=2, default=str))
