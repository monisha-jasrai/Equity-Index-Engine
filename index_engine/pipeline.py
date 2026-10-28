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
from .validation import provenance, run_checks, run_log, write_run_log

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


def run(cfg: IndexConfig, out_dir: str | Path, refresh: bool = False,
        config_path: str | None = None, argv: list[str] | None = None) -> dict:
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
    tri_lvl = md.benchmark_tri.reindex(idx).ffill() if md.benchmark_tri is not None else None
    has_tri = tri_lvl is not None and tri_lvl.notna().mean() > 0.95
    bt = tri_lvl.pct_change().dropna() if has_tri else None

    # Like-for-like only: index PR vs benchmark PR; index TR/NET vs benchmark TRI (if supplied).
    stats = {
        "Index PR": an.summary(r["PR"], rf, ppy, bench=b),
        "Benchmark PR": an.summary(b, rf, ppy),
        "Index TR": an.summary(r["TR"], rf, ppy, bench=bt) if has_tri else an.summary(r["TR"], rf, ppy),
        "Index NET": an.summary(r["NET"], rf, ppy, bench=bt) if has_tri else an.summary(r["NET"], rf, ppy),
    }
    if has_tri:
        stats["Benchmark TRI"] = an.summary(bt, rf, ppy)
    boot = an.block_bootstrap_active(r["PR"], b, cfg.bootstrap_samples, cfg.bootstrap_block_days, ppy)
    boot_tr = (an.block_bootstrap_active(r["NET"], bt, cfg.bootstrap_samples, cfg.bootstrap_block_days, ppy)
               if has_tri else None)
    roll = an.rolling_relative(r["PR"], b, cfg.rolling_window_days, ppy)
    cal_cols = [main.levels, bench_lvl.rename("Benchmark PR")]
    if has_tri:
        cal_cols.append(tri_lvl.rename("Benchmark TRI"))
    cal = an.calendar_returns(pd.concat(cal_cols, axis=1))
    cal["Active (PR − PR)"] = cal["PR"] - cal["Benchmark PR"]
    if has_tri:
        cal["Active (NET − TRI)"] = cal["NET"] - cal["Benchmark TRI"]
    dd = an.max_drawdown_details(r["PR"])

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

    uncapped = variants.get("market_cap") or run_backtest(md, cfg, scheme="market_cap")
    bridge = rules_bridge(b, parent.returns["PR"], uncapped.returns["PR"], r["PR"], cfg)
    robust = period_robustness(r["PR"], b, ppy)

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
    lv_out = main.levels.join(bench_lvl.rename("Benchmark PR"))
    if has_tri:
        lv_out = lv_out.join(tri_lvl.rename("Benchmark TRI"))
    lv_out.join(main.divisor).to_csv(out / "index_levels.csv")
    rt.to_csv(out / "rebalance_log.csv")
    holdings.to_csv(out / "current_constituents.csv")
    attr["periods"].to_csv(out / "attribution_by_period.csv", index=False)
    var_table.to_csv(out / "variant_comparison.csv")
    bridge.to_csv(out / "rules_bridge.csv")

    basis = ("free-float market cap" if md.is_free_float else "full market cap (IWF = 1)")
    universe_note = "simulated market" if md.source == "synthetic" else "fixed candidate universe"
    subtitle = f"Capped market-cap weighted · {basis} · {universe_note}"
    charts = {
        "growth": rp.chart_growth(main.levels["PR"], bench_lvl, "Index (price return)",
                                  "NIFTY 50 (price return)",
                                  "Growth of 1,000: price return vs price return (log scale)",
                                  subtitle, out / "charts", "growth.png"),
        "drawdown": rp.chart_drawdown(r["PR"], b, "Index (price return)", "NIFTY 50 (price return)",
                                      out / "charts"),
        "bridge": rp.chart_bridge(bridge, out / "charts"),
        "rolling": rp.chart_rolling(roll, cfg.rolling_window_days, out / "charts"),
        "sectors": rp.chart_sector_weights(sector_w, out / "charts"),
        "turnover": rp.chart_turnover(rt, out / "charts"),
        "variants": rp.chart_variants(var_table, out / "charts"),
        "attribution": rp.chart_attribution(attr["by_sector"], out / "charts"),
    }
    if has_tri:
        charts["growth_tr"] = rp.chart_growth(main.levels["NET"], tri_lvl, "Index (total return, net of costs)",
                                              "NIFTY 50 TRI (total return)",
                                              "Growth of 1,000: total return vs total return (log scale)",
                                              subtitle, out / "charts", "growth_tr.png")

    checks = run_checks(main, md, cfg, attr)
    prov = provenance(main, md, cfg)
    log_data = run_log(cfg, md, main, checks, prov, config_path, argv)
    write_run_log(log_data, out / "run_log.json")
    failed = [c.name for c in checks if not c.passed]
    if failed:
        log.warning("Validation checks FAILED: %s", failed)

    md_text = _render_markdown(cfg, md, main, stats, boot, dd, cal, var_table, attr, contrib,
                               holdings, rt, charts, checks, prov, log_data,
                               bridge, robust, has_tri, boot_tr)
    (out / "report.md").write_text(md_text)
    summary = {"config": cfg.name, "source": md.source, "start": str(idx[0].date()),
               "end": str(idx[-1].date()), "rebalances": len(main.rebalances),
               "stats": stats, "bootstrap": boot,
               "attribution_totals": attr["totals"]["value"].to_dict(),
               "weighting_basis": md.weighting_basis, "is_free_float": md.is_free_float,
               "checks_passed": log_data["checks_passed"],
               "rules_bridge": bridge[["value", "ci_low", "ci_high"]].to_dict(orient="index"),
               "period_robustness": {k: v for k, v in robust.items() if k != "by_year"},
               "bootstrap_net_vs_tri": boot_tr}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    return {"md": md, "main": main, "variants": variants, "parent": parent, "stats": stats,
            "attribution": attr, "summary": summary, "checks": checks, "provenance": prov}


