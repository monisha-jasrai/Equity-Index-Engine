"""End-to-end run: data -> backtests -> analytics -> attribution -> reports."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from . import analytics as an
from . import report as rp
from .attribution import brinson_fachler, contributions
from .config import IndexConfig
from .data import MarketData, load_market_data
from .engine import BacktestResult, run_backtest

log = logging.getLogger(__name__)


def run_variants(md: MarketData, cfg: IndexConfig) -> dict[str, BacktestResult]:
    out = {}
    for v in dict.fromkeys((cfg.scheme, *cfg.variants)):
        out[v] = run_backtest(md, cfg, scheme=v)
    return out


def parent_universe(md: MarketData, cfg: IndexConfig) -> BacktestResult:
    """Uncapped float-cap index of *every* eligible name: the attribution benchmark."""
    n = len(md.tickers)
    pcfg = cfg.with_overrides(n_constituents=n, retain_rank=n, scheme="market_cap")
    return run_backtest(md, pcfg, scheme="market_cap", name="parent")


def run(cfg: IndexConfig, out_dir: str | Path, refresh: bool = False) -> dict:
    out = Path(out_dir)
    (out / "charts").mkdir(parents=True, exist_ok=True)
    md = load_market_data(cfg, refresh=refresh)
    ppy, rf = cfg.periods_per_year, cfg.risk_free_rate

    variants = run_variants(md, cfg)
    main = variants[cfg.scheme]
    parent = parent_universe(md, cfg)

    idx = main.levels.index
    bench_lvl = md.benchmark.reindex(idx).ffill()
    b = bench_lvl.pct_change().dropna()
    r = main.returns

    stats = {
        "Index PR": an.summary(r["PR"], rf, ppy, bench=b),
        "Index TR": an.summary(r["TR"], rf, ppy),
        "Index NET": an.summary(r["NET"], rf, ppy),
        "Benchmark PR": an.summary(b, rf, ppy),
    }
    boot = an.block_bootstrap_active(r["PR"], b, cfg.bootstrap_samples, cfg.bootstrap_block_days, ppy)
    roll = an.rolling_relative(r["PR"], b, cfg.rolling_window_days, ppy)
    cal = an.calendar_returns(pd.concat([main.levels, bench_lvl.rename("Benchmark")], axis=1))
    dd = an.max_drawdown_details(r["TR"])

    var_rows = {}
    for name, res in variants.items():
        s = an.summary(res.returns["PR"], rf, ppy, bench=b)
        rt = res.rebalance_table()
        var_rows[name] = {**{k: s[k] for k in ("cagr", "volatility", "sharpe", "max_drawdown",
                                                "tracking_error", "information_ratio", "beta")},
                          "avg_turnover": rt["one_way_turnover"].iloc[1:].mean(),
                          "avg_effective_n": rt["effective_n"].mean()}
    sb = an.summary(b, rf, ppy)
    var_rows["benchmark"] = {k: sb[k] for k in ("cagr", "volatility", "sharpe", "max_drawdown")}
    var_table = pd.DataFrame(var_rows).T

    attr = brinson_fachler(main, parent, md)
    contrib = contributions(main, md)
    rt = main.rebalance_table()
    last = main.rebalances[-1]
    holdings = pd.DataFrame({
        "sector": md.sectors[last.constituents],
        "target_weight": last.target_weights,
        "current_weight": main.weights.iloc[-1][last.constituents],
        "capping_factor": last.capping_factors,
        "index_shares": last.index_shares,
    }).sort_values("current_weight", ascending=False)
    holdings.index = holdings.index.str.replace(".NS", "", regex=False)
    sector_w = main.sector_weights(md.sectors)

    # ---- files
    main.levels.join(bench_lvl.rename("Benchmark")).join(main.divisor).to_csv(out / "index_levels.csv")
    rt.to_csv(out / "rebalance_log.csv")
    holdings.to_csv(out / "current_constituents.csv")
    attr["periods"].to_csv(out / "attribution_by_period.csv", index=False)
    var_table.to_csv(out / "variant_comparison.csv")

    charts = {
        "growth": rp.chart_growth(main.levels, bench_lvl, "Index", out / "charts"),
        "drawdown": rp.chart_drawdown(r["TR"], b, out / "charts"),
        "rolling": rp.chart_rolling(roll, cfg.rolling_window_days, out / "charts"),
        "sectors": rp.chart_sector_weights(sector_w, out / "charts"),
        "turnover": rp.chart_turnover(rt, out / "charts"),
        "variants": rp.chart_variants(var_table, out / "charts"),
        "attribution": rp.chart_attribution(attr["by_sector"], out / "charts"),
    }

    md_text = _render_markdown(cfg, md, main, stats, boot, dd, cal, var_table, attr, contrib,
                               holdings, rt, charts)
    (out / "report.md").write_text(md_text)
    summary = {"config": cfg.name, "source": md.source, "start": str(idx[0].date()),
               "end": str(idx[-1].date()), "rebalances": len(main.rebalances),
               "stats": stats, "bootstrap": boot,
               "attribution_totals": attr["totals"]["value"].to_dict()}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    return {"md": md, "main": main, "variants": variants, "parent": parent, "stats": stats,
            "attribution": attr, "summary": summary}


def _render_markdown(cfg, md, main, stats, boot, dd, cal, var_table, attr, contrib,
                     holdings, rt, charts) -> str:
    idx = main.levels.index
    src_note = ("> **Data source: SYNTHETIC.** Simulated multi-factor market used to demonstrate and "
                "test the engine. Run with `--source yahoo` for real NSE data.\n"
                if md.source == "synthetic" else
                "> **Data source: Yahoo Finance (NSE).** See README for data limitations "
                "(survivorship bias, free-float approximation).\n")
    totals = attr["totals"]["value"]
    contr = contrib["stocks"]
    top = contr.head(10)
    bot = contr.tail(5).iloc[::-1]
    fmt_ct = lambda d: rp.df_to_md(
        d.assign(contribution=d["contribution"], avg_weight=d["avg_weight"])
         [["sector", "contribution", "avg_weight", "days_in_index"]]
         .rename(index=lambda t: t.replace(".NS", "")),
        pct_cols=("contribution", "avg_weight"), index_name="Stock")
    cal_md = rp.df_to_md(cal[["PR", "TR", "NET", "Benchmark"]], pct_cols=("PR", "TR", "NET", "Benchmark"),
                         index_name="Year")
    var_md = rp.df_to_md(var_table, pct_cols=("cagr", "volatility", "max_drawdown", "tracking_error",
                                              "avg_turnover"),
                         num_cols=("sharpe", "information_ratio", "beta", "avg_effective_n"),
                         index_name="Scheme")
    attr_md = rp.df_to_md(attr["by_sector"], pct_cols=("allocation", "selection", "interaction", "total"),
                          index_name="Sector")
    hold_md = rp.df_to_md(holdings.head(15)[["sector", "target_weight", "current_weight", "capping_factor"]],
                          pct_cols=("target_weight", "current_weight"), num_cols=("capping_factor",),
                          index_name="Ticker")
    recent = rt.tail(6)[["n", "eligible", "adds", "dels", "additions", "deletions", "one_way_turnover",
                         "cost_bps", "divisor"]]
    reb_md = rp.df_to_md(recent, pct_cols=("one_way_turnover",), num_cols=("cost_bps", "divisor"),
                         index_name="Rebalance")
    rec = dd["recovery"].date() if dd["recovery"] is not None else "not yet recovered"

    return f"""# {cfg.name} — Backtest Report

