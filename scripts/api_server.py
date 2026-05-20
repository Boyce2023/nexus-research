#!/usr/bin/env python3
"""
Nexus Recommendation API Server
供第三方平台（雪球/公众号）内嵌调用

Endpoints:
  GET  /api/v1/recommendations          — 获取所有活跃推荐
  GET  /api/v1/recommendations/<id>      — 获取单条推荐详情
  GET  /api/v1/recommendations/summary   — 获取推荐摘要（适合卡片展示）
  GET  /api/v1/portfolio/stats           — 获取组合统计数据
  GET  /api/v1/portfolio/live            — 模拟盘实时持仓+收益率（yfinance）
  GET  /api/v1/widget/card/<id>          — 获取可嵌入的HTML卡片
  GET  /api/v1/widget/portfolio          — 获取完整组合widget HTML
  GET  /api/v1/widget/performance        — 收益率变化图表（Chart.js）
  GET  /api/v1/feed/rss                  — RSS订阅源
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json, os, sys, threading, time
from pathlib import Path
from datetime import datetime
import urllib.parse

BASE = Path(__file__).parent.parent
PUBLISHED = BASE / "output-buffer" / "published"
SIM_PORTFOLIO = BASE / "output-buffer" / "sim-portfolio.json"
PORT = int(os.environ.get("PORT", 8899))

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

_price_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 300


def get_price(ticker):
    now = time.time()
    with _cache_lock:
        if ticker in _price_cache and now - _price_cache[ticker]["t"] < CACHE_TTL:
            return _price_cache[ticker]["p"]
    if not HAS_YF:
        return None
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = info.last_price
        with _cache_lock:
            _price_cache[ticker] = {"p": price, "t": now}
        return price
    except Exception:
        return None


def load_all_recs():
    recs = []
    for f in sorted(PUBLISHED.glob("*.json"), reverse=True):
        with open(f) as fp:
            recs.append(json.load(fp))
    return recs


def load_sim_portfolio():
    if not SIM_PORTFOLIO.exists():
        return None
    with open(SIM_PORTFOLIO) as fp:
        return json.load(fp)


def get_live_portfolio():
    sim = load_sim_portfolio()
    if not sim:
        return {"error": "sim portfolio not found"}

    accounts = {}
    total_initial = 0
    total_current = 0

    for acct_key in ["a_share", "us"]:
        acct = sim["accounts"][acct_key]
        currency = acct["currency"]
        initial = acct["initial_capital"]
        total_initial_acct = initial
        positions = []
        invested_value = 0
        total_cost = 0

        for pos in acct["positions"]:
            ticker = pos["ticker"]
            shares = pos["shares"]
            avg_cost = pos["avg_cost"]
            cost_basis = shares * avg_cost

            live_price = get_price(ticker)
            if live_price is None:
                live_price = avg_cost

            market_value = shares * live_price
            pnl = market_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0

            invested_value += market_value
            total_cost += cost_basis

            positions.append({
                "ticker": ticker,
                "name": pos["name"],
                "type": pos["type"],
                "shares": shares,
                "avg_cost": round(avg_cost, 2),
                "current_price": round(live_price, 2),
                "cost_basis": round(cost_basis, 2),
                "market_value": round(market_value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "entry_date": pos["entry_date"]
            })

        cash = initial - total_cost + (invested_value - total_cost)
        total_assets = initial + (invested_value - total_cost)
        return_pct = ((total_assets - initial) / initial * 100)

        accounts[acct_key] = {
            "currency": currency,
            "initial_capital": initial,
            "total_assets": round(total_assets, 2),
            "invested_value": round(invested_value, 2),
            "cash": round(initial - total_cost, 2),
            "return_pct": round(return_pct, 2),
            "unrealized_pnl": round(invested_value - total_cost, 2),
            "positions": sorted(positions, key=lambda x: abs(x["pnl"]), reverse=True)
        }

        if currency == "CNY":
            total_initial += initial / 7.2
            total_current += total_assets / 7.2
        else:
            total_initial += initial
            total_current += total_assets

    combined_return = ((total_current - total_initial) / total_initial * 100) if total_initial > 0 else 0

    snapshots = sim.get("daily_snapshots", [])

    return {
        "updated_at": datetime.now().isoformat(),
        "yfinance_available": HAS_YF,
        "cache_ttl_seconds": CACHE_TTL,
        "combined": {
            "total_initial_usd_equiv": round(total_initial, 2),
            "total_current_usd_equiv": round(total_current, 2),
            "combined_return_pct": round(combined_return, 2)
        },
        "accounts": accounts,
        "daily_snapshots": snapshots,
        "disclaimer": sim["meta"]["disclaimer"]
    }


def make_summary(rec):
    return {
        "id": rec["id"],
        "ticker": rec["ticker"],
        "name": rec["name"],
        "market": rec["market"],
        "direction": rec["direction"],
        "conviction": rec["conviction"],
        "headline": rec["display"]["headline"],
        "summary": rec["display"]["summary_cn"],
        "target_price": rec["valuation"].get("target_price"),
        "current_price": rec["valuation"].get("current_price"),
        "upside_pct": rec["valuation"].get("upside_pct"),
        "bear_downside": rec["bear_case"]["probability_weighted_downside"],
        "tags": rec["display"]["tags"],
        "risk_level": rec["display"]["risk_level"],
        "created_at": rec["metadata"]["created_at"],
        "review_date": rec["metadata"]["review_date"],
        "checks_passed": rec["metadata"].get("system_checks_passed", {})
    }


def make_widget_card(rec):
    d = rec["direction"]
    dir_cn = {"long": "做多", "short": "做空", "avoid": "回避"}[d]
    dir_color = {"long": "#3fb950", "short": "#f85149", "avoid": "#d29922"}[d]
    conv_cn = {"high": "高", "medium": "中", "low": "低"}[rec["conviction"]]
    upside = rec["valuation"].get("upside_pct", 0)
    target = rec["valuation"].get("target_price", "N/A")

    checks_html = ""
    for k, v in rec["metadata"].get("system_checks_passed", {}).items():
        icon = "✓" if v else "✗"
        color = "#3fb950" if v else "#f85149"
        checks_html += f'<span style="color:{color};margin-right:8px;font-size:11px">{icon} {k.replace("_"," ")}</span>'

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
.nexus-card{{font-family:-apple-system,sans-serif;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-left:3px solid {dir_color};border-radius:8px;padding:16px;max-width:480px;line-height:1.5}}
.nexus-card h3{{color:#fff;margin:0 0 8px;font-size:15px}}
.nexus-card .meta{{font-size:12px;color:#8b949e;margin-bottom:8px}}
.nexus-card .meta span{{margin-right:12px}}
.nexus-card .direction{{color:{dir_color};font-weight:700}}
.nexus-card .summary{{font-size:13px;margin:8px 0}}
.nexus-card .checks{{font-size:11px;margin-top:8px;padding-top:8px;border-top:1px solid #30363d}}
.nexus-card .footer{{font-size:11px;color:#8b949e;margin-top:8px}}
.nexus-card a{{color:#58a6ff;text-decoration:none}}
</style></head><body>
<div class="nexus-card">
<h3>{rec['display']['headline']}</h3>
<div class="meta">
<span class="direction">{dir_cn}</span>
<span>确信度: {conv_cn}</span>
<span>目标: ${target} ({upside:+.1f}%)</span>
<span>Bear: {rec['bear_case']['probability_weighted_downside']}%</span>
</div>
<div class="summary">{rec['display']['summary_cn']}</div>
<div class="checks">{checks_html}</div>
<div class="footer">Nexus Research System · {rec['metadata']['data_freshness']} · <a href="#">查看完整分析</a></div>
</div></body></html>"""


