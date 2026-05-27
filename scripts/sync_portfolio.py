#!/usr/bin/env python3
"""SSOT Sync: portfolio_state.json → sim-portfolio.json

Uses core/compute.full_snapshot() as the single computation source.
All NAV, return_pct, portfolio_pct, and combined_return logic lives there.

Usage:
  python sync_portfolio.py              # sync + validate
  python sync_portfolio.py --dry-run    # validate only, don't write
"""

import json, sys
from pathlib import Path

# Add sim-portfolio/scripts to path so we can import core
SIM_PORTFOLIO = Path(__file__).parent.parent.parent / "sim-portfolio"
sys.path.insert(0, str(SIM_PORTFOLIO / "scripts"))

from core.compute import full_snapshot  # noqa: E402
from nav_calc import calc_nav           # noqa: E402

SSOT = SIM_PORTFOLIO / "portfolio_state.json"
OUTPUT = Path(__file__).parent.parent / "output-buffer" / "sim-portfolio.json"


def validate(output_data):
    """Independent cross-check of the generated output.

    NAV formula: total_assets = cash + long_mv + short_margin + short_pnl
    short_margin = sum(entry_price × shares) for each short position,
    which is money held as collateral and still belongs to the portfolio.
    """
    errors = []
    for acct_key in ["a_share", "us"]:
        acct = output_data["accounts"][acct_key]
        cash = acct["cash"]
        initial = acct["initial_capital"]
        total = acct["total_assets"]
        positions = acct["positions"]

        long_mv = sum(p["market_value"] for p in positions if p["shares"] > 0)
        # short_margin = entry_price × abs(shares) (collateral, always positive)
        short_margin = sum(
            p["avg_cost"] * abs(p["shares"])
            for p in positions if p["shares"] < 0
        )
        short_pnl = sum(
            (p["avg_cost"] - p["current_price"]) * abs(p["shares"])
            for p in positions if p["shares"] < 0
        )
        expected_total = cash + long_mv + short_margin + short_pnl

        if abs(expected_total - total) > 1.0:
            errors.append(
                f"{acct_key}: total_assets={total} != cash({cash}) + "
                f"long_mv({long_mv:.2f}) + short_margin({short_margin:.2f}) + "
                f"short_pnl({short_pnl:.2f}) = {expected_total:.2f}"
            )

        expected_return = ((total - initial) / initial * 100) if initial else 0
        if abs(expected_return - acct["return_pct"]) > 0.05:
            errors.append(
                f"{acct_key}: return_pct={acct['return_pct']} != "
                f"({total}-{initial})/{initial}*100 = {expected_return:.2f}"
            )

        has_shorts = any(p["shares"] < 0 for p in positions)
        if not has_shorts:
            pct_sum = sum(p["portfolio_pct"] for p in positions)
            cash_pct = cash / total if total else 0
            if abs(pct_sum + cash_pct - 1.0) > 0.05:
                errors.append(
                    f"{acct_key}: position pcts({pct_sum:.3f}) + cash_pct({cash_pct:.3f}) "
                    f"!= 1.0 (diff={pct_sum + cash_pct - 1.0:.3f})"
                )

    return errors


def main():
    dry_run = "--dry-run" in sys.argv

    if not SSOT.exists():
        print(f"ERROR: SSOT not found: {SSOT}")
        sys.exit(1)

    with open(SSOT) as f:
        ssot = json.load(f)

    # All computation delegated to the unified engine
    output = full_snapshot(ssot)

    # Independent validation cross-check
    errors = validate(output)
    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    a_acct = output["accounts"]["a_share"]
    us_acct = output["accounts"]["us"]
    a_initial = a_acct["initial_capital"]
    us_initial = us_acct["initial_capital"]
    a_total = a_acct["total_assets"]
    us_total = us_acct["total_assets"]
    combined = ((a_total / 7.2 + us_total) / (a_initial / 7.2 + us_initial) - 1) * 100

    print("✓ Validation passed")
    print(f"  A股: ¥{a_total:,.0f} ({a_acct['return_pct']:+.2f}%) | {len(a_acct['positions'])} positions")
    print(f"  美股: ${us_total:,.0f} ({us_acct['return_pct']:+.2f}%) | {len(us_acct['positions'])} positions")
    print(f"  综合: {combined:+.2f}%")
    print(f"  交易: {len(output['trade_log'])} trades")

    if dry_run:
        print(f"\n[dry-run] Would write to {OUTPUT}")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT, "w") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Written to {OUTPUT}")


if __name__ == "__main__":
    main()
