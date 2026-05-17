# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ATE (Automated Test Equipment) data analysis AI Agent built on the ReAct (Reasoning + Acting) loop pattern. Uses an LLM (DeepSeek by default) to autonomously analyze semiconductor chip test data from CSV/XLSX files, producing diagnostic reports about yield, persistent failures, and cross-round chip tracking. All user-facing output is in Chinese.

## Commands

```bash
# Setup
pip3 install -r requirements.txt
cp .env.example .env  # then edit .env to set LLM_API_KEY

# Run agent (one-shot default analysis)
bash run.sh
# or directly:
python3 ate_agent.py

# Run with custom request
bash run.sh "对比QC和FT轮次的数据差异"
python3 ate_agent.py --request "找出多轮持续fail的芯片"

# Interactive (REPL) mode
bash run.sh -i
python3 ate_agent.py --interactive

# Standalone parser report (no LLM needed)
python3 ate_parser.py

# Adjust max ReAct iterations
python3 ate_agent.py --max-steps 20
```

`run.sh` auto-creates `.venv`, installs deps, loads `.env`, and validates `LLM_API_KEY` before running.

## Architecture

Three-layer design, each in its own file:

1. **`ate_agent.py`** — Agent orchestration. `LLM` class wraps the OpenAI client. `run_agent()` implements the ReAct loop: sends messages to LLM, parses `[工具: name]` actions from responses via regex, executes tools, feeds observations back. Enforces a mandatory analysis flow with quality gates — refuses `[最终报告]` if required tools were skipped. Writes report to `ATE分析报告_Agent版.md`.

2. **`ate_agent_tools.py`** — Six tool classes (`ListDataFiles`, `GetSummaryStats`, `AnalyzeFailItems`, `CompareFiles`, `FindPersistentFails`, `TrackChipAcrossRounds`), each with an `execute()` method. All delegate to `ATEParser`. Module instantiates a shared `ATEParser()` at import time.

3. **`ate_parser.py`** — Data parsing engine. `ATEParser` class reads `summary.xlsx` (via pandas) for yield/Bin data and CSV files (custom row/col sparse-matrix reader, not pandas) for test results. Key methods: `parse_summary()`, `parse_test_data()`, `find_persistent_fails()`, `get_chip_results()`. Test item names are cleaned by stripping `Main.` prefix and removing noise tokens like `Collection`, `funcTestDescriptor`.

## Key Domain Concepts

- **Cross-round tracking**: All CSV files represent the **same batch of 215 chips** tested across multiple rounds (FT_R0, QC_R0, QC_R1, QC_R2). The same `PART_ID` in different files refers to the same physical chip. Chip counts must NOT be summed across rounds.
- **Persistent fail analysis** (`find_persistent_fails`): The core value-add — identifies chips that fail the same test item across multiple rounds, distinguishing sporadic test noise from genuine hardware defects.
- **Mandatory analysis flow**: `get_summary_stats` → `list_data_files` → `analyze_fail_items` (per file) → `find_persistent_fails` (mandatory) → `track_chip_across_rounds` → `compare_files` → final report. The agent enforces this via quality gates in `run_agent()`.

## Configuration

Environment variables (set in `.env`):
- `LLM_API_KEY` — Required. API key for the LLM service.
- `LLM_BASE_URL` — Default: `https://api.deepseek.com`
- `LLM_MODEL` — Default: `deepseek-chat`
- `ATE_DATA_DIR` — Default: `./data`

## CSV Data Format

CSV files are transposed wide tables: a "Test Name" row followed by spec rows (Number, Low, High, Unit), then chip data rows. Each chip row has metadata columns (PART_ID, HARD_BIN, SOFT_BIN, PART_FLG) followed by test values. Fail detection compares values against Low/High spec limits.

<!-- superpowers-zh:begin (do not edit between these markers) -->
# Superpowers-ZH 中文增强版

本项目已安装 superpowers-zh 技能框架（20 个 skills）。

## 核心规则