def make_portfolio_widget(recs):
    total = len(recs)
    long_count = sum(1 for r in recs if r["direction"] == "long")
    short_count = sum(1 for r in recs if r["direction"] == "short")
    avg_upside = sum(r["valuation"].get("upside_pct", 0) for r in recs) / max(total, 1)

    cards = ""
    for rec in recs:
        d = rec["direction"]
        dir_cn = {"long": "做多", "short": "做空", "avoid": "回避"}[d]
        dir_color = {"long": "#3fb950", "short": "#f85149", "avoid": "#d29922"}[d]
        upside = rec["valuation"].get("upside_pct", 0)
        cards += f"""<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #30363d">
<div><span style="color:{dir_color};font-weight:700;margin-right:8px">{dir_cn}</span><span style="color:#fff">{rec['ticker']}</span> <span style="color:#8b949e;font-size:12px">{rec['name']}</span></div>
<div style="text-align:right"><span style="color:{'#3fb950' if upside>0 else '#f85149'};font-weight:700">{upside:+.1f}%</span><br><span style="font-size:11px;color:#8b949e">{rec['conviction'].upper()}</span></div>
</div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
.nexus-portfolio{{font-family:-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:20px;max-width:520px}}
.nexus-portfolio h2{{color:#fff;font-size:16px;margin:0 0 4px}}
.nexus-portfolio .subtitle{{color:#8b949e;font-size:12px;margin-bottom:16px}}
.nexus-portfolio .stats{{display:flex;gap:20px;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid #30363d}}
.nexus-portfolio .stat-num{{font-size:18px;font-weight:700;color:#58a6ff}}
.nexus-portfolio .stat-label{{font-size:11px;color:#8b949e}}
.nexus-portfolio .footer{{font-size:11px;color:#8b949e;margin-top:12px;text-align:center}}
.nexus-portfolio a{{color:#58a6ff;text-decoration:none}}
</style></head><body>
<div class="nexus-portfolio">
<h2>Nexus Research System</h2>
<div class="subtitle">系统化股票研究 · 先淘汰再推荐 · Bear Case硬门验证</div>
<div class="stats">
<div><div class="stat-num">{total}</div><div class="stat-label">活跃推荐</div></div>
<div><div class="stat-num">{long_count}L/{short_count}S</div><div class="stat-label">多空</div></div>
<div><div class="stat-num">{avg_upside:+.1f}%</div><div class="stat-label">平均预期</div></div>
</div>
{cards}
<div class="footer">Powered by Nexus · <a href="#">查看全部分析</a></div>
</div></body></html>"""


