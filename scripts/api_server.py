#!/usr/bin/env python3
"""
Nexus Recommendation API Server
供第三方平台（雪球/公众号）内嵌调用

Endpoints:
  GET  /api/v1/recommendations          — 获取所有活跃推荐
  GET  /api/v1/recommendations/<id>      — 获取单条推荐详情
  GET  /api/v1/recommendations/summary   — 获取推荐摘要（适合卡片展示）
  GET  /api/v1/portfolio/stats           — 获取组合统计数据
  GET  /api/v1/widget/card/<id>          — 获取可嵌入的HTML卡片
  GET  /api/v1/widget/portfolio          — 获取完整组合widget HTML
  GET  /api/v1/feed/rss                  — RSS订阅源

Usage:
  python api_server.py                   # 启动在 localhost:8899
  python api_server.py --port 8899       # 指定端口
  python api_server.py --host 0.0.0.0    # 对外开放

部署方式:
  - 本地开发: python api_server.py
  - 生产: 部署到 Railway/Render/Fly.io (免费tier够用)
  - 雪球接入: 提供API地址，他们用iframe或API调用
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json, os, sys
from pathlib import Path
from datetime import datetime
import urllib.parse

BASE = Path(__file__).parent.parent
PUBLISHED = BASE / "output-buffer" / "published"
PORT = int(os.environ.get("PORT", 8899))


def load_all_recs():
    recs = []
    for f in sorted(PUBLISHED.glob("*.json"), reverse=True):
        with open(f) as fp:
            recs.append(json.load(fp))
    return recs


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

        elif path.startswith("/api/v1/widget/card/"):
            rec_id = path.split("/")[-1]
            match = [r for r in recs if rec_id in r["id"] or rec_id.upper() in r["ticker"].upper()]
            if match:
                self._html(make_widget_card(match[0]))
            else:
                self._html("<p>Not found</p>", 404)

        elif path == "/api/v1/widget/portfolio":
            self._html(make_portfolio_widget(recs))

        elif path == "/api/v1/feed/rss":
            self._xml(make_rss(recs))

        elif path == "/" or path == "/docs":
            self._html("""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Nexus API</title>
<style>body{font-family:monospace;background:#0d1117;color:#c9d1d9;padding:40px;max-width:800px;margin:0 auto}
h1{color:#fff}a{color:#58a6ff}code{background:#161b22;padding:2px 6px;border-radius:3px}
.endpoint{margin:12px 0;padding:8px;background:#161b22;border-radius:4px}</style></head><body>
<h1>Nexus Research System API</h1>
<p>系统化股票研究推荐接口 · 供第三方平台内嵌</p>
<h2>Endpoints</h2>
<div class="endpoint"><code>GET</code> <a href="/api/v1/recommendations">/api/v1/recommendations</a> — 全部推荐(完整JSON)</div>
<div class="endpoint"><code>GET</code> <a href="/api/v1/recommendations/summary">/api/v1/recommendations/summary</a> — 推荐摘要(卡片用)</div>
<div class="endpoint"><code>GET</code> <a href="/api/v1/portfolio/stats">/api/v1/portfolio/stats</a> — 组合统计</div>
<div class="endpoint"><code>GET</code> <a href="/api/v1/widget/portfolio">/api/v1/widget/portfolio</a> — 可嵌入组合Widget(HTML)</div>
<div class="endpoint"><code>GET</code> /api/v1/widget/card/{ticker} — 单条推荐卡片Widget(HTML)</div>
<div class="endpoint"><code>GET</code> <a href="/api/v1/feed/rss">/api/v1/feed/rss</a> — RSS订阅源</div>
<h2>嵌入方式</h2>
<p>雪球/公众号/任何网站用 iframe 嵌入:</p>
<code>&lt;iframe src="http://YOUR_DOMAIN/api/v1/widget/portfolio" width="520" height="600"&gt;&lt;/iframe&gt;</code>
<p>或直接调API获取JSON渲染自己的UI。</p>
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
    print(f"Docs: http://{host}:{port}/docs")
    print(f"Widget: http://{host}:{port}/api/v1/widget/portfolio")
    print(f"Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
