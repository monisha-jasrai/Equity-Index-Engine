# India Large-Cap 40 — Backtest Report

> **Data source: Yahoo Finance (NSE).** Fixed-candidate-universe study weighted on **full market cap (IWF = 1: no historical free-float data)**. See *Data provenance and limitations* below.

**Period:** 2016-03-31 → 2025-12-30 · **Rebalances:** 39 (quarterly) ·
**Index type:** capped market-cap weighted (free-float-ready framework) · **Constituents:** 40 · **Weighting:** capped_market_cap on full market cap (IWF = 1: no historical free-float data) (stock cap 10%, sector cap 35%) ·
**Costs:** 10 bps per unit traded · **Risk-free:** 6.5%

![growth](charts/growth.png)

## Performance and risk

Comparisons are strictly like-for-like, so price return and total return are shown in **separate tables**.

**Price return vs price return** (the headline comparison):

| Metric | Index PR | NIFTY 50 PR |
|---|---:|---:|
| CAGR | 14.25% | 13.49% |
| Volatility (ann.) | 15.49% | 16.13% |
| Sharpe | 0.52 | 0.46 |
| Sortino | 0.71 | 0.63 |
| Max drawdown | -35.81% | -38.44% |
| Calmar | 0.40 | 0.35 |
| 1-day VaR 95% | 1.35% | 1.37% |
| 1-day CVaR 95% | 2.23% | 2.35% |
| Skew | -1.03 | -1.12 |
| Excess kurtosis | 20.08 | 20.17 |
| Best month | 12.83% | 14.68% |
| Worst month | -20.53% | -23.25% |
| Beta | 0.95 | – |
| Jensen's alpha (ann.) | 0.97% | – |
| Correlation | 0.98 | – |
| Tracking error | 2.90% | – |
| Active return (CAGR diff) | 0.75% | – |
| Information ratio | 0.19 | – |
| Up capture | 0.96 | – |
| Down capture | 0.95 | – |
| Monthly hit rate | 50.43% | – |

**Total return** (dividends reinvested; NET after transaction costs):

| Metric | Index TR (gross) | Index NET (after costs) |
|---|---:|---:|
| CAGR | 16.13% | 16.11% |
| Volatility (ann.) | 15.47% | 15.47% |
| Sharpe | 0.62 | 0.62 |
| Sortino | 0.86 | 0.86 |
| Max drawdown | -35.35% | -35.35% |
| Calmar | 0.46 | 0.46 |
| 1-day VaR 95% | 1.35% | 1.35% |
| 1-day CVaR 95% | 2.22% | 2.22% |
| Skew | -0.98 | -0.98 |
| Excess kurtosis | 19.38 | 19.38 |
| Best month | 12.83% | 12.83% |
| Worst month | -19.99% | -20.00% |

**Total return is not compared with a benchmark** in this run: no NIFTY 50 Total Returns Index was supplied, and comparing the index's TR with a price index would overstate it by roughly the dividend yield. Set `data.benchmark_tri_file` to add a TR vs TRI comparison. The index's TR and NET figures above are absolute numbers only.

**Is the active return statistically meaningful?** A moving-block bootstrap (2,000 resamples, 20-day blocks) of daily PR − PR active returns puts the mean annualised active return at
0.56% with a 95% interval of [-0.97%, 2.30%]; 79% of resamples are positive. (This arithmetic mean differs slightly from the CAGR gap because the two series have different volatility.)

**Worst drawdown (price return):** -35.8%, peak 2020-01-17 → trough 2020-03-23, recovered 2020-10-12.

![drawdown](charts/drawdown.png)
![rolling](charts/rolling.png)

## What drives the result

- **Size of the gap.** Price return vs price return, the index's CAGR differs from the NIFTY 50's by **+0.75% a year** (95% interval [-0.77%, 2.49%]), so the difference is **not** statistically distinguishable from zero: the data are consistent with anything from underperformance to meaningful outperformance, so the result is not statistically conclusive.
- **Which rule drives it.** Universe choice +1.17% (not significant); Top-40 cut -0.70% (significant); Stock & sector caps +0.28% (not significant). The largest single effect is **universe choice**.
- **Universe choice is where survivorship bias shows up.** That step compares an index of all candidates with the real NIFTY 50. The candidates are today's large caps, so they include companies that grew into the list and exclude ones that fell out of it. Treat the +1.17% as likely overstated, partly an artefact of the fixed candidate list rather than of the index rules.
- **Sector view of the rules.** Against the parent universe, Brinson-Fachler splits the cumulative (not annual) effect of the top-40 cut and caps into allocation +6.91%, selection -20.55% and interaction +1.12% (see the attribution section).
- **Is it broad-based?** The index beat the NIFTY in 7 of 10 calendar years. The best year (2020, +3.96%) matters: excluding it, the annual gap is +0.39%. Worst year: 2023 (-1.08%).
- **What this does not show.** A backtest over one ten-year window, on a fixed list of today's large caps, cannot establish a repeatable edge. Read the gap as a description of how these rules behaved in this period, not as evidence that they will outperform.

![bridge](charts/bridge.png)

| Step | CAGR / effect | 95% interval |
|---|---:|---:|
| NIFTY 50 | 13.49% |  |
| Universe choice | 1.17% | [-0.45%, 3.01%] |
| Top-40 cut | -0.70% | [-1.15%, -0.26%] |
| Stock & sector caps | 0.28% | [-0.11%, 0.77%] |
| Total gap (index − NIFTY) | 0.75% | [-0.77%, 2.49%] |
| Index | 14.25% |  |