def make_performance_widget():
    sim = load_sim_portfolio()
    if not sim:
        return "<p>Portfolio not available</p>"

    a_acct = sim["accounts"].get("a_share", {})
    us_acct = sim["accounts"].get("us", {})
    snapshots = sim.get("daily_snapshots", [])
    trade_log = sim.get("trade_log", [])
    last_updated = sim["meta"].get("last_updated", "")

    a_return = a_acct.get("return_pct", 0)
    us_return = us_acct.get("return_pct", 0)
    a_initial = a_acct.get("initial_capital", 1000000)
    us_initial = us_acct.get("initial_capital", 150000)
    a_total = a_acct.get("total_assets", a_initial)
    us_total = us_acct.get("total_assets", us_initial)
    combined_return = round(a_return * 0.87 + us_return * 0.13, 2)

    snapshot_dates = json.dumps([s["date"] for s in snapshots])
    snapshot_a = json.dumps([s.get("a_share", {}).get("return_pct", 0) for s in snapshots])
    snapshot_us = json.dumps([s.get("us", {}).get("return_pct", 0) for s in snapshots])
    snapshot_combined = json.dumps([s.get("combined_return_pct", 0) for s in snapshots])

    a_rows = ""
    for p in a_acct.get("positions", []):
        pnl_pct = p.get("unrealized_pnl_pct", 0)
        cost_basis = p["shares"] * p["avg_cost"]
        pnl = p.get("market_value", cost_basis) - cost_basis
        color = "#3fb950" if pnl >= 0 else "#f85149"
        a_rows += f"""<tr>
<td>{p['ticker']}</td><td>{p.get('name','')}</td><td>{p['shares']}</td>
<td>¥{p['avg_cost']:.2f}</td><td>¥{p.get('current_price', p['avg_cost']):.2f}</td>
<td style="color:{color};font-weight:700">{pnl_pct:+.2f}%</td>
<td style="color:{color}">¥{pnl:,.0f}</td></tr>"""

    us_rows = ""
    for p in us_acct.get("positions", []):
        pnl_pct = p.get("unrealized_pnl_pct", 0)
        cost_basis = p["shares"] * p["avg_cost"]
        pnl = p.get("market_value", cost_basis) - cost_basis
        color = "#3fb950" if pnl >= 0 else "#f85149"
        us_rows += f"""<tr>
<td>{p['ticker']}</td><td>{p.get('name','')}</td><td>{p['shares']}</td>
<td>${p['avg_cost']:.2f}</td><td>${p.get('current_price', p['avg_cost']):.2f}</td>
<td style="color:{color};font-weight:700">{pnl_pct:+.2f}%</td>
<td style="color:{color}">${pnl:,.0f}</td></tr>"""

    trade_rows = ""
    for t in reversed(trade_log):
        acct_label = "A股" if t.get("account") == "a_share" else "美股"
        action_cn = {"buy": "买入", "sell": "卖出", "short": "做空", "cover": "平空"}.get(t.get("action", ""), t.get("action", ""))
        action_color = {"buy": "#3fb950", "sell": "#f85149", "short": "#f85149", "cover": "#3fb950"}.get(t.get("action", ""), "#c9d1d9")
        currency = "¥" if t.get("account") == "a_share" else "$"
        value = t.get("shares", 0) * t.get("price", 0)
        trade_rows += f"""<tr>
<td>{t.get('date','')}</td><td>{acct_label}</td>
<td style="color:{action_color};font-weight:600">{action_cn}</td>
<td>{t.get('ticker','')}</td><td>{t.get('shares',0)}</td>
<td>{currency}{t.get('price',0):.2f}</td><td>{currency}{value:,.0f}</td></tr>"""

    a_color = "#3fb950" if a_return >= 0 else "#f85149"
    us_color = "#3fb950" if us_return >= 0 else "#f85149"
    c_color = "#3fb950" if combined_return >= 0 else "#f85149"
    pos_count = len(a_acct.get("positions", [])) + len(us_acct.get("positions", []))

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9;padding:20px}}
.container{{max-width:900px;margin:0 auto}}
h1{{color:#fff;font-size:20px;margin-bottom:4px}}
.subtitle{{color:#8b949e;font-size:12px;margin-bottom:20px}}
.stats-bar{{display:flex;gap:24px;margin-bottom:24px;padding:16px;background:#161b22;border:1px solid #30363d;border-radius:8px;flex-wrap:wrap}}
.stat{{text-align:center;min-width:80px}}
.stat-val{{font-size:24px;font-weight:700}}
.stat-lbl{{font-size:11px;color:#8b949e;margin-top:2px}}
.chart-box{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:24px}}
.chart-box h3{{color:#fff;font-size:14px;margin-bottom:12px}}
.section{{margin-bottom:24px}}
.section h2{{color:#fff;font-size:16px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #30363d}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;color:#8b949e;font-weight:500;padding:8px 6px;border-bottom:1px solid #30363d}}
td{{padding:8px 6px;border-bottom:1px solid #21262d}}
.disclaimer{{font-size:11px;color:#484f58;text-align:center;margin-top:24px;padding-top:16px;border-top:1px solid #21262d}}
.updated{{font-size:11px;color:#484f58;text-align:right;margin-bottom:8px}}
</style></head><body>
<div class="container">
<h1>Nexus AI 模拟组合</h1>
<div class="subtitle">Claude AI独立管理 · 2026-05-18 → 06-18 · 同步数据</div>
<div class="updated">数据同步: {last_updated[:19]}</div>

<div class="stats-bar">
<div class="stat"><div class="stat-val" style="color:{a_color}">{a_return:+.2f}%</div><div class="stat-lbl">A股 (¥{a_total:,.0f})</div></div>
<div class="stat"><div class="stat-val" style="color:{us_color}">{us_return:+.2f}%</div><div class="stat-lbl">美股 (${us_total:,.0f})</div></div>
<div class="stat"><div class="stat-val" style="color:{c_color}">{combined_return:+.2f}%</div><div class="stat-lbl">综合收益率</div></div>
<div class="stat"><div class="stat-val" style="color:#58a6ff">{pos_count}</div><div class="stat-lbl">持仓标的</div></div>
<div class="stat"><div class="stat-val" style="color:#8b949e">{len(trade_log)}</div><div class="stat-lbl">总交易笔数</div></div>
</div>

<div class="chart-box">
<h3>收益率走势</h3>
<canvas id="perfChart" height="200"></canvas>
</div>

<div class="section">
<h2>A股持仓 (初始 ¥1,000,000)</h2>
<table>
<tr><th>代码</th><th>名称</th><th>股数</th><th>成本</th><th>现价</th><th>涨跌</th><th>盈亏</th></tr>
{a_rows}
</table>
</div>

<div class="section">
<h2>美股持仓 (初始 $150,000)</h2>
<table>
<tr><th>代码</th><th>名称</th><th>股数</th><th>成本</th><th>现价</th><th>涨跌</th><th>盈亏</th></tr>
{us_rows}
</table>
</div>

<div class="section">
<h2>交易明细</h2>
<table>
<tr><th>日期</th><th>账户</th><th>操作</th><th>标的</th><th>股数</th><th>价格</th><th>金额</th></tr>
{trade_rows}
</table>
</div>

<div class="disclaimer">此为AI系统模拟投资组合，仅用于研究验证。不构成投资建议。<br>Nexus Research System · Powered by Claude AI</div>
</div>

<script>
const dates = {snapshot_dates};
const aReturns = {snapshot_a};
const usReturns = {snapshot_us};
const combinedReturns = {snapshot_combined};

if (dates.length > 0) {{
    new Chart(document.getElementById('perfChart'), {{
        type: 'line',
        data: {{
            labels: dates,
            datasets: [
                {{label: 'A股', data: aReturns, borderColor: '#f97316', borderWidth: 2, pointRadius: 3, tension: 0.3}},
                {{label: '美股', data: usReturns, borderColor: '#3b82f6', borderWidth: 2, pointRadius: 3, tension: 0.3}},
                {{label: '综合', data: combinedReturns, borderColor: '#3fb950', borderWidth: 2.5, pointRadius: 3, tension: 0.3}}
            ]
        }},
        options: {{
            responsive: true,
            plugins: {{legend: {{labels: {{color: '#c9d1d9'}}}}}},
            scales: {{
                x: {{ticks: {{color: '#8b949e'}}, grid: {{color: '#21262d'}}}},
                y: {{ticks: {{color: '#8b949e', callback: v => v+'%'}}, grid: {{color: '#21262d'}}}}
            }}
        }}
    }});
}} else {{
    document.getElementById('perfChart').parentElement.innerHTML = '<h3>收益率走势</h3><p style="color:#8b949e;text-align:center;padding:40px">模拟盘刚启动，数据积累中...</p>';
}}
</script>
</body></html>"""


def make_rss(recs):
    items = ""
    for rec in recs:
        items += f"""<item>
<title>{rec['display']['headline']}</title>
<description><![CDATA[{rec['display']['summary_cn']}]]></description>
<pubDate>{rec['metadata']['created_at']}</pubDate>
<guid>{rec['id']}</guid>
<category>{','.join(rec['display']['tags'])}</category>
</item>
"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Nexus Research System</title>
<description>系统化股票研究推荐</description>
<language>zh-CN</language>
<lastBuildDate>{datetime.now().isoformat()}</lastBuildDate>
{items}
</channel>
</rss>"""


class APIHandler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    def _html(self, html, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _xml(self, xml, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(xml.encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        recs = load_all_recs()

        if path == "/api/v1/recommendations":
            self._json({"count": len(recs), "recommendations": recs})

        elif path.startswith("/api/v1/recommendations/") and "summary" not in path and "widget" not in path:
            rec_id = path.split("/")[-1]
            match = [r for r in recs if rec_id in r["id"]]
            if match:
                self._json(match[0])
            else:
                self._json({"error": "not found"}, 404)

        elif path == "/api/v1/recommendations/summary":
            summaries = [make_summary(r) for r in recs]
            self._json({"count": len(summaries), "recommendations": summaries})

        elif path == "/api/v1/portfolio/stats":
            stats = {
                "total_active": len(recs),
                "long": sum(1 for r in recs if r["direction"] == "long"),
                "short": sum(1 for r in recs if r["direction"] == "short"),
                "avg_upside_pct": sum(r["valuation"].get("upside_pct", 0) for r in recs) / max(len(recs), 1),
                "avg_bear_downside": sum(r["bear_case"]["probability_weighted_downside"] for r in recs) / max(len(recs), 1),
                "high_conviction": sum(1 for r in recs if r["conviction"] == "high"),
                "markets": list(set(r["market"] for r in recs)),
                "updated_at": datetime.now().isoformat()
            }
            self._json(stats)

        elif path == "/api/v1/portfolio/live":
            self._json(get_live_portfolio())

        elif path.startswith("/api/v1/widget/card/"):
            rec_id = path.split("/")[-1]
            match = [r for r in recs if rec_id in r["id"] or rec_id.upper() in r["ticker"].upper()]
            if match:
                self._html(make_widget_card(match[0]))
            else:
                self._html("<p>Not found</p>", 404)

        elif path == "/api/v1/widget/portfolio":
            self._html(make_portfolio_widget(recs))

        elif path == "/api/v1/widget/performance":
            self._html(make_performance_widget())

        elif path == "/api/v1/feed/rss":
            self._xml(make_rss(recs))

        elif path == "/":
            self._html(make_performance_widget())

        elif path == "/docs":
            self._html("""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Nexus API</title>
<style>body{font-family:monospace;background:#0d1117;color:#c9d1d9;padding:40px;max-width:800px;margin:0 auto}
h1{color:#fff}a{color:#58a6ff}code{background:#161b22;padding:2px 6px;border-radius:3px}
.endpoint{margin:12px 0;padding:8px;background:#161b22;border-radius:4px}
.new{color:#3fb950;font-size:11px;font-weight:700;margin-left:8px}</style></head><body>
<h1>Nexus Research System API</h1>
<p>系统化股票研究推荐接口 · 供第三方平台内嵌</p>
<h2>Endpoints</h2>
<h3>推荐系统</h3>
<div class="endpoint"><code>GET</code> <a href="/api/v1/recommendations">/api/v1/recommendations</a> — 全部推荐(完整JSON)</div>
<div class="endpoint"><code>GET</code> <a href="/api/v1/recommendations/summary">/api/v1/recommendations/summary</a> — 推荐摘要(卡片用)</div>
<div class="endpoint"><code>GET</code> <a href="/api/v1/portfolio/stats">/api/v1/portfolio/stats</a> — 组合统计</div>
<h3>模拟盘实时数据<span class="new">NEW</span></h3>
<div class="endpoint"><code>GET</code> <a href="/api/v1/portfolio/live">/api/v1/portfolio/live</a> — 实时持仓+收益率(A股+美股)</div>
<div class="endpoint"><code>GET</code> <a href="/api/v1/widget/performance">/api/v1/widget/performance</a> — 收益率图表+持仓明细(可嵌入)</div>
<h3>Widgets</h3>
<div class="endpoint"><code>GET</code> <a href="/api/v1/widget/portfolio">/api/v1/widget/portfolio</a> — 可嵌入组合Widget(HTML)</div>
<div class="endpoint"><code>GET</code> /api/v1/widget/card/{ticker} — 单条推荐卡片Widget(HTML)</div>
<div class="endpoint"><code>GET</code> <a href="/api/v1/feed/rss">/api/v1/feed/rss</a> — RSS订阅源</div>
<h2>嵌入方式</h2>
<p>雪球/公众号/任何网站用 iframe 嵌入:</p>
<code>&lt;iframe src="https://YOUR_DOMAIN/api/v1/widget/performance" width="920" height="900"&gt;&lt;/iframe&gt;</code>
</body></html>""")

        else:
            self._json({"error": "unknown endpoint", "docs": "/"}, 404)

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


if __name__ == "__main__":
    port = PORT
    host = "127.0.0.1"
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--port" and i < len(sys.argv) - 1:
            port = int(sys.argv[i + 1])
        elif arg == "--host" and i < len(sys.argv) - 1:
            host = sys.argv[i + 1]

    server = HTTPServer((host, port), APIHandler)
    print(f"Nexus API Server running at http://{host}:{port}")
    print(f"  Docs:        http://{host}:{port}/docs")
    print(f"  Portfolio:   http://{host}:{port}/api/v1/widget/portfolio")
    print(f"  Performance: http://{host}:{port}/api/v1/widget/performance")
    print(f"  Live Data:   http://{host}:{port}/api/v1/portfolio/live")
    print(f"  yfinance:    {'available' if HAS_YF else 'NOT INSTALLED - using cost prices'}")
    print(f"Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