{src_note}
**Period:** {idx[0].date()} → {idx[-1].date()} · **Rebalances:** {len(main.rebalances)} ({cfg.frequency}) ·
**Constituents:** {cfg.n_constituents} · **Weighting:** {cfg.scheme} (stock cap {cfg.single_stock_cap:.0%}, sector cap {cfg.sector_cap:.0%}) ·
**Costs:** {cfg.transaction_cost_bps:.0f} bps per unit traded · **Risk-free:** {cfg.risk_free_rate:.1%}

![growth](charts/{charts['growth']})

## Performance and risk

{rp.metrics_table(stats)}

Relative statistics compare the **price-return** index with the **price-return** benchmark, so dividends do not flatter the comparison.

**Is the active return statistically meaningful?** A moving-block bootstrap ({cfg.bootstrap_samples:,} resamples, {cfg.bootstrap_block_days}-day blocks) puts the annualised active return at
{boot['active_mean_annual']:.2%} with a 95% interval of [{boot['ci_95_low']:.2%}, {boot['ci_95_high']:.2%}]; {boot['p_active_positive']:.0%} of resamples are positive.

**Worst drawdown (TR):** {dd['max_drawdown']:.1%}, peak {dd['peak'].date()} → trough {dd['trough'].date()}, recovered {rec}.

![drawdown](charts/{charts['drawdown']})
![rolling](charts/{charts['rolling']})

## Calendar-year returns

{cal_md}

## Weighting-scheme comparison

Same universe, selection rules and rebalance calendar; only the weighting changes.

{var_md}

![variants](charts/{charts['variants']})

## Sector exposure and attribution

Brinson-Fachler attribution of the index against its **parent universe** (all eligible names, uncapped float-cap weights), per holding period, Carino-linked.
Index {totals['index_return']:.2%} vs parent {totals['benchmark_return']:.2%} → active {totals['active_return']:.2%} =
allocation {totals['allocation']:.2%} + selection {totals['selection']:.2%} + interaction {totals['interaction']:.2%} (residual {totals['residual']:.1e}).

{attr_md}

![attribution](charts/{charts['attribution']})
![sectors](charts/{charts['sectors']})

## Constituent contribution (price return, cumulative)

Top 10

{fmt_ct(top)}

Bottom 5

{fmt_ct(bot)}

## Rebalancing

![turnover](charts/{charts['turnover']})

Most recent rebalances (full log in `rebalance_log.csv`):

{reb_md}

Current top 15 holdings (full list in `current_constituents.csv`):

{hold_md}
"""
