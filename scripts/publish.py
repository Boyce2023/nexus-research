#!/usr/bin/env python3
"""
Nexus Recommendation Publisher
- Renders recommendation JSON → multiple output formats
- Tracks publication history and performance
- Generates static portfolio site

Usage:
  python publish.py approve <rec_id>        # Move from pending → published, render all formats
  python publish.py list                     # Show all pending recommendations
  python publish.py update <rec_id>         # Re-render after editing
  python publish.py performance             # Calculate returns for all published recs
  python publish.py site                    # Regenerate the full portfolio site
"""

import json, os, sys, shutil
from datetime import datetime, date
from pathlib import Path

BASE = Path(__file__).parent.parent
PENDING = BASE / "output-buffer" / "pending"
PUBLISHED = BASE / "output-buffer" / "published"
ARCHIVED = BASE / "output-buffer" / "archived"
SITE = BASE / "site"
PERF_LOG = BASE / "output-buffer" / "performance-log.json"


def load_rec(filepath):
    with open(filepath) as f:
        return json.load(f)


def render_xueqiu_markdown(rec):
    """Render recommendation as 雪球-style long post markdown"""
    lines = []
    lines.append(f"# {rec['display']['headline']}")
    lines.append("")
    lines.append(f"**方向**: {'做多' if rec['direction']=='long' else '做空' if rec['direction']=='short' else '回避'} | "
                 f"**确信度**: {rec['conviction'].upper()} | "
                 f"**目标价**: ${rec['valuation'].get('target_price', 'N/A')} ({rec['valuation'].get('upside_pct', 0):+.1f}%)")
    lines.append("")
    lines.append(f"> {rec['display']['summary_cn']}")
    lines.append("")

    # Thesis
    lines.append("## 核心逻辑")
    lines.append(f"**一句话**: {rec['thesis']['one_liner']}")
    lines.append("")
    for i, arg in enumerate(rec['thesis']['core_arguments'], 1):
        lines.append(f"{i}. {arg}")
    lines.append("")

    # Supply side
    lines.append("## 供给侧分析")
    lines.append(rec['thesis']['supply_side_logic'])
    lines.append("")

    # Edge
    if rec['thesis'].get('consensus_check'):
        cc = rec['thesis']['consensus_check']
        lines.append(f"**卖方共识**: {cc.get('sell_side_consensus', 'N/A')}")
        lines.append(f"**我的Edge**: {cc.get('edge_statement', 'N/A')}")
        lines.append("")

    # Bear case
    lines.append("## 风险与Bear Case")
    lines.append("")
    lines.append("| 情景 | 概率 | 下行 | 严重度 |")
    lines.append("|------|------|------|--------|")
    for s in rec['bear_case']['scenarios']:
        lines.append(f"| {s['description'][:40]}... | {s['probability']*100:.0f}% | {s['downside_pct']}% | {s['severity']}/10 |")
    lines.append("")
    lines.append(f"**概率加权下行**: {rec['bear_case']['probability_weighted_downside']}%")
    lines.append(f"**止损条件**: {rec['bear_case']['kill_condition']}")
    lines.append("")

    # Catalysts
    lines.append("## 催化剂时间线")
    lines.append("")
    for cat in rec['catalysts']:
        lines.append(f"- **{cat['expected_date']}** — {cat['event']} (影响: {cat['impact']})")
        lines.append(f"  - 兑现 → {cat['if_positive']}")
        lines.append(f"  - 落空 → {cat['if_negative']}")
    lines.append("")

    # Valuation
    lines.append("## 估值")
    v = rec['valuation']
    lines.append(f"方法: {v['methodology']} | 目标: ${v['target_price']} | 当前: ${v['current_price']} | 上行: {v['upside_pct']}%")
    lines.append("")
    lines.append("关键假设:")
    for a in v.get('key_assumptions', []):
        lines.append(f"- {a}")
    lines.append("")

    # Metadata
    lines.append("---")
    lines.append(f"*分析系统: Nexus Research System | 数据截止: {rec['metadata']['data_freshness']} | "
                 f"下次Review: {rec['metadata']['review_date']}*")
    lines.append("")
    lines.append(f"标签: {' '.join(['#'+t for t in rec['display']['tags']])}")

    return "\n".join(lines)


