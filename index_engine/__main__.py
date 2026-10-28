"""Command-line entry point.

    python -m index_engine --config config/india_large_cap_40.yaml               # real NSE data
    python -m index_engine --config config/india_large_cap_40.yaml --source synthetic
"""
from __future__ import annotations

import argparse
import logging

from .config import load_config
from .pipeline import run


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="index_engine", description="Construct and back-test an equity index")
    p.add_argument("--config", default="config/india_large_cap_40.yaml")
    p.add_argument("--source", choices=["yahoo", "synthetic"], help="override data.source")
    p.add_argument("--scheme", help="override weighting.scheme")
    p.add_argument("--frequency", choices=["monthly", "quarterly", "semiannual", "annual"])
    p.add_argument("--out", help="output directory (default reports/<source>)")
    p.add_argument("--refresh", action="store_true", help="re-download data, ignoring the cache")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    overrides = {k: v for k, v in {"source": a.source, "scheme": a.scheme, "frequency": a.frequency}.items() if v}
    cfg = load_config(a.config, **overrides)
    out = a.out or f"reports/{cfg.source}"
    import sys
    res = run(cfg, out, refresh=a.refresh, config_path=a.config, argv=["python -m index_engine", *sys.argv[1:]])
    s = res["stats"]
    print(f"\n{cfg.name}  [{res['summary']['source']}]  {res['summary']['start']} -> {res['summary']['end']}")
    for k in ("Index PR", "Index TR", "Index NET", "Benchmark PR"):
        print(f"  {k:<13} CAGR {s[k]['cagr']:7.2%}   vol {s[k]['volatility']:6.2%}   "
              f"Sharpe {s[k]['sharpe']:5.2f}   maxDD {s[k]['max_drawdown']:7.2%}")
    pr = s["Index PR"]
    print(f"  vs benchmark: beta {pr['beta']:.2f}  TE {pr['tracking_error']:.2%}  IR {pr['information_ratio']:.2f}")
    print(f"  weighting basis: {res['md'].weighting_basis}")
    print(f"  validation checks passed: {res['summary']['checks_passed']}")
    print(f"\nReport written to {out}/report.md  (run log: {out}/run_log.json)")


if __name__ == "__main__":
    main()
