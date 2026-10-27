# Interview prep — Equity Index Engine

Read this until you can answer every question without looking. Interviewers will probe the project on your resume harder than anything else.

## 30-second pitch

"I built a rules-based index engine in Python that constructs a 40-stock, free-float market-cap weighted index of large NSE stocks and back-tests it against the NIFTY 50 over ten years. It calculates the index the way NSE and S&P do, with index shares and a divisor that's reset at each quarterly rebalance. It applies a 10% single-stock cap and a 35% sector cap, produces price, total-return and net-of-cost series, and then analyses the result with risk metrics, a block bootstrap on active return, and Brinson-Fachler attribution to explain where the performance difference came from."

## Resume bullets (fill in the numbers from YOUR `reports/yahoo/report.md`)

* Constructed and back-tested a **capped free-float market-cap weighted index of 40 NSE stocks** (2016–2025) in Python, using a **divisor-based** calculation with quarterly reconstitution, a rank-buffer selection rule and 10% stock / 35% sector caps.
* Produced price-return, total-return and **net-of-transaction-cost** series; index delivered **X% CAGR vs Y% for NIFTY 50** with **Z% tracking error** and information ratio of **W**.
* Decomposed active return with **Brinson-Fachler sector attribution** (Carino-linked) and tested significance via a **moving-block bootstrap**; compared five weighting schemes on risk, return and turnover.

Only use numbers you actually generated from the real-data run.

## Concepts you must be able to explain

**Why a divisor?** Index level = market value / divisor. When you add or drop stocks or change index shares, market value changes for reasons that aren't price moves. Resetting the divisor (D_new = D_old × MV_new / MV_old) keeps the level continuous, so the index only moves when prices move.

**Free-float / IWF.** Only shares available to public investors count (promoter and government holdings excluded). NSE uses an Investable Weight Factor. In my real-data run IWF = 1 because Yahoo doesn't provide history — say this upfront, it shows awareness.

**Why cap weights?** Uncapped cap weighting lets a few giants dominate (concentration risk, and regulatory limits for funds — e.g. SEBI diversification norms). Capping limits single-name and sector risk at the cost of some tracking error versus the uncapped parent.

**Capping algorithm.** Cap anything above 10%, redistribute the excess pro rata to names with room, repeat because redistribution can push the next name over; same for sectors. It must be iterative because of cascading.

**Buffer rule.** Incumbents stay unless they fall below rank 48. Without it, names near rank 40 churn every quarter, which costs money and adds no information.

**Reference lag / look-ahead bias.** Weights are computed with data 5 trading days before the rebalance. Using same-day data would be look-ahead: you couldn't actually trade on information you only get at that close.

**PR vs TR vs NET.** PR ignores dividends. TR reinvests them. NET deducts trading costs on rebalance turnover — what an index fund tracking it would actually earn. I compare PR with NIFTY 50 PR so it's apples-to-apples.

**Turnover.** One-way turnover = ½ Σ|w_new − w_drifted|. Drifted weights are where weights ended up after a quarter of price moves, not the old targets.

**Tracking error and information ratio.** TE = annualised std of daily (index − benchmark) returns. IR = annualised active return / TE: active return per unit of active risk.

**Beta below 1 with a cap-weighted index?** Capping and sector limits reduce weight in the largest, often most market-driving names, and differences in sector mix change sensitivity.

**Brinson-Fachler.** Allocation: did over/underweighting sectors help? Selection: within a sector, did our stocks beat the benchmark's stocks? Interaction: the cross term. Brinson-Fachler measures allocation relative to the total benchmark return, so overweighting a sector only scores positive if that sector beat the overall benchmark.

**Why attribute against the parent universe, not NIFTY 50?** Brinson needs the benchmark's constituent weights each period, which aren't freely available for NIFTY 50. The parent (all eligible names, uncapped) isolates exactly what my rules — the top-40 cut and the caps — did.

**Carino linking.** Single-period effects don't add up over many periods because returns compound. Carino rescales each period's effects with log-return-based coefficients so they sum to the total active return.

**Why a block bootstrap?** Daily returns aren't independent (volatility clusters). Resampling blocks of 20 days keeps that structure, so the confidence interval on active return is honest. If the interval contains zero, the outperformance isn't statistically significant — saying so is a strength.

**Sharpe vs Sortino.** Sortino only penalises downside volatility.

**VaR vs CVaR.** VaR 95% = the loss you exceed only 5% of days. CVaR = the average loss on those worst 5% of days — captures tail severity.

## Questions you will probably get

1. *What's the biggest weakness of your backtest?* — Survivorship bias: the universe is today's large caps. Fix: point-in-time index membership data.
2. *How did you avoid look-ahead bias?* — Reference-date lag; eligibility uses only data up to the reference date.
3. *How would you test it's correct?* — Unit tests for divisor continuity, weights summing to 1, caps respected, attribution residual ≈ 0, zero-cost NET = TR, buffer reduces turnover.
4. *What happens to a stock that gets delisted mid-quarter?* — Its last price is carried forward until the next rebalance removes it (a simplification; real providers remove it with a divisor adjustment).
5. *Why quarterly rebalancing?* — Trade-off between staying representative and turnover cost; the CLI lets you compare monthly/annual.
6. *Which weighting scheme was best and why?* — Answer from your variant table; discuss the size effect (equal weight tilts to smaller stocks) and costs (equal weight has higher turnover).
7. *How would you extend it?* — Point-in-time membership, real IWFs, NIFTY TRI benchmark, factor tilts, an optimiser for minimum variance.
