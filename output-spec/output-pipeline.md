# Nexus → 雪球 Output Pipeline

## 产出流程

```
研究系统(research workstream)
    ↓ 完成10步流程 + 通过Quality Gate
    ↓
Recommendation Object (recommendation-schema.json)
    ↓ 自动验证: bear_case_gate + consensus_check + source_verified + catalyst_dated
    ↓
Output Buffer (待发布队列)
    ↓ 人工最终确认 (Buwen 1-click approve/reject/edit)
    ↓
Distribution API → 雪球
```

## 产出节点（什么时候生成推荐）

| 触发事件 | 产出类型 | 时效 |
|---------|---------|------|
| 新标的完成10步评估 | 新建推荐 (long/short/avoid) | 当日 |
| 催化剂兑现/失败 | 更新推荐 (修改conviction/方向) | 4小时内 |
| 季报发布 | 更新推荐 (earnings review) | 24小时内 |
| bear case触发kill条件 | 紧急退出推荐 | 立即 |
| 定期review日期到期 | 确认/更新/关闭推荐 | 当日 |

## 质量关卡（系统自动执行，不依赖人记得）

每条推荐发布前必须通过4个硬门：

1. **Bear Case Gate**: `max_downside_pct > -20%` → 不允许发布positive推荐
2. **Consensus Check**: `sell_side_consensus = "15/15看多"` → 自动标记"共识已price in"警告
3. **Source Verification**: 所有数字有`confidence_sources`条目 → 否则标"估算"
4. **Catalyst Dating**: 至少1个催化剂有具体`expected_date` → 否则不发

## 输出格式适配

### 雪球长文格式
```
标题: {display.headline}
正文:
  第一段: {display.summary_cn}
  核心逻辑: {thesis.core_arguments} 展开
  供给侧: {thesis.supply_side_logic}
  风险: {bear_case.scenarios} 表格化
  催化剂: {catalysts} 时间线
  估值: {valuation} 关键假设
标签: {display.tags}
```

### 雪球短帖格式（催化剂触发时快速更新）
```
标题: {ticker} — {catalyst.event}结果: {if_positive/if_negative}
正文: 2-3句结论 + 行动建议 + 下次review日期
```

### API JSON格式（如雪球提供技术对接）
直接推送 recommendation-schema.json 对象

## 版本管理

- 每条推荐有唯一`id`，更新时生成新版本（保留历史）
- 历史推荐可追溯：什么时候发的、什么时候更新的、最终结果如何
- 结果回填：推荐发出后跟踪6个月收益率，回填到metadata
- 这是scorecard RPR维度的数据源

## 容量规划

| 指标 | 预期 |
|------|------|
| 活跃推荐数 | 5-15条同时存在 |
| 新增频率 | 2-4条/月 |
| 更新频率 | 5-10次/月（催化剂/季报/review） |
| 关闭频率 | 1-3条/月 |
| 覆盖市场 | US + HK + A-share |
| 覆盖行业 | 核能/SMR/DC电力/LiDAR/机器人/A股主题 |
