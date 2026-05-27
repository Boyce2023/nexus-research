"""
NAV calculation — single source of truth.

All scripts that compute total_assets MUST use calc_nav().
Never duplicate this formula elsewhere.

NAV = cash + long_market_value + short_margin + short_unrealized_pnl

When shorting: margin (entry_price × shares) is deducted from cash but
still belongs to the portfolio. On cover, margin is returned ± PnL.
"""

from __future__ import annotations


def calc_nav(account: dict, *, price_overrides: dict | None = None) -> dict:
    """
    Calculate NAV and component breakdown for one account.

    Args:
        account: account dict with keys: cash, positions, short_positions
        price_overrides: optional {ticker: price} to use instead of stored prices

    Returns:
        dict with: total_assets, long_mv, short_margin, short_pnl, unrealized_pnl
    """
    overrides = price_overrides or {}
    cash = account.get("cash", 0)

    long_mv = 0.0
    long_unrealized = 0.0
    for pos in account.get("positions", []):
        shares = pos.get("shares", 0)
        if shares <= 0:
            continue
        price = overrides.get(pos["ticker"], pos.get("current_price", pos.get("avg_cost", 0)))
        mv = shares * price
        long_mv += mv
        long_unrealized += mv - shares * pos.get("avg_cost", 0)

    short_margin = 0.0
    short_pnl = 0.0
    for sp in account.get("short_positions", []):
        entry = sp.get("entry_price", 0)
        shares = abs(sp.get("shares", 0))
        price = overrides.get(sp["ticker"], sp.get("current_price", entry))
        short_margin += entry * shares
        short_pnl += (entry - price) * shares

    total_assets = round(cash + long_mv + short_margin + short_pnl, 2)
    unrealized_pnl = round(long_unrealized + short_pnl, 2)

    return {
        "total_assets": total_assets,
        "long_mv": round(long_mv, 2),
        "short_margin": round(short_margin, 2),
        "short_pnl": round(short_pnl, 2),
        "unrealized_pnl": unrealized_pnl,
        "cash": cash,
    }


def apply_nav(account: dict, nav: dict, initial_capital: float | None = None) -> None:
    """Write NAV results back into the account dict in-place."""
    account["total_assets"] = nav["total_assets"]
    account["unrealized_pnl"] = nav["unrealized_pnl"]
    account["total_invested"] = round(nav["long_mv"] + nav["short_margin"], 2)

    ta = nav["total_assets"]
    if ta > 0:
        account["cash_pct"] = round(nav["cash"] / ta, 3)
        for pos in account.get("positions", []):
            shares = pos.get("shares", 0)
            if shares > 0:
                pos["portfolio_pct"] = round(pos.get("market_value", 0) / ta, 3)

    if initial_capital and initial_capital > 0:
        account["return_pct"] = round((ta / initial_capital - 1) * 100, 2)


def validate_nav(account: dict, label: str = "") -> list[str]:
    """Cross-check stored total_assets against fresh calculation. Returns errors."""
    nav = calc_nav(account)
    stored = account.get("total_assets", 0)
    errors = []
    if abs(stored - nav["total_assets"]) > 1:
        errors.append(
            f"[{label}] NAV mismatch: stored={stored:.2f}, "
            f"calculated={nav['total_assets']:.2f}, "
            f"diff={stored - nav['total_assets']:.2f}"
        )
    return errors
