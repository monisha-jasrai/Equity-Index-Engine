"""End-to-end run: data -> backtests -> analytics -> attribution -> reports."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
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
        config_path: str | None = None, argv: list[str] | None = None,
        readme_path: str | Path | None = None) -> dict:
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

    costs = cost_sensitivity(main, cfg)
    drift = cap_drift(main, md, cfg)

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
    costs.to_csv(out / "cost_sensitivity.csv")

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
                               bridge, robust, has_tri, boot_tr, costs, drift)
    (out / "report.md").write_text(md_text)
    summary = {"config": cfg.name, "source": md.source, "start": str(idx[0].date()),
               "end": str(idx[-1].date()), "rebalances": len(main.rebalances),
               "stats": stats, "bootstrap": boot,
               "attribution_totals": attr["totals"]["value"].to_dict(),
               "weighting_basis": md.weighting_basis, "is_free_float": md.is_free_float,
               "checks_passed": log_data["checks_passed"],
               "rules_bridge": bridge[["value", "ci_low", "ci_high"]].to_dict(orient="index"),
               "period_robustness": {k: v for k, v in robust.items() if k != "by_year"},
               "bootstrap_net_vs_tri": boot_tr,
               "cost_sensitivity": costs.to_dict(orient="index"),
               "cap_drift": drift,
               "n_candidates": len(cfg.universe), "n_with_data": len(md.tickers)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    if md.source == "yahoo" and readme_path is not None:
        update_readme(Path(readme_path), summary, out)
    return {"md": md, "main": main, "variants": variants, "parent": parent, "stats": stats,
            "attribution": attr, "summary": summary, "checks": checks, "provenance": prov}


def cost_sensitivity(res: BacktestResult, cfg: IndexConfig, bps_list=(10, 25, 50)) -> pd.DataFrame:
    """Rebuild the NET series at several cost levels from the same trades.

    Convention: at each rebalance the cost is bps × Σ|w_new − w_drifted|, i.e. charged on the
    total notional traded (buys + sells). One-way turnover is half of that sum."""
    tr = res.levels["TR"]
    traded = pd.Series({r.date: 2 * r.one_way_turnover for r in res.rebalances[1:]})
    years = len(tr) / cfg.periods_per_year
    tr_cagr = (tr.iloc[-1] / tr.iloc[0]) ** (1 / years) - 1
    rows = {}
    for bps in sorted(set(bps_list) | {cfg.transaction_cost_bps}):
        factor = float((1 - traded * bps / 1e4).prod())
        net_cagr = (tr.iloc[-1] * factor / tr.iloc[0]) ** (1 / years) - 1
        rows[f"{bps:g} bps"] = {"net_cagr": net_cagr, "drag_vs_tr": tr_cagr - net_cagr}
    out = pd.DataFrame(rows).T
    out.attrs["avg_one_way_turnover"] = float(traded.mean() / 2) if len(traded) else 0.0
    out.attrs["rebalances_per_year"] = len(traded) / years
    return out


def cap_drift(res: BacktestResult, md: MarketData, cfg: IndexConfig) -> dict:
    """Caps apply at each rebalance; between rebalances weights drift with prices.
    Measure how far the largest stock and sector weights drift before the next rebalance."""
    pre_stock, pre_sector = [], []
    w = res.weights
    for r in res.rebalances[1:]:
        pos = w.index.get_loc(r.date)
        if pos == 0:
            continue
        before = w.iloc[pos - 1]
        pre_stock.append(float(before.max()))
        pre_sector.append(float(before.groupby(md.sectors.reindex(before.index)).sum().max()))
    last = w.iloc[-1]
    return {
        "stock_cap": cfg.single_stock_cap, "sector_cap": cfg.sector_cap,
        "max_stock_at_rebalance": float(max(r.target_weights.max() for r in res.rebalances)),
        "avg_max_stock_before_rebalance": float(np.mean(pre_stock)) if pre_stock else float("nan"),
        "max_stock_before_rebalance": float(np.max(pre_stock)) if pre_stock else float("nan"),
        "quarters_stock_above_cap": int(sum(x > cfg.single_stock_cap + 1e-9 for x in pre_stock)),
        "max_sector_before_rebalance": float(np.max(pre_sector)) if pre_sector else float("nan"),
        "n_periods": len(pre_stock),
        "latest_max_stock": float(last.max()),
        "latest_max_stock_name": str(last.idxmax()).replace(".NS", ""),
    }


RESULTS_START = "<!-- RESULTS:START (written automatically by `python -m index_engine --source yahoo`) -->"
RESULTS_END = "<!-- RESULTS:END -->"


def readme_results_block(summary: dict, out: Path) -> str:
    st = summary["stats"]
    ip, bp = st["Index PR"], st["Benchmark PR"]
    boot = summary["bootstrap"]
    br = summary["rules_bridge"]
    tot = next(v for k, v in br.items() if k.startswith("Total"))
    steps = {k: v for k, v in br.items() if k not in ("NIFTY 50", "Index") and not k.startswith("Total")}
    sig = lambda v: "significant" if v["ci_low"] > 0 or v["ci_high"] < 0 else "not significant"
    costs = summary["cost_sensitivity"]
    rel = out.as_posix()
    rows = [("CAGR", "cagr", "pct"), ("Annualised volatility", "volatility", "pct"),
            ("Sharpe ratio", "sharpe", "num"), ("Maximum drawdown", "max_drawdown", "pct")]
    f = lambda v, k: f"{v:.2%}" if k == "pct" else f"{v:.2f}"
    table = "| Metric (price return) | Index | NIFTY 50 |\n|---|---:|---:|\n" + "\n".join(
        f"| {lbl} | {f(ip[key], k)} | {f(bp[key], k)} |" for lbl, key, k in rows)
    table += (f"\n| Beta / tracking error vs NIFTY 50 | {ip['beta']:.2f} / {ip['tracking_error']:.2%} | – |")
    bridge_txt = "; ".join(f"{k.lower()} {v['value']:+.2%} ({sig(v)})" for k, v in steps.items())
    cost_txt = ", ".join(f"{k}: {v['net_cagr']:.2%}" for k, v in costs.items())
    return f"""{RESULTS_START}

