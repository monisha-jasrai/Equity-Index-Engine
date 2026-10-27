"""Typed loading and validation of the index methodology YAML."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

WEIGHT_SCHEMES = {"market_cap", "capped_market_cap", "equal", "inverse_vol", "sqrt_cap"}
FREQUENCIES = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}


@dataclass(frozen=True)
class IndexConfig:
    name: str
    base_value: float
    start_date: str
    end_date: str
    currency: str
    # data
    source: str
    cache_dir: str
    benchmark_ticker: str
    synthetic_seed: int
    # selection
    n_constituents: int
    retain_rank: int
    min_history_days: int
    liquidity_lookback_days: int
    min_median_traded_value: float
    reference_lag_days: int
    # weighting
    scheme: str
    single_stock_cap: float
    sector_cap: float
    vol_lookback_days: int
    # rebalance / costs
    frequency: str
    transaction_cost_bps: float
    # analytics
    risk_free_rate: float
    periods_per_year: int
    rolling_window_days: int
    bootstrap_samples: int
    bootstrap_block_days: int
    variants: tuple[str, ...]
    universe: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.scheme not in WEIGHT_SCHEMES:
            raise ValueError(f"unknown weighting scheme {self.scheme!r}")
        if self.frequency not in FREQUENCIES:
            raise ValueError(f"unknown rebalance frequency {self.frequency!r}")
        if self.retain_rank < self.n_constituents:
            raise ValueError("retain_rank must be >= n_constituents")
        if self.scheme == "capped_market_cap":
            if self.single_stock_cap * self.n_constituents < 1.0:
                raise ValueError("single_stock_cap * n_constituents < 1: caps are infeasible")
            n_sectors = len(set(self.universe.values()))
            if self.sector_cap * n_sectors < 1.0:
                raise ValueError("sector_cap * n_sectors < 1: caps are infeasible")
        for v in self.variants:
            if v not in WEIGHT_SCHEMES:
                raise ValueError(f"unknown variant {v!r}")

    def with_overrides(self, **kwargs) -> "IndexConfig":
        return replace(self, **kwargs)


def load_config(path: str | Path, **overrides) -> IndexConfig:
    raw = yaml.safe_load(Path(path).read_text())
    cfg = IndexConfig(
        name=raw["index"]["name"],
        base_value=float(raw["index"]["base_value"]),
        start_date=str(raw["index"]["start_date"]),
        end_date=str(raw["index"]["end_date"]),
        currency=raw["index"].get("currency", ""),
        source=raw["data"]["source"],
        cache_dir=raw["data"]["cache_dir"],
        benchmark_ticker=raw["data"]["benchmark_ticker"],
        synthetic_seed=int(raw["data"].get("synthetic_seed", 42)),
        n_constituents=int(raw["selection"]["n_constituents"]),
        retain_rank=int(raw["selection"]["retain_rank"]),
        min_history_days=int(raw["selection"]["min_history_days"]),
        liquidity_lookback_days=int(raw["selection"]["liquidity_lookback_days"]),
        min_median_traded_value=float(raw["selection"]["min_median_traded_value"]),
        reference_lag_days=int(raw["selection"]["reference_lag_days"]),
        scheme=raw["weighting"]["scheme"],
        single_stock_cap=float(raw["weighting"]["single_stock_cap"]),
        sector_cap=float(raw["weighting"]["sector_cap"]),
        vol_lookback_days=int(raw["weighting"]["vol_lookback_days"]),
        frequency=raw["rebalance"]["frequency"],
        transaction_cost_bps=float(raw["costs"]["transaction_cost_bps"]),
        risk_free_rate=float(raw["analytics"]["risk_free_rate"]),
        periods_per_year=int(raw["analytics"]["periods_per_year"]),
        rolling_window_days=int(raw["analytics"]["rolling_window_days"]),
        bootstrap_samples=int(raw["analytics"]["bootstrap_samples"]),
        bootstrap_block_days=int(raw["analytics"]["bootstrap_block_days"]),
        variants=tuple(raw.get("variants", [raw["weighting"]["scheme"]])),
        universe=dict(raw["universe"]),
    )
    return cfg.with_overrides(**overrides) if overrides else cfg