1. **收到任务时，先检查是否有匹配的 skill** — 哪怕只有 1% 的可能性也要检查
2. **设计先于编码** — 收到功能需求时，先用 brainstorming skill 做需求分析
3. **测试先于实现** — 写代码前先写测试（TDD）
4. **验证先于完成** — 声称完成前必须运行验证命令

## 可用 Skills

Skills 位于 `.claude/skills/` 目录，每个 skill 有独立的 `SKILL.md` 文件。

- **brainstorming**: 在任何创造性工作之前必须使用此技能——创建功能、构建组件、添加功能或修改行为。在实现之前先探索用户意图、需求和设计。
- **chinese-code-review**: 中文 review 沟通参考——话术模板、分级标注（必须修复/建议修改/仅供参考）、国内团队常见反模式应对。仅在用户显式 /chinese-code-review 时调用，不要根据上下文自动触发。
- **chinese-commit-conventions**: 中文 commit 与 changelog 配置参考——Conventional Commits 中文适配、commitlint/husky/commitizen 中文模板、conventional-changelog 中文配置。仅在用户显式 /chinese-commit-conventions 时调用，不要根据上下文自动触发。
- **chinese-documentation**: 中文文档排版参考——中英文空格、全半角标点、术语保留、链接格式、中文文案排版指北约定。仅在用户显式 /chinese-documentation 时调用，不要根据上下文自动触发。
- **chinese-git-workflow**: 国内 Git 平台配置参考——Gitee、Coding.net、极狐 GitLab、CNB 的 SSH/HTTPS/凭据/CI 接入差异与镜像同步配置。仅在用户显式 /chinese-git-workflow 时调用，不要根据上下文自动触发。
- **dispatching-parallel-agents**: 当面对 2 个以上可以独立进行、无共享状态或顺序依赖的任务时使用
- **executing-plans**: 当你有一份书面实现计划需要在单独的会话中执行，并设有审查检查点时使用
- **finishing-a-development-branch**: 当实现完成、所有测试通过、需要决定如何集成工作时使用——通过提供合并、PR 或清理等结构化选项来引导开发工作的收尾
- **mcp-builder**: MCP 服务器构建方法论 — 系统化构建生产级 MCP 工具，让 AI 助手连接外部能力
- **receiving-code-review**: 收到代码审查反馈后、实施建议之前使用，尤其当反馈不明确或技术上有疑问时——需要技术严谨性和验证，而非敷衍附和或盲目执行
- **requesting-code-review**: 完成任务、实现重要功能或合并前使用，用于验证工作成果是否符合要求
- **subagent-driven-development**: 当在当前会话中执行包含独立任务的实现计划时使用
- **systematic-debugging**: 遇到任何 bug、测试失败或异常行为时使用，在提出修复方案之前执行
- **test-driven-development**: 在实现任何功能或修复 bug 时使用，在编写实现代码之前
- **using-git-worktrees**: 当需要开始与当前工作区隔离的功能开发或执行实现计划之前使用——创建具有智能目录选择和安全验证的隔离 git 工作树
- **using-superpowers**: 在开始任何对话时使用——确立如何查找和使用技能，要求在任何响应（包括澄清性问题）之前调用 Skill 工具
- **verification-before-completion**: 在宣称工作完成、已修复或测试通过之前使用，在提交或创建 PR 之前——必须运行验证命令并确认输出后才能声称成功；始终用证据支撑断言
- **workflow-runner**: 在 Claude Code / OpenClaw / Cursor 中直接运行 agency-orchestrator YAML 工作流——无需 API key，使用当前会话的 LLM 作为执行引擎。当用户提供 .yaml 工作流文件或要求多角色协作完成任务时触发。
- **writing-plans**: 当你有规格说明或需求用于多步骤任务时使用，在动手写代码之前
- **writing-skills**: 当创建新技能、编辑现有技能或在部署前验证技能是否有效时使用

## 如何使用

当任务匹配某个 skill 时，使用 `Skill` 工具加载对应 skill 并严格遵循其流程。绝不要用 Read 工具读取 SKILL.md 文件。

如果你认为哪怕只有 1% 的可能性某个 skill 适用于你正在做的事情，你必须调用该 skill 检查。
<!-- superpowers-zh:end -->