### Headline results

Real NSE data (Yahoo Finance), {summary['start']} → {summary['end']}. A 40-stock index selected from a fixed list of {summary['n_candidates']} current large caps ({summary['n_with_data']} with data), weighted on **{summary['weighting_basis']}**, with 10% stock and 35% sector caps. Like-for-like: index **price return** vs NIFTY 50 **price return**.

{table}

**Interpretation.** The index's CAGR was {abs(tot['value']) * 100:.2f} percentage points a year {"higher" if tot['value'] >= 0 else "lower"} than the NIFTY 50's, with {"lower" if ip['volatility'] < bp['volatility'] else "higher"} realised volatility. The block-bootstrap 95% interval for the gap is [{tot['ci_low']:.2%}, {tot['ci_high']:.2%}], which {"excludes" if tot['ci_low'] > 0 or tot['ci_high'] < 0 else "includes"} zero: the data are consistent with anything from {"modest" if tot['ci_low'] > -0.02 else "meaningful"} underperformance to meaningful outperformance, so the result is **{"statistically conclusive" if tot['ci_low'] > 0 or tot['ci_high'] < 0 else "not statistically conclusive"}**. Splitting the gap by rule: {bridge_txt}. The universe-choice step reflects the fixed list of today's large caps, so it likely includes survivorship bias. None of this is evidence of a repeatable edge.

Total return is {"compared with the NIFTY 50 TRI in the report" if summary.get("bootstrap_net_vs_tri") else "**not** benchmarked here (no NIFTY 50 TRI supplied); the index's TR of " + f"{st['Index TR']['cagr']:.2%}" + " must not be compared with the NIFTY's price return"}. Net-of-cost CAGR by cost assumption: {cost_txt}. Validation: {summary['checks_passed']} run-time checks passed.

Full report: [`{rel}/report.md`]({rel}/report.md)

