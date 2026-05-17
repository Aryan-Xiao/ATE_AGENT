# ATE 数据分析 Agent

基于 ReAct（Reasoning + Acting）循环的 AI Agent，自主分析半导体芯片 ATE 测试数据，自动定位良率问题、持续 fail 芯片与跨轮次异常追踪。

## 架构

```
┌─────────────────────────────────────────────────┐
│                  ate_agent.py                    │
│              ReAct Loop · LLM(DeepSeek)          │
│                                                  │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   │
│   │  思考     │──▶│  行动     │──▶│  观察     │   │
│   │ (Reason) │   │  (Act)   │   │(Observe) │   │
│   └──────────┘   └────┬─────┘   └────┬─────┘   │
│        ▲              │              │          │
│        └──────────────┘──────────────┘          │
│                    循环直到得出结论               │
└────────────────────────┬────────────────────────┘
                         │ 工具调用
┌────────────────────────▼────────────────────────┐
│              ate_agent_tools.py                  │
│                 6 个 Agent 工具                   │
│                                                  │
│  ListDataFiles  GetSummaryStats  AnalyzeFailItems│
│  CompareFiles   FindPersistentFails              │
│                       TrackChipAcrossRounds       │
└────────────────────────┬────────────────────────┘
                         │ 委托解析
┌────────────────────────▼────────────────────────┐
│                ate_parser.py                     │
│              ATE 数据解析引擎                     │
│                                                  │
│   summary.xlsx ──pandas──▶ 良率/Bin 数据         │
│   *.csv ──稀疏矩阵解析──▶ 测试结果              │
│                                                  │
│   find_persistent_fails()  get_chip_results()    │
│   parse_summary()  parse_test_data()             │
└─────────────────────────────────────────────────┘
```

## 快速开始

```bash
# 1. 安装依赖
pip3 install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY

# 3. 放入数据（summary.xlsx + CSV 文件到 data/ 目录）

# 4. 运行
bash run.sh
```

### 更多用法

```bash
# 指定分析问题
bash run.sh "对比QC和FT轮次的数据差异"
python3 ate_agent.py --request "找出多轮持续fail的芯片"

# 交互模式（REPL）
bash run.sh -i

# 调整最大推理轮次
python3 ate_agent.py --max-steps 20

# 无需 LLM 的独立数据报告
python3 ate_parser.py
```

## Agent 工具

Agent 在 ReAct 循环中按需调用以下工具，遵循强制分析流程与质量门控：

| 工具 | 说明 | 参数 |
|------|------|------|
| **ListDataFiles** | 列出 data 目录下所有 ATE 数据文件，返回文件名、测试类型(FT/QC)、轮次(R0/R1/R2)、芯片数、测试项数、fail 数 | 无 |
| **GetSummaryStats** | 获取 summary.xlsx 中的整体良率与 Fail Bin 分布 | 无 |
| **AnalyzeFailItems** | 深入分析指定文件的 fail 测试项，返回规格、fail 值及每颗 fail 芯片的 PART_ID | `filename` |
| **CompareFiles** | 对比多个数据文件的关键指标（芯片数、测试项数、fail 项数） | `filenames` (列表) |
| **FindPersistentFails** | 核心分析——找出在 ≥N 个轮次中同一测试项持续 fail 的芯片，区分偶发噪声与硬件缺陷 | `min_rounds` (默认 2) |
| **TrackChipAcrossRounds** | 追踪单颗芯片在所有轮次(FT_R0/QC_R0/QC_R1/QC_R2)的测试结果 | `chip_id` |

### 强制分析流程

```
get_summary_stats → list_data_files → analyze_fail_items(逐文件)
    → find_persistent_fails(必须) → track_chip_across_rounds
    → compare_files → 最终报告
```

Agent 拒绝在跳过必需工具时输出 `[最终报告]`，确保分析完整性。

## 实际成果

对 **WQ7037AXB** 批次 215 颗芯片的 4 轮测试数据（FT_R0 / QC_R0 / QC_R1 / QC_R2）分析：

- **整体良率**：93%（200 Pass / 15 Fail）
- **15 颗 fail 芯片精准定位**：每颗芯片的 fail 测试项、规格偏离值、PART_ID 均可追溯
- **持续 fail 分析**：识别出多轮同一测试项持续 fail 的芯片，区分偶发测试噪声与真实硬件缺陷
- **跨轮次追踪**：同一 PART_ID 在 FT → QC 各轮的表现对比，揭示退化趋势

## 技术栈

| 组件 | 技术 |
|------|------|
| Agent 框架 | ReAct 循环（自研，无框架依赖） |
| LLM | DeepSeek（默认），兼容 OpenAI API |
| 数据解析 | pandas（XLSX）+ 自研稀疏矩阵解析器（CSV） |
| 运行时 | Python 3.8+ |

## 项目目录

```
ATE_AGENT/
├── ate_agent.py              # ReAct Agent 主程序
├── ate_agent_tools.py        # 6 个 Agent 工具
├── ate_parser.py             # ATE 数据解析引擎
├── run.sh                    # 一键启动脚本
├── requirements.txt          # Python 依赖
├── .env.example              # 环境变量模板
├── .env                      # 环境变量（需自行创建）
├── data/                     # ATE 测试数据
│   ├── summary.xlsx          #   良率汇总
│   ├── WQ7037AXB_*_FT_R0.csv #   FT 轮次数据
│   ├── WQ7037AXB_*_QC_R0.csv #   QC R0 数据
│   ├── WQ7037AXB_*_QC_R1.csv #   QC R1 数据
│   └── WQ7037AXB_*_QC_R2.csv #   QC R2 数据
└── ATE分析报告_Agent版.md     # Agent 生成的分析报告
```

## 配置

环境变量（在 `.env` 中设置）：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_API_KEY` | LLM API 密钥（必填） | — |
| `LLM_BASE_URL` | LLM API 地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | 模型名称 | `deepseek-chat` |
| `ATE_DATA_DIR` | 数据目录 | `./data` |