def rules_bridge(nifty: pd.Series, parent: pd.Series, uncapped: pd.Series, capped: pd.Series,
                 cfg: IndexConfig) -> pd.DataFrame:
    """Split the index-vs-NIFTY gap (price return, CAGR) into the effect of each rule.

    NIFTY 50 -> parent universe (all eligible candidates, uncapped): universe choice
    parent -> top-40 uncapped: the top-40 cut (with buffer)
    top-40 uncapped -> top-40 capped: the 10% stock / 35% sector caps
    The steps are differences of CAGRs, so they sum exactly to the total gap.
    """
    ppy = cfg.periods_per_year
    al = pd.concat([nifty, parent, uncapped, capped], axis=1, join="inner").dropna()
    al.columns = ["nifty", "parent", "uncapped", "capped"]
    c = {k: an.cagr(al[k], ppy) for k in al.columns}
    steps = [("Universe choice", "parent", "nifty"), ("Top-40 cut", "uncapped", "parent"),
             ("Stock & sector caps", "capped", "uncapped")]
    rows = [{"step": "NIFTY 50", "kind": "level", "value": c["nifty"]}]
    for name, a, bb in steps:
        bs = an.block_bootstrap_active(al[a], al[bb], cfg.bootstrap_samples, cfg.bootstrap_block_days, ppy)
        # bootstrap is on mean active return; shift its interval onto the CAGR-difference scale
        shift = (c[a] - c[bb]) - bs["active_mean_annual"]
        rows.append({"step": name, "kind": "step", "value": c[a] - c[bb],
                     "ci_low": bs["ci_95_low"] + shift, "ci_high": bs["ci_95_high"] + shift,
                     "p_positive": bs["p_active_positive"]})
    bs = an.block_bootstrap_active(al["capped"], al["nifty"], cfg.bootstrap_samples,
                                   cfg.bootstrap_block_days, ppy)
    shift = (c["capped"] - c["nifty"]) - bs["active_mean_annual"]
    rows.append({"step": "Total gap (index − NIFTY)", "kind": "total", "value": c["capped"] - c["nifty"],
                 "ci_low": bs["ci_95_low"] + shift, "ci_high": bs["ci_95_high"] + shift,
                 "p_positive": bs["p_active_positive"]})
    rows.append({"step": "Index", "kind": "level", "value": c["capped"]})
    return pd.DataFrame(rows).set_index("step")


def period_robustness(r: pd.Series, b: pd.Series, ppy: int) -> dict:
    """Is the active return broad-based or driven by one period?"""
    r, b = r.align(b, join="inner")
    yr_r = (1 + r).groupby(r.index.year).prod() - 1
    yr_b = (1 + b).groupby(b.index.year).prod() - 1
    act = yr_r - yr_b
    best = int(act.idxmax())
    worst = int(act.idxmin())
    keep = r.index.year != best
    ex_best = an.cagr(r[keep], ppy) - an.cagr(b[keep], ppy)
    return {"by_year": act, "years_positive": int((act > 0).sum()), "n_years": int(len(act)),
            "best_year": best, "best_active": float(act[best]),
            "worst_year": worst, "worst_active": float(act[worst]),
            "active_ex_best_year": float(ex_best),
            "total_active": float(an.cagr(r, ppy) - an.cagr(b, ppy))}


