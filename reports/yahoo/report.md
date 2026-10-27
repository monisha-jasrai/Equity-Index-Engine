# India Large-Cap 40 — Backtest Report

> **Data source: Yahoo Finance (NSE).** See README for data limitations (survivorship bias, free-float approximation).

**Period:** 2016-03-31 → 2025-12-30 · **Rebalances:** 39 (quarterly) ·
**Constituents:** 40 · **Weighting:** capped_market_cap (stock cap 10%, sector cap 35%) ·
**Costs:** 10 bps per unit traded · **Risk-free:** 6.5%

![growth](charts/growth.png)

## Performance and risk

| Metric | Index PR | Index TR | Index NET | Benchmark PR |
|---|---:|---:|---:|---:|
| CAGR | 14.25% | 16.13% | 16.11% | 13.49% |
| Volatility (ann.) | 15.49% | 15.47% | 15.47% | 16.13% |
| Sharpe | 0.52 | 0.62 | 0.62 | 0.46 |
| Sortino | 0.71 | 0.86 | 0.86 | 0.63 |
| Max drawdown | -35.81% | -35.35% | -35.35% | -38.44% |
| Calmar | 0.40 | 0.46 | 0.46 | 0.35 |
| 1-day VaR 95% | 1.35% | 1.35% | 1.35% | 1.37% |
| 1-day CVaR 95% | 2.23% | 2.22% | 2.22% | 2.35% |
| Skew | -1.03 | -0.98 | -0.98 | -1.12 |
| Excess kurtosis | 20.08 | 19.38 | 19.38 | 20.17 |
| Best month | 12.83% | 12.83% | 12.83% | 14.68% |
| Worst month | -20.53% | -19.99% | -20.00% | -23.25% |
| Beta | 0.95 | – | – | – |
| Jensen's alpha (ann.) | 0.97% | – | – | – |
| Correlation | 0.98 | – | – | – |
| Tracking error | 2.90% | – | – | – |
| Active return (CAGR diff) | 0.75% | – | – | – |
| Information ratio | 0.19 | – | – | – |
| Up capture | 0.96 | – | – | – |
| Down capture | 0.95 | – | – | – |
| Monthly hit rate | 50.43% | – | – | – |

Relative statistics compare the **price-return** index with the **price-return** benchmark, so dividends do not flatter the comparison.

**Is the active return statistically meaningful?** A moving-block bootstrap (2,000 resamples, 20-day blocks) puts the annualised active return at
0.56% with a 95% interval of [-0.97%, 2.30%]; 79% of resamples are positive.

**Worst drawdown (TR):** -35.4%, peak 2020-01-17 → trough 2020-03-23, recovered 2020-10-08.

![drawdown](charts/drawdown.png)
![rolling](charts/rolling.png)

## Calendar-year returns

| Year | PR | TR | NET | Benchmark |
|---|---:|---:|---:|---:|
| 2016 | 4.87% | 6.10% | 6.07% | 5.78% |
| 2017 | 30.73% | 32.93% | 32.91% | 28.65% |
| 2018 | 4.38% | 6.09% | 6.06% | 3.15% |
| 2019 | 12.17% | 13.85% | 13.84% | 12.02% |
| 2020 | 18.86% | 20.91% | 20.87% | 14.90% |
| 2021 | 25.53% | 27.53% | 27.52% | 24.12% |
| 2022 | 4.66% | 6.32% | 6.31% | 4.33% |
| 2023 | 18.95% | 21.04% | 21.03% | 20.03% |
| 2024 | 9.31% | 10.87% | 10.86% | 8.80% |
| 2025 | 9.57% | 11.35% | 11.34% | 9.70% |

## Weighting-scheme comparison

Same universe, selection rules and rebalance calendar; only the weighting changes.

| Scheme | cagr | volatility | sharpe | max_drawdown | tracking_error | information_ratio | beta | avg_turnover | avg_effective_n |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| capped_market_cap | 14.25% | 15.49% | 0.52 | -35.81% | 2.90% | 0.19 | 0.95 | 1.98% | 23.10 |
| market_cap | 13.96% | 15.51% | 0.50 | -35.87% | 2.99% | 0.11 | 0.95 | 1.47% | 22.00 |
| equal | 16.07% | 16.13% | 0.60 | -37.71% | 4.69% | 0.48 | 0.96 | 5.42% | 39.62 |
| inverse_vol | 15.79% | 15.44% | 0.61 | -36.10% | 4.48% | 0.42 | 0.92 | 6.05% | 38.11 |
| sqrt_cap | 14.90% | 15.71% | 0.55 | -36.51% | 3.43% | 0.34 | 0.95 | 3.03% | 34.05 |
| benchmark | 13.49% | 16.13% | 0.46 | -38.44% | – | – | – | – | – |

![variants](charts/variants.png)

## Sector exposure and attribution

