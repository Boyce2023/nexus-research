# Nexus Research System — Package Overview

## 这是什么

一套基于Claude Code构建的多智能体股票研究操作系统，从覆盖→淘汰→推荐→跟踪全链路自动化，内置质量控制和规则执法层。

核心设计理念：**先淘汰再推荐**。系统的目的不是找到更多标的，而是用严格的方法论把不该买的排除掉。

## 系统组成

```
nexus-package/
├── core/                    # 架构定义 + 工作流配置
├── skills/                  # 15个可复用的分析技能模块
├── output-spec/             # 推荐输出标准格式 + 分发pipeline
├── scripts/                 # 导出/部署工具
└── README.md
```

## 方法论核心

### 10步标准化研究流程
1. 一句话核心问题 → 2. 全供应链映射 → 3. 需求验证 → 4. 供给约束评估 →
5. 类比攻防法 → 6. 共识检查 → 7. 熊方压力测试 → 8. 淘汰 →
9. 入场催化剂 → 10. 最终判断

### 16个分析框架 (F1-F16)
覆盖估值、供需、周期、竞争格局、管理层、新技术可信度等维度。每个框架有明确触发条件和标准输出物。

### 规则执法层 (4级)
- **Constitutional** (5条): 准确性/Bear Case硬门/SSOT/矛盾处理/Agent验证
- **Statutory** (18条): 每个session可见的强制规则
- **Operational Triggers** (22条): WHEN→THEN→VERIFY自动触发
- **Advisory** (~180条): 积累的行为纠正知识库

### 质量评分体系 (7维度)
RE(25%) + KQI(15%) + DSQ(25%) + SC(10%) + SNR(10%) + CPS(5%) + RPR(10%)

## 输出接口

系统产出遵循 `output-spec/recommendation-schema.json`:
- 每条推荐包含: thesis + bear_case + catalysts + valuation + metadata
- 4个硬门自动验证后才允许发布
- 支持雪球长文、短帖、API JSON三种输出格式

## 技术栈

- **Runtime**: Claude Code (Anthropic CLI)
- **数据**: Yahoo Finance API + AkShare(A股) + Bloomberg(可选)
- **存储**: 文件系统 (JSON/YAML/Markdown)
- **并行**: 最多10个Sub-agent同时研究
- **Skills**: 自定义SKILL.md prompt模块化设计

## 部署方式

1. 安装Claude Code CLI
2. 将本package放入 `~/.claude/` 对应位置
3. 配置CLAUDE.md全局指令
4. 初始化Truth Store (空模板)
5. 开始研究第一个标的

详见 `scripts/export.sh` 了解完整文件映射。

## 合作模式

### Mode 1: 方法论授权
合作方获得完整方法论包（本package），用自己的数据和分析师团队运行。我方提供：
- 系统部署支持
- 方法论培训
- 季度方法论升级

### Mode 2: 推荐产出
我方持续运行系统，产出标准化推荐（recommendation-schema.json），合作方负责分发。我方提供：
- 持续研究覆盖（5-15条活跃推荐）
- 催化剂驱动的实时更新
- 季报后24小时内更新
- 完整bear case和kill condition

### Mode 1+2 组合（推荐）
合作方获得方法论理解（透明度+可信度），同时接收持续推荐产出（recurring value）。方法论公开建立品牌信任，推荐产出建立付费关系。
