#!/usr/bin/env python3
"""
SSOT Sync: portfolio_state.json → sim-portfolio.json

Reads the single source of truth and generates a clean, validated
public-facing portfolio file. All calculations done from raw position data.

Usage:
  python sync_portfolio.py              # sync + validate
  python sync_portfolio.py --dry-run    # validate only, don't write
"""

import json, sys
from pathlib import Path
from datetime import datetime

SSOT = Path(__file__).parent.parent.parent / "sim-portfolio" / "portfolio_state.json"
OUTPUT = Path(__file__).parent.parent / "output-buffer" / "sim-portfolio.json"


def calculate_account(acct_data, acct_key):
    """Calculate account totals from raw position data. Never trust pre-computed values."""
    cash = acct_data.get("cash", 0)
    initial = acct_data.get("initial_capital", 0)
    positions = acct_data.get("positions", [])

    long_mv = 0
    short_pnl = 0
    pub_positions = []

    for pos in positions:
        shares = pos.get("shares", 0)
        avg_cost = pos.get("avg_cost", 0)
        current_price = pos.get("current_price", avg_cost)
        abs_shares = abs(shares)
        is_short = shares < 0

        if is_short:
            mv = -(abs_shares * current_price)
            pnl = (avg_cost - current_price) * abs_shares
            pnl_pct = (avg_cost - current_price) / avg_cost * 100 if avg_cost else 0
            short_pnl += pnl
        else:
            mv = shares * current_price
            pnl_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost else 0
            long_mv += mv

        ticker = pos.get("ticker", "")
        if acct_key == "a_share" and "." not in ticker:
            if ticker.startswith("6"):
                ticker = f"{ticker}.SS"
            else:
                ticker = f"{ticker}.SZ"

        pub_positions.append({
            "ticker": ticker,
            "name": pos.get("name", ""),
            "shares": shares,
            "avg_cost": round(avg_cost, 4),
            "current_price": round(current_price, 4),
            "market_value": round(mv, 2),
            "unrealized_pnl_pct": round(pnl_pct, 2),
            "portfolio_pct": 0,  # filled below
            "entry_date": pos.get("entry_date", ""),
            "type": pos.get("type", ""),
            "sector": pos.get("sector", ""),
        })

    total_assets = cash + long_mv + short_pnl
    return_pct = ((total_assets - initial) / initial * 100) if initial else 0

    for p in pub_positions:
        abs_mv = abs(p["market_value"])
        p["portfolio_pct"] = round(abs_mv / total_assets, 3) if total_assets else 0

    return {
        "currency": acct_data.get("currency", ""),
        "initial_capital": initial,
        "total_assets": round(total_assets, 2),
        "cash": round(cash, 2),
        "realized_pnl": round(acct_data.get("realized_pnl", 0), 2),
        "return_pct": round(return_pct, 2),
        "positions": pub_positions,
    }, long_mv, short_pnl


def build_snapshots(ssot):
    snapshots = []
    daily = ssot.get("performance", {}).get("daily_snapshots", [])
    for s in daily:
        snapshots.append({
            "date": s["date"],
            "a_share": {
                "total_assets": s.get("a_share_nav", 0),
                "return_pct": s.get("a_share_return_pct", 0),
            },
            "us": {
                "total_assets": s.get("us_nav", 0),
                "return_pct": s.get("us_return_pct", 0),
            },
            "combined_return_pct": 0,  # filled below
        })
    return snapshots


def build_trade_log(ssot):
    trades = []
    for t in ssot.get("trade_log", []):
        entry = {
            "date": t.get("timestamp", t.get("date", ""))[:10],
            "account": t.get("account", ""),
            "action": t.get("action", ""),
            "ticker": t.get("ticker", ""),
            "shares": t.get("shares", 0),
            "price": t.get("price", 0),
        }
        if "realized_pnl" in t:
            entry["realized_pnl"] = t["realized_pnl"]
        trades.append(entry)
    return trades


def validate(output_data):
    errors = []
    for acct_key in ["a_share", "us"]:
        acct = output_data["accounts"][acct_key]
        cash = acct["cash"]
        initial = acct["initial_capital"]
        total = acct["total_assets"]
        positions = acct["positions"]

        long_mv = sum(p["market_value"] for p in positions if p["shares"] > 0)
        short_pnl = sum(
            (p["avg_cost"] - p["current_price"]) * abs(p["shares"])
            for p in positions if p["shares"] < 0
        )
        expected_total = cash + long_mv + short_pnl

        if abs(expected_total - total) > 1.0:
            errors.append(
                f"{acct_key}: total_assets={total} != cash({cash}) + "
                f"long_mv({long_mv:.2f}) + short_pnl({short_pnl:.2f}) = {expected_total:.2f}"
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

    a_acct, a_long_mv, a_short_pnl = calculate_account(
        ssot["accounts"]["a_share"], "a_share"
    )
    us_acct, us_long_mv, us_short_pnl = calculate_account(
        ssot["accounts"]["us"], "us"
    )

    snapshots = build_snapshots(ssot)

    a_initial_usd = a_acct["initial_capital"] / 7.2
    us_initial_usd = us_acct["initial_capital"]
    total_initial = a_initial_usd + us_initial_usd

    for snap in snapshots:
        a_nav = snap["a_share"]["total_assets"]
        us_nav = snap["us"]["total_assets"]
        combined = ((a_nav / 7.2 + us_nav) / total_initial - 1) * 100
        snap["combined_return_pct"] = round(combined, 2)

    output = {
        "meta": {
            "type": "sim_portfolio",
            "description": "Claude AI模拟盘 — ¥1M A股 + $150K 美股",
            "start_date": ssot.get("_meta", {}).get("start_date", "2026-05-18"),
            "end_date": ssot.get("_meta", {}).get("end_date", "2026-06-18"),
            "last_updated": datetime.now().astimezone().isoformat(),
            "synced_from": "portfolio_state.json",
            "benchmark": {"a_share": "CSI300", "us": "SPY"},
            "disclaimer": "模拟盘，非真实交易。仅供研究参考。",
        },
        "accounts": {"a_share": a_acct, "us": us_acct},
        "daily_snapshots": snapshots,
        "trade_log": build_trade_log(ssot),
    }

    errors = validate(output)
    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    a_ret = a_acct["return_pct"]
    us_ret = us_acct["return_pct"]
    combined = ((a_acct["total_assets"] / 7.2 + us_acct["total_assets"]) / total_initial - 1) * 100

    print(f"✓ Validation passed")
    print(f"  A股: ¥{a_acct['total_assets']:,.0f} ({a_ret:+.2f}%) | {len(a_acct['positions'])} positions")
    print(f"  美股: ${us_acct['total_assets']:,.0f} ({us_ret:+.2f}%) | {len(us_acct['positions'])} positions")
    print(f"  综合: {combined:+.2f}%")
    print(f"  交易: {len(output['trade_log'])} trades")

    if dry_run:
        print(f"\n[dry-run] Would write to {OUTPUT}")
    else:
        with open(OUTPUT, "w") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Written to {OUTPUT}")


if __name__ == "__main__":
    main()