Brinson-Fachler attribution of the index against its **parent universe** (all eligible names, uncapped float-cap weights), per holding period, Carino-linked.
Index 257.11% vs parent 269.63% → active -12.52% =
allocation 6.91% + selection -20.55% + interaction 1.12% (residual -1.1e-15).

| Sector | allocation | selection | interaction | total |
|---|---:|---:|---:|---:|
| Energy | 4.57% | -0.45% | -0.30% | 3.82% |
| Communication Services | 1.17% | 0.00% | -0.00% | 1.17% |
| Information Technology | 0.33% | 0.57% | 0.06% | 0.96% |
| Materials | -0.29% | 0.27% | -0.00% | -0.02% |
| Financials | 2.30% | -2.53% | -0.17% | -0.39% |
| Utilities | -0.67% | -0.71% | -0.05% | -1.43% |
| Consumer Staples | 1.18% | -4.55% | 0.68% | -2.69% |
| Health Care | -0.80% | -2.17% | -0.10% | -3.07% |
| Consumer Discretionary | 0.47% | -5.35% | 0.25% | -4.63% |
| Industrials | -1.35% | -5.64% | 0.75% | -6.24% |

![attribution](charts/attribution.png)
![sectors](charts/sector_weights.png)

## Constituent contribution (price return, cumulative)

Top 10

| Stock | sector | contribution | avg_weight | days_in_index |
|---|---:|---:|---:|---:|
| RELIANCE | Energy | 19.89% | 9.27% | 2409 |
| HDFCBANK | Financials | 10.74% | 7.61% | 2409 |
| TCS | Information Technology | 10.16% | 8.93% | 2409 |
| BHARTIARTL | Communication Services | 7.84% | 3.48% | 2409 |
| ICICIBANK | Financials | 7.76% | 4.10% | 2409 |
| SBIN | Financials | 6.18% | 3.77% | 2409 |
| BAJFINANCE | Financials | 5.97% | 2.79% | 2285 |
| HINDUNILVR | Consumer Staples | 5.80% | 4.68% | 2409 |
| INFY | Information Technology | 5.46% | 4.59% | 2409 |
| MARUTI | Consumer Discretionary | 4.33% | 2.69% | 2409 |

Bottom 5

| Stock | sector | contribution | avg_weight | days_in_index |
|---|---:|---:|---:|---:|
| SHRIRAMFIN | Financials | -0.24% | 0.65% | 861 |
| BRITANNIA | Consumer Staples | -0.11% | 0.75% | 61 |
| DABUR | Consumer Staples | -0.02% | 0.74% | 307 |
| COALINDIA | Energy | -0.00% | 1.83% | 2409 |
| INDUSINDBK | Financials | 0.05% | 1.16% | 1544 |

## Rebalancing

![turnover](charts/turnover.png)

Most recent rebalances (full log in `rebalance_log.csv`):

| Rebalance | n | eligible | adds | dels | additions | deletions | one_way_turnover | cost_bps | divisor |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2024-06-28 | 40 | 55 | 0 | 0 |  |  | 0.76% | 0.15 | 52966723538.67 |
| 2024-09-30 | 40 | 55 | 0 | 0 |  |  | 0.72% | 0.14 | 53185843533.67 |
| 2024-12-31 | 40 | 55 | 0 | 0 |  |  | 0.82% | 0.16 | 53992321327.55 |
| 2025-03-28 | 40 | 55 | 0 | 0 |  |  | 0.47% | 0.09 | 53582114451.85 |
| 2025-06-30 | 40 | 55 | 0 | 0 |  |  | 0.79% | 0.16 | 53165687464.14 |
| 2025-09-30 | 40 | 55 | 0 | 0 |  |  | 0.71% | 0.14 | 53671066372.82 |

Current top 15 holdings (full list in `current_constituents.csv`):

| Ticker | sector | target_weight | current_weight | capping_factor |
|---|---:|---:|---:|---:|
| RELIANCE | Energy | 10.00% | 10.69% | 0.97 |
| HDFCBANK | Financials | 7.95% | 7.94% | 1.00 |
| BHARTIARTL | Communication Services | 6.31% | 6.59% | 1.00 |
| TCS | Information Technology | 5.99% | 6.13% | 1.00 |
| ICICIBANK | Financials | 5.39% | 5.00% | 1.00 |
| SBIN | Financials | 4.38% | 4.73% | 1.00 |
| INFY | Information Technology | 3.36% | 3.51% | 1.00 |
| BAJFINANCE | Financials | 3.45% | 3.21% | 1.00 |
| LT | Industrials | 2.72% | 2.91% | 1.00 |
| HINDUNILVR | Consumer Staples | 3.20% | 2.81% | 1.00 |
| MARUTI | Consumer Discretionary | 2.74% | 2.74% | 1.00 |
| ITC | Consumer Staples | 2.76% | 2.64% | 1.00 |
| HCLTECH | Information Technology | 2.13% | 2.33% | 1.00 |
| M&M | Consumer Discretionary | 2.38% | 2.32% | 1.00 |
| KOTAKBANK | Financials | 2.20% | 2.23% | 1.00 |