def _interpretation(bridge: pd.DataFrame, robust: dict, boot: dict, attr: dict) -> str:
    steps = bridge[bridge["kind"] == "step"]
    tot = bridge[bridge["kind"] == "total"].iloc[0]
    significant = lambda row: row["ci_low"] > 0 or row["ci_high"] < 0
    sig_txt = lambda row: "significant" if significant(row) else "not significant"
    biggest = steps["value"].abs().idxmax()
    uni = steps.loc["Universe choice"]
    lines = [
        f"- **Size of the gap.** Price return vs price return, the index's CAGR differs from the NIFTY 50's by "
        f"**{tot['value']:+.2%} a year** (95% interval [{tot['ci_low']:.2%}, {tot['ci_high']:.2%}]), so the "
        f"difference is {'statistically distinguishable from zero' if significant(tot) else '**not** statistically distinguishable from zero'}.",
        "- **Which rule drives it.** " + "; ".join(
            f"{name} {row['value']:+.2%} ({sig_txt(row)})" for name, row in steps.iterrows())
        + f". The largest single effect is **{biggest.lower()}**.",
        f"- **Universe choice is where survivorship bias shows up.** That step compares an index of all "
        f"candidates with the real NIFTY 50. The candidates are today's large caps, so they include companies "
        f"that grew into the list and exclude ones that fell out of it. Treat the {uni['value']:+.2%} as likely overstated, "
        f"partly an artefact of the fixed candidate list rather than of the index rules.",
    ]
    t = attr["totals"]["value"]
    lines.append(
        f"- **Sector view of the rules.** Against the parent universe, Brinson-Fachler splits the cumulative "
        f"(not annual) effect of the top-40 cut and caps into allocation {t['allocation']:+.2%}, selection "
        f"{t['selection']:+.2%} and interaction {t['interaction']:+.2%} (see the attribution section).")
    lines.append(
        f"- **Is it broad-based?** The index beat the NIFTY in {robust['years_positive']} of "
        f"{robust['n_years']} calendar years. The best year ({robust['best_year']}, {robust['best_active']:+.2%}) "
        f"matters: excluding it, the annual gap is {robust['active_ex_best_year']:+.2%}. "
        f"Worst year: {robust['worst_year']} ({robust['worst_active']:+.2%}).")
    lines.append(
        "- **What this does not show.** A backtest over one ten-year window, on a fixed list of today's "
        "large caps, cannot establish a repeatable edge. Read the gap as a description of how these rules "
        "behaved in this period, not as evidence that they will outperform.")
    return "\n".join(lines)


