# Equity Index Engine — India Large-Cap 40

![tests](https://github.com/monisha-jasrai/Equity-Index-Engine/actions/workflows/tests.yml/badge.svg)

A rules-based engine that **constructs, calculates and back-tests a free-float, market-cap weighted equity index** of 40 NSE-listed stocks, then evaluates it against the NIFTY 50 with institutional-grade risk, benchmark-relative and attribution analytics.

The index is calculated the way exchange index providers (NSE Indices, S&P DJI, MSCI) do it: **index shares and a divisor**, with the divisor reset at every quarterly rebalance so the level stays continuous. The full methodology lives in one YAML file, so every rule is auditable and changeable without touching code.

![growth](reports/synthetic/charts/growth.png)

> Charts in this README come from the bundled **synthetic** market (so the repo runs offline and in CI). Run with `--source yahoo` to reproduce on real NSE data; results land in `reports/yahoo/`.

---

## What it does

| Stage | Detail |
|---|---|
| **Universe & eligibility** | 56 large-cap NSE candidates across 10 sectors. Point-in-time screens: minimum 6-month trading history, minimum median daily traded value, valid sector. |
| **Selection** | Top 40 by free-float market cap, with a **rank buffer** (incumbents keep their seat down to rank 48) to cut turnover from names flickering around the cutoff. |
| **Weighting** | Free-float market cap with an **iterative 10% single-stock cap and 35% sector cap**; excess weight redistributed pro rata until both constraints hold. Four alternative schemes (uncapped, equal, inverse-volatility, √cap) for comparison. |
| **Index calculation** | Divisor-based price-return (PR) level, gross total-return (TR) with dividend reinvestment, and an investable **NET** series charged transaction costs on actual rebalance turnover. |
| **No look-ahead** | Selection and weights use data snapshotted 5 trading days before the effective date, as real index committees do. |
| **Analytics** | CAGR, volatility, Sharpe, Sortino, Calmar, max drawdown (with recovery), historical VaR/CVaR, skew/kurtosis, beta, Jensen's alpha, tracking error, information ratio, up/down capture, rolling 1-year beta/TE/excess return, calendar-year returns. |
| **Significance** | **Moving-block bootstrap** confidence interval on active return (preserves volatility clustering, unlike an i.i.d. bootstrap). |
| **Attribution** | **Brinson-Fachler** sector attribution (allocation / selection / interaction) per holding period, **Carino-linked** so effects sum exactly to the cumulative active return; constituent and sector contribution to return. |
| **Engineering** | Typed config with validation, cached data layer, vectorised daily calculation (~0.5 s per 10-year backtest), 13 invariant tests, GitHub Actions CI. |

---

## Quick start

```bash
git clone https://github.com/monisha-jasrai/Equity-Index-Engine.git
cd Equity-Index-Engine
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m index_engine --source yahoo        # real NSE data (downloads once, then cached)
python -m index_engine --source synthetic    # fully offline demo
pytest -q                                    # run the test suite
```

Useful overrides:

```bash
python -m index_engine --scheme equal                 # different weighting
python -m index_engine --frequency monthly            # different rebalance calendar
python -m index_engine --refresh                      # force re-download
```

Each run writes to `reports/<source>/`:

| File | Contents |
|---|---|
| `report.md` | Full tear sheet: metrics, charts, attribution, rebalance log |
| `index_levels.csv` | Daily PR / TR / NET levels, benchmark, divisor |
| `rebalance_log.csv` | Every rebalance: adds, deletes, turnover, cost, divisor, concentration |
| `current_constituents.csv` | Latest holdings with target/current weights, capping factors, index shares |
| `attribution_by_period.csv` | Brinson-Fachler effects for each sector in each holding period |
| `variant_comparison.csv` | Weighting-scheme comparison |
| `summary.json` | Machine-readable headline results |

---

## Methodology

### 1. Index level and the divisor

$$
\text{Level}_t = \frac{\sum_i q_i \, P_{i,t}}{D}, \qquad q_i = \text{Shares}_i \times \text{IWF}_i \times \text{CF}_i
$$

* $q_i$ — **index shares**: shares outstanding × investable weight factor (free-float fraction) × capping factor. Frozen between rebalances.
* $\text{CF}_i$ — **capping factor**, scales a stock's index shares so its weight equals the capped target. By convention the largest CF is 1.
* $D$ — **divisor**. When constituents or index shares change at a rebalance, market value jumps for reasons unrelated to price moves. The divisor is reset so the level is unchanged at that close:

$$
D_{\text{new}} = D_{\text{old}} \times \frac{MV_{\text{new}}}{MV_{\text{old}}}
$$

This continuity is enforced by a unit test (`test_level_is_continuous_across_rebalances`).

### 2. Price, total and net return

* **PR**: the level above. Dividends are ignored, so the price drop on an ex-date is a loss.
* **TR**: $\; TR_t = TR_{t-1} \cdot \dfrac{\sum_i q_i (P_{i,t} + d_{i,t})}{\sum_i q_i P_{i,t-1}}$ — cash dividends reinvested across the whole index on the ex-date.
* **NET**: TR multiplied by $(1 - c)$ at each rebalance, where $c = \text{bps} \times \sum_i |w_i^{\text{new}} - w_i^{\text{drifted}}|$. Drifted weights are the pre-rebalance weights after a quarter of price moves, so costs reflect trades a tracking fund would actually make.

Benchmark comparisons use **PR vs PR** (NIFTY 50 on Yahoo is a price index) so dividends don't flatter the result.

### 3. Selection with a buffer

At each reference date, eligible stocks are ranked by free-float market cap. Incumbents ranked ≤ 48 are retained; remaining seats go to the highest-ranked non-members. Without the buffer, a stock oscillating between ranks 39 and 41 would be bought and sold every quarter. `test_buffer_rule_reduces_turnover` verifies it.

### 4. Capping algorithm

Alternating projections onto the two constraint sets:

1. Any stock above 10% is set to 10%; the excess is spread pro rata over names that are below both their stock cap and their sector cap.
2. Any sector above 35% is scaled down to 35%; the excess is spread pro rata over names in sectors below the cap.
3. Repeat until both constraints hold.

Capping can cascade (redistribution pushes the next stock over the cap), which is why it must iterate. Feasibility is checked up front: 40 × 10% ≥ 100% and 10 sectors × 35% ≥ 100%.

### 5. Attribution

Brinson-Fachler against the **parent universe** (all eligible names, uncapped cap weights) — this isolates the effect of the index's *rules* (top-40 cutoff and capping):

$$
\text{Allocation}_s = (w^I_s - w^B_s)(r^B_s - R^B), \quad
\text{Selection}_s = w^B_s (r^I_s - r^B_s), \quad
\text{Interaction}_s = (w^I_s - w^B_s)(r^I_s - r^B_s)
$$

Computed for each holding period (index shares are fixed, so buy-and-hold period returns are exact), then linked across periods with **Carino smoothing**, $k_t / K$ with $k = \frac{\ln(1+R^I) - \ln(1+R^B)}{R^I - R^B}$, so the three effects sum to the cumulative active return with zero residual (verified by test).

### 6. Analytics definitions

| Metric | Definition |
|---|---|
| Sharpe | $\frac{\overline{r - r_f}}{\sigma(r - r_f)}\sqrt{252}$ |
| Sortino | annualised mean excess return / downside deviation |
| Beta / Jensen's alpha | OLS of index excess returns on benchmark excess returns |
| Tracking error | $\sigma(r_I - r_B)\sqrt{252}$ |
| Information ratio | annualised mean active return / tracking error |
| Up / down capture | mean index return ÷ mean benchmark return on up / down benchmark days |
| VaR / CVaR 95% | historical 5th-percentile daily loss / mean loss beyond it |

---

## Sample output (synthetic market)

| | |
|---|---|
| ![drawdown](reports/synthetic/charts/drawdown.png) | ![rolling](reports/synthetic/charts/rolling.png) |
| ![sectors](reports/synthetic/charts/sector_weights.png) | ![attribution](reports/synthetic/charts/attribution.png) |
| ![variants](reports/synthetic/charts/variants.png) | ![turnover](reports/synthetic/charts/turnover.png) |

Full tear sheet: [`reports/synthetic/report.md`](reports/synthetic/report.md).

---

## Project structure

```
equity-index-engine/
├── config/india_large_cap_40.yaml   # the complete index methodology
├── index_engine/
│   ├── config.py        # typed, validated config
│   ├── data.py          # Yahoo loader (cached) + synthetic market simulator
│   ├── universe.py      # eligibility screens, buffered selection
│   ├── weighting.py     # cap-weighting, iterative capping, alt. schemes, concentration
│   ├── engine.py        # divisor-based PR / TR / NET calculation, rebalancing, costs
│   ├── analytics.py     # risk/return, relative stats, rolling, block bootstrap
│   ├── attribution.py   # Brinson-Fachler + Carino linking, contributions
│   ├── report.py        # charts and Markdown tables
│   ├── pipeline.py      # end-to-end run
│   └── __main__.py      # CLI
├── tests/test_engine.py # invariant tests
└── reports/             # generated output
```

### The synthetic market

`make_synthetic` simulates the configured universe with a market factor under **GARCH(1,1)** volatility and Student-t shocks, sector factors, stock-specific betas and idiosyncratic risk, a crash-and-recovery episode, quarterly dividends (price drops on ex-date), buybacks/issuance, a few illiquid names (to exercise the liquidity screen) and late listings (to exercise the history screen). It is seeded, so results are reproducible.

---

## Limitations and honest caveats

* **Survivorship bias.** The candidate list is today's large caps. Stocks that were large in 2016 and later fell away are missing, which flatters back-tested returns. A production version would use point-in-time historical index membership.
* **Free float.** Yahoo does not publish historical investable weight factors, so IWF = 1 on real data (full market cap). The engine fully supports IWFs; plug in NSE's free-float data to use them.
* **Shares outstanding.** Taken from yfinance's share history where available (restated for splits), otherwise the current count. Exchange providers use filed share counts.
* **Corporate actions.** Splits are handled via split-adjusted prices; spin-offs and rights issues are not modelled explicitly.
* **Benchmark.** NIFTY 50 PR from Yahoo; a TR comparison would need the NIFTY 50 TRI series from NSE.

---

## Extending

* Add a weighting scheme: one branch in `weighting.target_weights`, then list it under `variants`.
* New market: copy the YAML, change `universe` and `benchmark_ticker` (e.g. S&P 500 names and `^GSPC`).
* Ideas: factor tilts (momentum/quality), ESG exclusions, optimiser-based minimum-variance weights, a Streamlit dashboard.