def render_wechat_markdown(rec):
    """Render as WeChat公众号 compatible markdown (simpler formatting)"""
    lines = []
    lines.append(f"{rec['display']['headline']}")
    lines.append("")
    lines.append(rec['display']['summary_cn'])
    lines.append("")
    lines.append(f"方向: {'做多' if rec['direction']=='long' else '做空' if rec['direction']=='short' else '回避'}")
    lines.append(f"确信度: {rec['conviction'].upper()}")
    lines.append(f"目标价: ${rec['valuation'].get('target_price', 'N/A')} (上行{rec['valuation'].get('upside_pct', 0):.1f}%)")
    lines.append("")
    lines.append("【核心逻辑】")
    for i, arg in enumerate(rec['thesis']['core_arguments'], 1):
        lines.append(f"{i}. {arg}")
    lines.append("")
    lines.append("【风险】")
    lines.append(f"概率加权下行: {rec['bear_case']['probability_weighted_downside']}%")
    lines.append(f"止损条件: {rec['bear_case']['kill_condition']}")
    lines.append("")
    lines.append("【催化剂】")
    for cat in rec['catalysts']:
        lines.append(f"· {cat['expected_date']} — {cat['event']}")
    lines.append("")
    lines.append(f"---\nNexus Research System | {rec['metadata']['data_freshness']}")
    return "\n".join(lines)


def render_site_card(rec):
    """Render as HTML card for portfolio site"""
    direction_class = rec['direction']
    direction_cn = {'long': '做多', 'short': '做空', 'avoid': '回避'}[rec['direction']]
    conviction_cn = {'high': '高', 'medium': '中', 'low': '低'}[rec['conviction']]

    checks = rec['metadata'].get('system_checks_passed', {})
    check_html = ""
    for k, v in checks.items():
        icon = "✓" if v else "✗"
        cls = "pass" if v else "fail"
        label = k.replace("_", " ").title()
        check_html += f'<span class="check {cls}">{icon} {label}</span>'

    scenarios_html = ""
    for s in rec['bear_case']['scenarios']:
        scenarios_html += f"<tr><td>{s['description'][:50]}</td><td>{s['probability']*100:.0f}%</td><td>{s['downside_pct']}%</td></tr>"

    catalysts_html = ""
    for cat in rec['catalysts']:
        catalysts_html += f"<li><strong>{cat['expected_date']}</strong> — {cat['event']} ({cat['impact']})</li>"

    return f"""
    <article class="rec-card {direction_class}" id="{rec['id']}">
      <header>
        <h2>{rec['display']['headline']}</h2>
        <div class="meta">
          <span class="ticker">${rec['ticker']}</span>
          <span class="direction {direction_class}">{direction_cn}</span>
          <span class="conviction">确信度: {conviction_cn}</span>
          <span class="target">目标 ${rec['valuation'].get('target_price', 'N/A')} ({rec['valuation'].get('upside_pct', 0):+.1f}%)</span>
        </div>
      </header>
      <section class="summary">
        <p>{rec['display']['summary_cn']}</p>
      </section>
      <section class="thesis">
        <h3>核心逻辑</h3>
        <p class="one-liner">"{rec['thesis']['one_liner']}"</p>
        <ul>{''.join(f"<li>{a}</li>" for a in rec['thesis']['core_arguments'])}</ul>
      </section>
      <section class="bear-case">
        <h3>Bear Case (概率加权: {rec['bear_case']['probability_weighted_downside']}%)</h3>
        <table><tr><th>情景</th><th>概率</th><th>下行</th></tr>{scenarios_html}</table>
        <p class="kill">止损: {rec['bear_case']['kill_condition']}</p>
      </section>
      <section class="catalysts">
        <h3>催化剂</h3>
        <ul>{catalysts_html}</ul>
      </section>
      <section class="checks">
        <h3>系统验证</h3>
        <div class="check-grid">{check_html}</div>
      </section>
      <footer>
        <span>数据截止: {rec['metadata']['data_freshness']}</span>
        <span>Review: {rec['metadata']['review_date']}</span>
        <span>框架: {', '.join(rec['metadata'].get('frameworks_applied', []))}</span>
      </footer>
    </article>"""


