"""Charts (PNG) and a Markdown tear sheet for a backtest run."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mtick  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# Validated categorical palette (fixed order, never cycled) + neutral inks.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER = "#b4b2a9"
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.titlecolor": INK,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
    "xtick.color": MUTED, "ytick.color": MUTED, "font.size": 9.5,
    "legend.frameon": False, "legend.labelcolor": INK2, "lines.linewidth": 1.6,
})


def _save(fig, path: Path) -> str:
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path.name


def _end_label(ax, s: pd.Series, text: str, color: str, dy: float = 0.0) -> None:
    ax.annotate(text, xy=(s.index[-1], s.iloc[-1]), xytext=(6, dy), textcoords="offset points",
                va="center", fontsize=8.5, color=INK2)
    ax.plot(s.index[-1], s.iloc[-1], "o", ms=4, color=color, mec=SURFACE, mew=1.2)


def chart_growth(index_lvl: pd.Series, bench: pd.Series, index_label: str, bench_label: str,
                 title: str, subtitle: str, out: Path, fname: str) -> str:
    """Growth of 1,000 for ONE like-for-like pair (PR vs PR, or TR vs TRI)."""
    fig, ax = plt.subplots(figsize=(9, 4.8))
    i = index_lvl / index_lvl.iloc[0] * 1000
    b = bench.reindex(index_lvl.index).ffill()
    b = b / b.iloc[0] * 1000
    series = [(i, index_label, SERIES[0]), (b, bench_label, SERIES[1])]
    hi, lo = (0, 1) if i.iloc[-1] >= b.iloc[-1] else (1, 0)
    close = series[hi][0].iloc[-1] / series[lo][0].iloc[-1] < 1.04
    for k, (s_, lbl, c) in enumerate(series):
        ax.plot(s_.index, s_, color=c, label=lbl)
        _end_label(ax, s_, f"{s_.iloc[-1]:,.0f}", c, (5 if k == hi else -5) if close else 0)
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(mtick.LogLocator(base=10, subs=(1.0, 1.5, 2.0, 3.0, 5.0, 7.0)))
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.yaxis.set_minor_formatter(mtick.NullFormatter())
    ax.set_title(title, pad=22)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=8.5, color=INK2, va="bottom")
    ax.legend(loc="upper left")
    ax.margins(x=0.06)
    return _save(fig, out / fname)


def chart_drawdown(r: pd.Series, b: pd.Series, r_label: str, b_label: str, out: Path) -> str:
    from .analytics import drawdown
    fig, ax = plt.subplots(figsize=(9, 3.2))
    for s_, lbl, c in [(drawdown(r), r_label, SERIES[0]), (drawdown(b), b_label, SERIES[1])]:
        ax.plot(s_.index, s_, color=c, label=lbl, lw=1.3)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax.axhline(0, color=AXIS, lw=0.8)
    ax.set_title("Drawdown from running peak (price return vs price return)")
    ax.legend(loc="lower left")
    return _save(fig, out / "drawdown.png")


def chart_bridge(bridge: pd.DataFrame, out: Path) -> str:
    """Annualised effect of each index rule on the gap vs the NIFTY 50, with 95% bootstrap
    intervals about zero, so the reader sees at a glance which effects are distinguishable from 0."""
    eff = bridge[bridge["kind"].isin(["step", "total"])].iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, 0.62 * len(eff) + 1.6))
    y = np.arange(len(eff))
    for k, (name, row) in enumerate(eff.iterrows()):
        v = row["value"]
        color = SERIES[0] if row["kind"] == "total" else (SERIES[2] if v >= 0 else SERIES[7])
        ax.barh(k, v, height=0.5, color=color)
        ax.errorbar(v, k, xerr=[[v - row["ci_low"]], [row["ci_high"] - v]], fmt="none",
                    ecolor=INK2, elinewidth=1.1, capsize=4)
        ax.annotate(f"{v:+.2%}", (row["ci_high"], k), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=8.5, color=INK)
    ax.axvline(0, color=INK2, lw=0.9)
    ax.set_yticks(y, eff.index)
    span = max(eff["ci_high"].abs().max(), eff["ci_low"].abs().max())
    ax.set_xlim(-span * 1.15, span * 1.35)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=1))
    ax.set_title("What separates the index from the NIFTY 50 (CAGR, price return)", pad=22)
    ax.text(0, 1.02, "Annualised effect of each rule · whiskers = 95% block-bootstrap interval · "
            "a whisker crossing 0 means not significant", transform=ax.transAxes, fontsize=8.5,
            color=INK2, va="bottom")
    ax.grid(axis="y", visible=False)
    return _save(fig, out / "bridge.png")


def chart_rolling(roll: pd.DataFrame, window: int, out: Path) -> str:
    fig, axes = plt.subplots(2, 1, figsize=(9, 5), sharex=True)
    ex = roll["excess_return"]
    axes[0].fill_between(ex.index, 0, ex, where=ex >= 0, color=SERIES[0], alpha=0.35, lw=0)
    axes[0].fill_between(ex.index, 0, ex, where=ex < 0, color=SERIES[1], alpha=0.35, lw=0)
    axes[0].plot(ex.index, ex, color=INK2, lw=0.9)
    axes[0].axhline(0, color=AXIS, lw=0.8)
    axes[0].set_title(f"Rolling {window}-day excess return vs benchmark")
    axes[0].yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    axes[1].plot(roll.index, roll["tracking_error"], color=SERIES[6], lw=1.4)
    axes[1].set_title(f"Rolling {window}-day tracking error (annualised)")
    axes[1].yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=1))
    return _save(fig, out / "rolling.png")


def chart_sector_weights(sw: pd.DataFrame, out: Path, top: int = 7) -> str:
    sw = sw.resample("ME").last()
    order = sw.mean().sort_values(ascending=False).index
    keep = list(order[:top])
    plot = sw[keep].copy()
    if len(order) > top:
        plot["Other"] = sw[order[top:]].sum(axis=1)
    colors = SERIES[:len(keep)] + ([OTHER] if "Other" in plot else [])
    fig, ax = plt.subplots(figsize=(9, 4.4))
    ax.stackplot(plot.index, plot.T.values, labels=plot.columns, colors=colors,
                 edgecolor=SURFACE, linewidth=0.6)
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax.set_title("Sector weights over time (month-end)")
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5))
    ax.margins(x=0)
    return _save(fig, out / "sector_weights.png")


def chart_turnover(rt: pd.DataFrame, out: Path) -> str:
    t = rt["one_way_turnover"].iloc[1:]
    fig, ax = plt.subplots(figsize=(9, 3.2))
    x = np.arange(len(t))
    ax.bar(x, t.values, color=SERIES[0], width=0.72)
    step = max(1, len(t) // 10)
    ax.set_xticks(x[::step], [str(d)[:7] for d in t.index[::step]])
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax.axhline(t.mean(), color=INK2, lw=0.9, ls="--")
    ax.annotate(f"avg {t.mean():.1%}", xy=(x[-1], t.mean()), xytext=(0, 4),
                textcoords="offset points", ha="right", fontsize=8.5, color=INK2)
    ax.set_title("One-way turnover at each rebalance")
    ax.grid(axis="x", visible=False)
    return _save(fig, out / "turnover.png")


def chart_variants(table: pd.DataFrame, out: Path) -> str:
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    xs, ys = table["volatility"], table["cagr"]
    span_x, span_y = (xs.max() - xs.min()) or 1, (ys.max() - ys.min()) or 1
    for i, (name, row) in enumerate(table.iterrows()):
        c = OTHER if name == "benchmark" else SERIES[i % len(SERIES)]
        ax.scatter(row["volatility"], row["cagr"], s=70, color=c, edgecolor=SURFACE, lw=1.5, zorder=3)
        # a point that sits just below a neighbour gets its label on the left
        crowded_below = any(
            (0 < (ys[o] - row["cagr"]) / span_y < 0.12) and abs(xs[o] - row["volatility"]) / span_x < 0.15
            for o in table.index if o != name)
        ax.annotate(name, (row["volatility"], row["cagr"]),
                    xytext=(-8, -3) if crowded_below else (8, 3), ha="right" if crowded_below else "left",
                    textcoords="offset points", fontsize=8.5, color=INK2)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=1))
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=1))
    ax.set_xlabel("Annualised volatility")
    ax.set_ylabel("CAGR (price return)")
    ax.set_title("Weighting schemes: risk vs return")
    ax.margins(0.25)
    return _save(fig, out / "variants.png")


def chart_attribution(by_sector: pd.DataFrame, out: Path) -> str:
    df = by_sector[["allocation", "selection", "interaction"]].iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(df) + 1.4))
    y = np.arange(len(df))
    h = 0.26
    for k, (colname, c) in enumerate(zip(df.columns, SERIES[:3])):
        ax.barh(y + (k - 1) * h, df[colname], height=h - 0.03, color=c, label=colname.title())
    ax.set_yticks(y, df.index)
    ax.axvline(0, color=AXIS, lw=0.8)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=1))
    ax.set_title("Brinson-Fachler attribution vs parent universe (linked)", pad=26)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3)
    ax.grid(axis="y", visible=False)
    return _save(fig, out / "attribution.png")


# ------------------------------------------------------------------ markdown helpers
def _fmt(v, kind: str) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    return {"pct": f"{v:.2%}", "num": f"{v:.2f}", "int": f"{int(v)}"}[kind]


PCT = {"cagr", "volatility", "max_drawdown", "var_95_1d", "cvar_95_1d", "best_month", "worst_month",
       "alpha_annual", "tracking_error", "active_return", "hit_rate_monthly"}
LABELS = {
    "cagr": "CAGR", "volatility": "Volatility (ann.)", "sharpe": "Sharpe", "sortino": "Sortino",
    "max_drawdown": "Max drawdown", "calmar": "Calmar", "var_95_1d": "1-day VaR 95%",
    "cvar_95_1d": "1-day CVaR 95%", "skew": "Skew", "excess_kurtosis": "Excess kurtosis",
    "best_month": "Best month", "worst_month": "Worst month", "beta": "Beta",
    "alpha_annual": "Jensen's alpha (ann.)", "correlation": "Correlation",
    "tracking_error": "Tracking error", "active_return": "Active return (CAGR diff)",
    "information_ratio": "Information ratio", "up_capture": "Up capture",
    "down_capture": "Down capture", "hit_rate_monthly": "Monthly hit rate",
}


def metrics_table(cols: dict[str, dict]) -> str:
    keys = [k for k in LABELS if any(k in c for c in cols.values())]
    head = "| Metric | " + " | ".join(cols) + " |\n|---|" + "---:|" * len(cols) + "\n"
    rows = []
    for k in keys:
        vals = [_fmt(c.get(k, np.nan), "pct" if k in PCT else "num") for c in cols.values()]
        rows.append(f"| {LABELS[k]} | " + " | ".join(vals) + " |")
    return head + "\n".join(rows)


def df_to_md(df: pd.DataFrame, pct_cols=(), num_cols=(), index_name: str = "") -> str:
    cols = list(df.columns)
    head = f"| {index_name} | " + " | ".join(str(c) for c in cols) + " |\n|---|" + "---:|" * len(cols) + "\n"
    lines = []
    for idx, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if c in pct_cols:
                cells.append(_fmt(v, "pct"))
            elif c in num_cols:
                cells.append(_fmt(v, "num"))
            else:
                cells.append(str(v))
        lines.append(f"| {idx} | " + " | ".join(cells) + " |")
    return head + "\n".join(lines)