def _render_markdown(cfg, md, main, stats, boot, dd, cal, var_table, attr, contrib,
                     holdings, rt, charts, checks, prov, log_data,
                     bridge, robust, has_tri, boot_tr) -> str:
    idx = main.levels.index
    if md.source == "synthetic":
        src_note = ("> **Data source: SYNTHETIC.** Simulated multi-factor market used to demonstrate and "
                    "test the engine. Run with `--source yahoo` for real NSE data.\n")
    else:
        src_note = ("> **Data source: Yahoo Finance (NSE).** Fixed-candidate-universe study weighted on "
                    f"**{md.weighting_basis}**. See *Data provenance and limitations* below.\n")
    kind = ("capped free-float market-cap weighted" if md.is_free_float
            else "capped market-cap weighted (free-float-ready framework)")
    totals = attr["totals"]["value"]
    contr = contrib["stocks"]
    top = contr.head(10)
    bot = contr.tail(5).iloc[::-1]
    fmt_ct = lambda d: rp.df_to_md(
        d.assign(contribution=d["contribution"], avg_weight=d["avg_weight"])
         [["sector", "contribution", "avg_weight", "days_in_index"]]
         .rename(index=lambda t: t.replace(".NS", "")),
        pct_cols=("contribution", "avg_weight"), index_name="Stock")
    cal_md = rp.df_to_md(cal, pct_cols=tuple(cal.columns), index_name="Year")
    bridge_md = rp.df_to_md(
        bridge.assign(ci=[f"[{lo:.2%}, {hi:.2%}]" if pd.notna(lo) else "" for lo, hi in
                          zip(bridge.get("ci_low"), bridge.get("ci_high"))])[["value", "ci"]]
        .rename(columns={"value": "CAGR / effect", "ci": "95% interval"}),
        pct_cols=("CAGR / effect",), index_name="Step")
    interp = _interpretation(bridge, robust, boot, attr)
    if has_tri:
        tr_note = (f"Total return is compared separately: **index NET (total return after costs) vs NIFTY 50 TRI**. "
                   f"Bootstrap active return {boot_tr['active_mean_annual']:.2%}, 95% interval "
                   f"[{boot_tr['ci_95_low']:.2%}, {boot_tr['ci_95_high']:.2%}].\n\n"
                   f"![growth_tr](charts/{charts['growth_tr']})")
    else:
        tr_note = ("**Total return is not compared with a benchmark** in this run: no NIFTY 50 Total Returns "
                   "Index was supplied, and comparing the index's TR with a price index would overstate it by "
                   "roughly the dividend yield. Set `data.benchmark_tri_file` to add a TR vs TRI comparison. "
                   "The index's TR and NET figures above are absolute numbers only.")
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
    checks_md = "| Check | Result | Detail |\n|---|---|---|\n" + "\n".join(
        f"| {c.name} | {'✅ pass' if c.passed else '❌ FAIL'} | {c.detail} |" for c in checks)
    excluded = ", ".join(t.replace(".NS", "") for t in prov["excluded_no_data"]) or "none"
    ff_note = ("IWF = 1 − promoter holding from the shareholding file, applied "
               f"{cfg.shareholding_lag_days} days after each quarter-end; NSE also excludes some other "
               "locked-in holdings, so this approximates the official factor."
               if md.iwf_source == "shareholding_file" else
               "Simulated IWFs." if md.iwf_source == "synthetic" else
               "No historical free-float data was used (IWF = 1), so weights are on full market cap. "
               "The engine supports point-in-time IWFs via `data.shareholding_file`.")

    return f"""# {cfg.name} — Backtest Report

{src_note}
**Period:** {idx[0].date()} → {idx[-1].date()} · **Rebalances:** {len(main.rebalances)} ({cfg.frequency}) ·
**Index type:** {kind} · **Constituents:** {cfg.n_constituents} · **Weighting:** {cfg.scheme} on {md.weighting_basis} (stock cap {cfg.single_stock_cap:.0%}, sector cap {cfg.sector_cap:.0%}) ·
**Costs:** {cfg.transaction_cost_bps:.0f} bps per unit traded · **Risk-free:** {cfg.risk_free_rate:.1%}

![growth](charts/{charts['growth']})

## Performance and risk

{rp.metrics_table(stats)}

Comparisons are strictly like-for-like. The headline chart and the relative statistics in the **Index PR** column compare the index's **price return** with the NIFTY 50 **price return**.{" Relative statistics in the Index TR and NET columns are against the NIFTY 50 TRI." if has_tri else ""}

{tr_note}

**Is the active return statistically meaningful?** A moving-block bootstrap ({cfg.bootstrap_samples:,} resamples, {cfg.bootstrap_block_days}-day blocks) of daily PR − PR active returns puts the mean annualised active return at
{boot['active_mean_annual']:.2%} with a 95% interval of [{boot['ci_95_low']:.2%}, {boot['ci_95_high']:.2%}]; {boot['p_active_positive']:.0%} of resamples are positive. (This arithmetic mean differs slightly from the CAGR gap because the two series have different volatility.)

**Worst drawdown (price return):** {dd['max_drawdown']:.1%}, peak {dd['peak'].date()} → trough {dd['trough'].date()}, recovered {rec}.

![drawdown](charts/{charts['drawdown']})
![rolling](charts/{charts['rolling']})

## What drives the result

{interp}

![bridge](charts/{charts['bridge']})

{bridge_md}

## Calendar-year returns

Benchmark columns are the NIFTY 50 price index{" and TRI" if has_tri else ""}; the active columns compare like with like.

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

## Validation

Every run reconciles its own outputs; failures are logged and shown here. Unit tests (`pytest`) separately check the logic on controlled inputs.

{checks_md}

## Data provenance and limitations

| Input | Basis in this run |
|---|---|
| Universe | {prov['universe']} ({prov['n_candidates_with_data']} candidates with data) |
| Weighting basis | {prov['weighting_basis']} |
| Index weight resting on point-in-time share counts (avg. over rebalances) | {prov['shares_point_in_time_weight']:.1%} |
| … on back-filled share counts (look-ahead) | {prov['shares_backfilled_weight']:.1%} |
| … on today's share count used for past dates (look-ahead) | {prov['shares_current_fallback_weight']:.1%} |
| Index weight with a known (non-default) IWF | {prov['iwf_known_weight']:.1%} |
| Prices, volumes, liquidity screen | {prov['prices_volumes']} |
| Excluded (no data) | {excluded} |

Limitations:

- **Survivorship bias.** The candidates are today's large caps, so companies that were large in 2016 but later shrank or delisted are missing. Treat results as a fixed-candidate-universe study, not a reconstruction of a historical index.
- **Free float.** {ff_note}
- **Share counts.** Where a stock's weight rests on back-filled or current share counts (above), its historical weight uses information that was not available at the time.
- **Benchmark.** {"NIFTY 50 price index for PR comparisons and the supplied NIFTY 50 TRI for TR comparisons." if has_tri else "NIFTY 50 price index only; the index's total return is not benchmarked until a NIFTY 50 TRI file is supplied."}
- **Corporate actions.** Splits via split-adjusted prices; spin-offs and rights issues are not modelled.

Run log: `run_log.json` ({log_data['run_at_utc']}, checks passed {log_data['checks_passed']}, config hash `{log_data['config_sha256']}`).
"""