## Calendar-year returns

Benchmark columns are the NIFTY 50 price index; the active columns compare like with like.

| Year | PR | TR | NET | Benchmark PR | Active (PR − PR) |
|---|---:|---:|---:|---:|---:|
| 2016 | 4.87% | 6.10% | 6.07% | 5.78% | -0.91% |
| 2017 | 30.73% | 32.93% | 32.91% | 28.65% | 2.08% |
| 2018 | 4.38% | 6.09% | 6.06% | 3.15% | 1.23% |
| 2019 | 12.17% | 13.85% | 13.84% | 12.02% | 0.14% |
| 2020 | 18.86% | 20.91% | 20.87% | 14.90% | 3.96% |
| 2021 | 25.53% | 27.53% | 27.52% | 24.12% | 1.41% |
| 2022 | 4.66% | 6.32% | 6.31% | 4.33% | 0.33% |
| 2023 | 18.95% | 21.04% | 21.03% | 20.03% | -1.08% |
| 2024 | 9.31% | 10.87% | 10.86% | 8.80% | 0.50% |
| 2025 | 9.57% | 11.35% | 11.34% | 9.70% | -0.13% |

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

## Sector exposure and attribution (vs the parent universe, not the NIFTY 50)

This section uses a **different benchmark** from the rest of the report. Brinson-Fachler needs the benchmark's stock weights at every rebalance, which are not available for the NIFTY 50, so the index is compared with its **parent universe**: all eligible candidates, uncapped market-cap weights. It therefore measures the effect of the index's own rules (top-40 cut and caps) by sector. A negative result here is not inconsistent with outperforming the NIFTY 50; the rules bridge above links the two benchmarks. Computed per holding period and Carino-linked.
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

## Rebalancing and costs

![turnover](charts/turnover.png)

**Cost convention.** At each rebalance the cost is (cost in bps) × Σ|new weight − drifted weight|, i.e. charged on the total notional traded, buys plus sells. One-way turnover is half that sum: 1.98% per rebalance on average, 4.0 rebalances a year. The base case is 10 bps.

**Sensitivity of the net return to the cost assumption:**

| Cost assumption | NET CAGR | Drag vs gross TR |
|---|---:|---:|
| 10 bps | 16.10% | 0.02% |
| 25 bps | 16.07% | 0.05% |
| 50 bps | 16.03% | 0.09% |

**Cap drift between rebalances.** Caps apply **at each rebalance**: the largest target weight is 10.00% (cap 10%). Between rebalances, index shares are fixed, so weights drift with prices. Just before the next rebalance, the largest stock weight averaged 9.94% (peak 14.06%) and exceeded the cap in 17 of 38 periods; the largest sector reached 29.41% (cap 35%). Each rebalance resets weights to within the caps. Today the largest weight is RELIANCE at 10.69%, which is drift since the last rebalance, not a capping failure.

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

## Validation

Every run reconciles its own outputs; failures are logged and shown here. Unit tests (`pytest`) separately check the logic on controlled inputs.

| Check | Result | Detail |
|---|---|---|
| Weights sum to 100% | ✅ pass | max abs(Σw − 1) over 2,409 days and 39 rebalances |
| Single-stock cap respected | ✅ pass | largest target weight 10.0000% vs cap 10% |
| Sector cap respected | ✅ pass | largest sector target 29.6737% vs cap 35% |
| Divisor keeps level continuous | ✅ pass | max relative gap between old-basket and new-basket level at each rebalance |
| Dividends reconcile (TR − PR) | ✅ pass | max daily gap vs dividends rebuilt from holdings; dividend yield ≈ 1.63%/yr |
| Costs reconcile (NET vs TR) | ✅ pass | cumulative cost drag 0.150% from 38 rebalances |
| Attribution sums to active return | ✅ pass | allocation + selection + interaction − active = -1.1e-15 |
| Attribution index return = PR level | ✅ pass | 257.1069% vs 257.1069% |
| Selection uses lagged data | ✅ pass | minimum lag 5 trading days (required ≥ 5) |

## Data provenance and limitations

| Input | Basis in this run |
|---|---|
| Universe | fixed candidate list of current large caps (not historical index membership) (55 candidates with data) |
| Weighting basis | full market cap (IWF = 1: no historical free-float data) |
| Index weight resting on point-in-time share counts (avg. over rebalances) | 88.2% |
| … on back-filled share counts (look-ahead) | 6.0% |
| … on today's share count used for past dates (look-ahead) | 5.8% |
| Index weight with a known (non-default) IWF | 0.0% |
| Prices, volumes, liquidity screen | daily, point-in-time (split-adjusted closes) |
| Excluded (no data) | LTIM |

Limitations:

- **Survivorship bias.** The candidates are today's large caps, so companies that were large in 2016 but later shrank or delisted are missing. Treat results as a fixed-candidate-universe study, not a reconstruction of a historical index.
- **Free float.** No historical free-float data was used (IWF = 1), so weights are on full market cap. The engine supports point-in-time IWFs via `data.shareholding_file`.
- **Share counts.** Where a stock's weight rests on back-filled or current share counts (above), its historical weight uses information that was not available at the time.
- **Benchmark.** NIFTY 50 price index only; the index's total return is not benchmarked until a NIFTY 50 TRI file is supplied.
- **Corporate actions.** Splits via split-adjusted prices; spin-offs and rights issues are not modelled.

Run log: `run_log.json` (2026-10-28T20:41:21+00:00, checks passed 9/9, config hash `5e80518b00643f14`).