def generate_site():
    """Generate full static portfolio site from all published recommendations"""
    published_recs = []
    for f in sorted(PUBLISHED.glob("*.json"), reverse=True):
        published_recs.append(load_rec(f))

    cards_html = "\n".join(render_site_card(r) for r in published_recs)

    # Stats
    total = len(published_recs)
    long_count = sum(1 for r in published_recs if r['direction'] == 'long')
    short_count = sum(1 for r in published_recs if r['direction'] == 'short')
    avg_upside = sum(r['valuation'].get('upside_pct', 0) for r in published_recs) / max(total, 1)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nexus Research System — Portfolio</title>
<style>
:root {{ --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9; --accent: #58a6ff; --green: #3fb950; --red: #f85149; --yellow: #d29922; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; padding: 2rem; }}
.container {{ max-width: 1200px; margin: 0 auto; }}
header.site-header {{ text-align: center; margin-bottom: 3rem; padding: 2rem; border-bottom: 1px solid var(--border); }}
header.site-header h1 {{ font-size: 2rem; color: #fff; margin-bottom: 0.5rem; }}
header.site-header p {{ color: #8b949e; font-size: 0.9rem; }}
.stats {{ display: flex; gap: 2rem; justify-content: center; margin-top: 1.5rem; }}
.stat {{ text-align: center; }}
.stat .num {{ font-size: 1.5rem; font-weight: 700; color: var(--accent); }}
.stat .label {{ font-size: 0.75rem; color: #8b949e; text-transform: uppercase; }}
.methodology {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.5rem; margin-bottom: 2rem; }}
.methodology h2 {{ font-size: 1.1rem; margin-bottom: 0.8rem; color: #fff; }}
.methodology p {{ font-size: 0.85rem; color: #8b949e; }}
.rec-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; }}
.rec-card.long {{ border-left: 3px solid var(--green); }}
.rec-card.short {{ border-left: 3px solid var(--red); }}
.rec-card.avoid {{ border-left: 3px solid var(--yellow); }}
.rec-card header h2 {{ font-size: 1.2rem; color: #fff; margin-bottom: 0.5rem; }}
.meta {{ display: flex; gap: 1rem; flex-wrap: wrap; font-size: 0.8rem; }}
.meta span {{ padding: 2px 8px; border-radius: 4px; background: var(--bg); }}
.direction.long {{ color: var(--green); }}
.direction.short {{ color: var(--red); }}
.direction.avoid {{ color: var(--yellow); }}
.ticker {{ color: var(--accent); font-weight: 700; }}
section {{ margin-top: 1rem; }}
section h3 {{ font-size: 0.9rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }}
.one-liner {{ font-style: italic; color: var(--accent); margin-bottom: 0.5rem; }}
.summary p {{ font-size: 0.95rem; }}
ul {{ padding-left: 1.2rem; }}
li {{ margin-bottom: 0.3rem; font-size: 0.9rem; }}
table {{ width: 100%; font-size: 0.85rem; border-collapse: collapse; }}
th, td {{ padding: 0.4rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ color: #8b949e; font-weight: 600; }}
.kill {{ color: var(--red); font-size: 0.85rem; margin-top: 0.5rem; }}
.check-grid {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
.check {{ font-size: 0.75rem; padding: 2px 6px; border-radius: 3px; }}
.check.pass {{ background: #1b3d2a; color: var(--green); }}
.check.fail {{ background: #3d1b1b; color: var(--red); }}
footer {{ margin-top: 1rem; padding-top: 0.8rem; border-top: 1px solid var(--border); display: flex; gap: 1.5rem; font-size: 0.75rem; color: #8b949e; }}
.empty {{ text-align: center; padding: 4rem; color: #8b949e; }}
</style>
</head>
<body>
<div class="container">
  <header class="site-header">
    <h1>Nexus Research System</h1>
    <p>系统化股票研究 — 先淘汰再推荐 | 每条推荐含Bear Case硬门验证</p>
    <div class="stats">
      <div class="stat"><div class="num">{total}</div><div class="label">活跃推荐</div></div>
      <div class="stat"><div class="num">{long_count}L / {short_count}S</div><div class="label">多空</div></div>
      <div class="stat"><div class="num">{avg_upside:+.1f}%</div><div class="label">平均预期</div></div>
    </div>
  </header>

  <div class="methodology">
    <h2>方法论</h2>
    <p>10步标准化流程 | 16个分析框架 | 4级规则执法 | 22条自动触发检查<br>
    核心原则: Bear Case下行 &gt;20% = 不推荐建仓 (硬规则, 无例外) | 供给侧约束优先 | 先淘汰再推荐</p>
  </div>

  {"<div class='empty'>暂无发布的推荐</div>" if not published_recs else cards_html}
</div>
<script>
document.querySelectorAll('.rec-card header').forEach(h => {{
  h.style.cursor = 'pointer';
  h.addEventListener('click', () => {{
    const card = h.closest('.rec-card');
    card.querySelectorAll('section').forEach(s => {{
      s.style.display = s.style.display === 'none' ? 'block' : 'none';
    }});
  }});
}});
</script>
</body>
</html>"""

    site_path = SITE / "index.html"
    site_path.write_text(html, encoding='utf-8')
    return site_path


def cmd_approve(rec_id):
    """Approve a pending recommendation: move to published + render all formats"""
    # Find the file
    matches = list(PENDING.glob(f"*{rec_id}*"))
    if not matches:
        print(f"ERROR: No pending recommendation matching '{rec_id}'")
        print(f"Pending: {[f.stem for f in PENDING.glob('*.json')]}")
        return

    src = matches[0]
    rec = load_rec(src)

    # Move to published
    dst = PUBLISHED / src.name
    shutil.move(str(src), str(dst))
    print(f"[✓] Moved to published: {dst.name}")

    # Render formats
    xueqiu_md = render_xueqiu_markdown(rec)
    wechat_md = render_wechat_markdown(rec)

    # Save renders
    renders_dir = SITE / "recommendations"
    renders_dir.mkdir(exist_ok=True)

    (renders_dir / f"{rec['id']}_xueqiu.md").write_text(xueqiu_md, encoding='utf-8')
    (renders_dir / f"{rec['id']}_wechat.md").write_text(wechat_md, encoding='utf-8')
    print(f"[✓] Rendered: xueqiu markdown + wechat markdown")

    # Regenerate site
    site_path = generate_site()
    print(f"[✓] Site updated: {site_path}")
    print(f"\n--- Preview (雪球格式前3行) ---")
    print("\n".join(xueqiu_md.split("\n")[:5]))


def cmd_list():
    """List all pending recommendations"""
    pending = list(PENDING.glob("*.json"))
    published = list(PUBLISHED.glob("*.json"))

    print(f"=== Pending: {len(pending)} | Published: {len(published)} ===\n")

    if pending:
        print("PENDING (awaiting approval):")
        for f in sorted(pending):
            rec = load_rec(f)
            print(f"  [{rec['direction'].upper():5}] {rec['ticker']:8} — {rec['display']['headline']}")
            print(f"         conviction={rec['conviction']} target=${rec['valuation'].get('target_price','?')} bear={rec['bear_case']['probability_weighted_downside']}%")
    else:
        print("  (no pending recommendations)")

    if published:
        print(f"\nPUBLISHED:")
        for f in sorted(published):
            rec = load_rec(f)
            print(f"  [{rec['direction'].upper():5}] {rec['ticker']:8} — {rec['display']['headline']} (since {rec['metadata']['created_at'][:10]})")


def cmd_performance():
    """Calculate performance for all published recommendations"""
    print("Performance tracking requires price data.")
    print("Run: yf price <TICKER> for each published rec to get current prices.")
    print("\nPublished recommendations:")
    for f in sorted(PUBLISHED.glob("*.json")):
        rec = load_rec(f)
        target = rec['valuation'].get('target_price', 0)
        entry = rec['valuation'].get('current_price', 0)
        print(f"  {rec['ticker']:8} entry=${entry} target=${target} — need current price to calc P&L")


def cmd_site():
    """Regenerate portfolio site"""
    path = generate_site()
    print(f"[✓] Site generated: {path}")
    print(f"    Open: file://{path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "approve" and len(sys.argv) > 2:
        cmd_approve(sys.argv[2])
    elif cmd == "list":
        cmd_list()
    elif cmd == "performance":
        cmd_performance()
    elif cmd == "site":
        cmd_site()
    else:
        print(__doc__)