{RESULTS_END}"""


def update_readme(readme: Path, summary: dict, out: Path) -> bool:
    """Replace the results block in the README so the front page always matches the latest
    real-data run. Does nothing if the README or its markers are missing."""
    if not readme.exists():
        return False
    text = readme.read_text()
    if RESULTS_START not in text or RESULTS_END not in text:
        return False
    try:
        rel_out = out.resolve().relative_to(readme.resolve().parent)
    except ValueError:
        return False
    head, rest = text.split(RESULTS_START, 1)
    _, tail = rest.split(RESULTS_END, 1)
    readme.write_text(head + readme_results_block(summary, rel_out) + tail)
    log.info("README results block updated from this run")
    return True


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
        f"difference is {'statistically distinguishable from zero' if significant(tot) else '**not** statistically distinguishable from zero'}"
        + ("." if significant(tot) else ": the data are consistent with anything from underperformance to "
           "meaningful outperformance, so the result is not statistically conclusive."),
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
                     bridge, robust, has_tri, boot_tr, costs, drift) -> str:
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
    pr_table = rp.metrics_table({"Index PR": stats["Index PR"], "NIFTY 50 PR": stats["Benchmark PR"]})
    tr_cols = {"Index TR (gross)": stats["Index TR"], "Index NET (after costs)": stats["Index NET"]}
    if has_tri:
        tr_cols["NIFTY 50 TRI"] = stats["Benchmark TRI"]
    tr_table = rp.metrics_table(tr_cols)
    cost_md = rp.df_to_md(costs.rename(columns={"net_cagr": "NET CAGR", "drag_vs_tr": "Drag vs gross TR"}),
                          pct_cols=("NET CAGR", "Drag vs gross TR"), index_name="Cost assumption")
    drift_txt = (
        f"Caps apply **at each rebalance**: the largest target weight is {drift['max_stock_at_rebalance']:.2%} "
        f"(cap {drift['stock_cap']:.0%}). Between rebalances, index shares are fixed, so weights drift with prices. "
        f"Just before the next rebalance, the largest stock weight averaged {drift['avg_max_stock_before_rebalance']:.2%} "
        f"(peak {drift['max_stock_before_rebalance']:.2%}) and exceeded the cap in {drift['quarters_stock_above_cap']} of "
        f"{drift['n_periods']} periods; the largest sector reached {drift['max_sector_before_rebalance']:.2%} "
        f"(cap {drift['sector_cap']:.0%}). Each rebalance resets weights to within the caps. Today the largest weight is "
        f"{drift['latest_max_stock_name']} at {drift['latest_max_stock']:.2%}, which is drift since the last rebalance, "
        f"not a capping failure.")
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

Comparisons are strictly like-for-like, so price return and total return are shown in **separate tables**.

**Price return vs price return** (the headline comparison):

{pr_table}

**Total return** (dividends reinvested; NET after transaction costs){" vs the NIFTY 50 TRI" if has_tri else ""}:

{tr_table}

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

## Sector exposure and attribution (vs the parent universe, not the NIFTY 50)

This section uses a **different benchmark** from the rest of the report. Brinson-Fachler needs the benchmark's stock weights at every rebalance, which are not available for the NIFTY 50, so the index is compared with its **parent universe**: all eligible candidates, uncapped market-cap weights. It therefore measures the effect of the index's own rules (top-40 cut and caps) by sector. A negative result here is not inconsistent with outperforming the NIFTY 50; the rules bridge above links the two benchmarks. Computed per holding period and Carino-linked.
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

## Rebalancing and costs

![turnover](charts/{charts['turnover']})

**Cost convention.** At each rebalance the cost is (cost in bps) × Σ|new weight − drifted weight|, i.e. charged on the total notional traded, buys plus sells. One-way turnover is half that sum: {costs.attrs['avg_one_way_turnover']:.2%} per rebalance on average, {costs.attrs['rebalances_per_year']:.1f} rebalances a year. The base case is {cfg.transaction_cost_bps:g} bps.

**Sensitivity of the net return to the cost assumption:**

{cost_md}

**Cap drift between rebalances.** {drift_txt}

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
