"""Eligibility screens and constituent selection (with a rank buffer)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import IndexConfig
from .data import MarketData


@dataclass
class SelectionResult:
    constituents: list[str]
    eligible: list[str]
    ranks: pd.Series          # float-mcap rank among eligible names (1 = largest)
    additions: list[str]
    deletions: list[str]
    excluded: dict[str, str]  # ticker -> reason it failed eligibility


def eligibility(md: MarketData, cfg: IndexConfig, ref_pos: int) -> tuple[list[str], dict[str, str]]:
    """Point-in-time screens evaluated using only data up to row `ref_pos`."""
    eligible, excluded = [], {}
    window = slice(max(0, ref_pos - cfg.liquidity_lookback_days + 1), ref_pos + 1)
    hist = md.prices.iloc[: ref_pos + 1].notna().sum()
    tv = md.traded_value().iloc[window].median()
    px = md.prices.iloc[ref_pos]
    sh = md.shares.iloc[ref_pos]
    for t in md.tickers:
        if pd.isna(px[t]):
            excluded[t] = "no price on reference date"
        elif not sh[t] > 0:
            excluded[t] = "no shares outstanding data"
        elif hist[t] < cfg.min_history_days:
            excluded[t] = f"history {int(hist[t])}d < {cfg.min_history_days}d"
        elif not tv[t] >= cfg.min_median_traded_value:
            excluded[t] = "below liquidity threshold"
        elif pd.isna(md.sectors.get(t)):
            excluded[t] = "no sector classification"
        else:
            eligible.append(t)
    return eligible, excluded


def select_constituents(md: MarketData, cfg: IndexConfig, ref_pos: int,
                        current: list[str] | None = None) -> SelectionResult:
    """Top-N by free-float market cap, keeping incumbents ranked within `retain_rank`."""
    current = current or []
    eligible, excluded = eligibility(md, cfg, ref_pos)
    fmc = md.float_market_cap().iloc[ref_pos][eligible]
    ranks = fmc.rank(ascending=False, method="first").astype(int).sort_values()
    n = min(cfg.n_constituents, len(eligible))

    keep = [t for t in current if t in ranks.index and ranks[t] <= cfg.retain_rank]
    keep = sorted(keep, key=lambda t: ranks[t])[:n]
    newcomers = [t for t in ranks.index if t not in keep]
    chosen = keep + newcomers[: n - len(keep)]
    chosen = sorted(chosen, key=lambda t: ranks[t])

    return SelectionResult(
        constituents=chosen,
        eligible=eligible,
        ranks=ranks,
        additions=[t for t in chosen if t not in current],
        deletions=[t for t in current if t not in chosen],
        excluded=excluded,
    )
