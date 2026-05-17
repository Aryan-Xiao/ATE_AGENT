"""
ATE数据分析Agent — 基于ReAct循环的真正Agent版本

工作方式：
1. 用户输入分析需求（如"分析B2024-0321批次"）
2. Agent循环：思考→选择工具→执行→观察结果→再思考
3. 直到Agent得出结论，输出最终报告

核心能力：
- 跨轮次追踪：识别同一chip_id在不同轮次(FT_R0/QC_R0/QC_R1/QC_R2)中的表现
- 持续fail分析：找出多轮持续fail的芯片，区分偶发fail和硬件缺陷

用法：
  export LLM_API_KEY=你的密钥
  export LLM_BASE_URL=https://api.deepseek.com
  export LLM_MODEL=deepseek-chat
  python3 ate_agent.py
"""
import sys, os, json, re
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ═══════════════════════════════════════════
# LLM客户端
# ═══════════════════════════════════════════

class LLM:
    def __init__(self):
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            raise ValueError("LLM_API_KEY 环境变量未设置或为空，请 export LLM_API_KEY=你的密钥")
        self.client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        )
        self.model = os.getenv("LLM_MODEL", "deepseek-chat")

    def chat(self, messages):
        cleaned = []
        for m in messages:
            content = m['content']
            if isinstance(content, str):
                content = content.encode('utf-8', errors='replace').decode('utf-8')
            cleaned.append({'role': m['role'], 'content': content})
        try:
            r = self.client.chat.completions.create(
                model=self.model, messages=cleaned,
                temperature=0.1, top_p=0.9
            )
            return r.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"LLM调用失败(网络超时或API错误): {e}") from e

llm = LLM()

# ═══════════════════════════════════════════
# Agent工具集 — 从ate_agent_tools.py导入
# ═══════════════════════════════════════════

from ate_agent_tools import (
    ListDataFiles,
    GetSummaryStats,
    AnalyzeFailItems,
    CompareFiles,
    FindPersistentFails,
    TrackChipAcrossRounds
)

tools = {
    "list_data_files": ListDataFiles(),
    "get_summary_stats": GetSummaryStats(),
    "analyze_fail_items": AnalyzeFailItems(),
    "compare_files": CompareFiles(),
    "find_persistent_fails": FindPersistentFails(),
    "track_chip_across_rounds": TrackChipAcrossRounds(),
}

TOOL_DESCRIPTIONS = """
可用工具（每次思考后只能调用一个，得到结果后再思考下一步）：

1. list_data_files
   描述: 列出data目录下所有ATE数据文件及概要
   参数: 无
   返回: 文件名、测试类型、芯片数、测试项数

2. get_summary_stats
   描述: 获取整体良率汇总（从summary.xlsx）
   参数: 无
   返回: 总芯片数、PASS/FAIL数量、良率、Fail Bin分布

3. analyze_fail_items
   描述: 深入分析指定数据文件的fail项
   参数: filename (字符串，如"WQ7037AXB_260508_QC_R0.csv")
   返回: 该文件的fail项详情、TOP10 fail项及其规格、fail值、fail芯片的chip_id(硅ID)

4. compare_files
   描述: 对比多个ATE数据文件的关键指标
   参数: filenames (数组，如["FT_R0.csv", "QC_R0.csv"])
   返回: 各文件的芯片数、测试项数、fail数对比

5. find_persistent_fails
   描述: 【核心分析】找出在多个轮次中持续fail的芯片。同一测试项在≥2轮中fail的芯片会被标记为持续fail，这有助于区分偶发fail和真正的硬件缺陷。
   参数: min_rounds (可选整数，默认2，至少在几轮中fail)
   返回: 持续fail芯片列表、每颗芯片的持续fail测试项及fail轮次、TOP持续fail测试项

6. track_chip_across_rounds
   描述: 追踪单颗芯片在所有轮次中的测试表现，查看它从FT→QC各轮次的pass/fail变化
   参数: chip_id (字符串，芯片的硅ID，如"11292")
   返回: 该芯片在各轮次的测试结果、fail项列表、是否有持续fail项
"""

SYSTEM_PROMPT = f"""你是ATE（自动测试设备）芯片测试分析专家。你是一个通过ReAct循环工作的AI Agent。

你的工作方式：
1. 收到用户的分析请求
2. 思考需要什么信息来判断
3. 调用一个工具获取信息
4. 观察工具返回的结果
5. 重复2-4直到有足够信息做出结论
6. 输出最终分析报告

{TOOL_DESCRIPTIONS}

⚠️ 关键领域知识 — 必须理解：
这批数据是同一批215颗WQ7037AXB芯片的多次轮流测试：
- FT_R0: 出厂测试第0轮（初测）
- QC_R0: 质量确认第0轮
- QC_R1: 质量确认第1轮（复测）
- QC_R2: 质量确认第2轮（再复测）
同一颗芯片在各文件中的chip_id(硅ID)相同，例如chip_id=11292的芯片在FT_R0和QC_R0中是同一颗物理芯片。不要用PART_ID(顺序编号)追踪芯片，不同文件中同一PART_ID对应不同物理芯片。
不要将各轮次当成独立批次，不要累加芯片数。

强制分析流程（必须按序执行，不许跳过）：

第一步：调 get_summary_stats — 看整体良率和Fail Bin分布
第二步：调 list_data_files — 看有哪些数据文件和轮次
第三步：对每个有fail的轮次，调 analyze_fail_items — 深入分析fail项
第四步：【必须】调 find_persistent_fails — 找出跨轮次持续fail的芯片
  这是区分偶发fail和硬件缺陷的关键步骤，绝不能跳过！
第五步：对find_persistent_fails返回的重点芯片，调 track_chip_across_rounds 深入追踪
第六步：如果有多个轮次，调 compare_files 做对比
第七步：综合所有数据输出最终报告

注意：第1、2、4步是强制的。第4步(find_persistent_fails)是本次分析的核心价值所在。
如果跳过跨轮次追踪分析，报告将无法区分"测试噪声"和"真实硬件问题"，这是不合格的。

输出格式要求：
- 每次思考：用 [思考] 开头
- 调用工具：用 [工具: 工具名] 开头，参数放在下一行（JSON格式）
- 观察结果：工具返回的内容
- 最终报告：用 [最终报告] 开头

示例：
[思考] 我需要先看看整体数据概况。
[工具: get_summary_stats]

[思考] 整体良率93%，有15颗fail。现在需要看看有哪些轮次数据。
[工具: list_data_files]

[思考] 看到有FT_R0, QC_R0, QC_R1, QC_R2四个轮次。先分析FT_R0的fail详情。
[工具: analyze_fail_items]
{{"filename": "WQ7037AXB_200_260508_FT_R0.csv"}}

[思考] FT_R0有5个fail项。接下来必须做跨轮次追踪，找出哪些芯片是持续fail。
[工具: find_persistent_fails]

[思考] 发现3颗芯片在≥2轮中持续fail！重点追踪芯片chip_id=11292。
[工具: track_chip_across_rounds]
{{"chip_id": "11292"}}

重要规则：
- 一次只能调用一个工具，得到结果后才能调下一个
- 必须分析完所有需要的信息才能出最终报告
- find_persistent_fails是必调工具，不能跳过
- 如果工具返回错误，尝试换个工具或参数
- 所有结论必须引用数据来源
- 不确定的用"可能"、"建议确认"等措辞
- 用中文输出
- 如果只看了一两个文件就出报告，这是不合格的
- 最终报告中必须包含"跨轮次分析"章节，列出持续fail芯片及其详情"""


def parse_action(response_text):
    """解析Agent输出，提取工具调用"""
    m = re.search(r'\[工具:\s*(\w+)\](?:\n\s*(.+))?', response_text)
    if not m:
        return None, None
    tool_name = m.group(1)
    param_line = m.group(2)
    if param_line:
        try:
            return tool_name, json.loads(param_line.strip())
        except json.JSONDecodeError:
            return tool_name, {}
    return tool_name, {}


def run_agent(user_request, max_steps=15):
    """运行ReAct Agent循环"""

    called_tools = set()
    analyzed_files = set()
    all_data_files = []

    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f"用户请求：{user_request}\n\n请开始分析。一步步思考和调用工具。完成分析后输出 [最终报告]。"}
    ]

    full_log = []

    for step in range(max_steps):
        print(f"[Step {step+1}/{max_steps}] 思考中...")
        response = llm.chat(messages)
        full_log.append(f"\n--- Step {step+1} ---\n{response}")
        print(f"[Step {step+1}/{max_steps}] LLM 响应 ({len(response)} 字符)")

        if '[最终报告]' in response:
            missing = []
            if 'get_summary_stats' not in called_tools:
                missing.append("还没有获取整体良率汇总(get_summary_stats)")
            if 'list_data_files' not in called_tools:
                missing.append("还没有列出数据文件(list_data_files)")
            if 'find_persistent_fails' not in called_tools:
                missing.append("⚠️ 还没有做跨轮次持续fail分析(find_persistent_fails)！这是区分偶发fail和硬件缺陷的关键步骤")

            if all_data_files and not missing:
                unanalyzed = [f for f in all_data_files if f not in analyzed_files]
                if unanalyzed and len(analyzed_files) < len(all_data_files) // 2:
                    missing.append(f"还有{len(unanalyzed)}个文件未分析: {', '.join(unanalyzed[:3])}...")

            if missing:
                messages.append({'role': 'assistant', 'content': response})
                hint = ""
                if all_data_files and analyzed_files:
                    done = len(analyzed_files)
                    total = len(all_data_files)
                    hint = f"\n已分析{done}/{total}个文件。"
                    if 'find_persistent_fails' not in called_tools:
                        hint += "\n⚠️ 你还没有调用find_persistent_fails做跨轮次分析，这是必须的！"
                messages.append({'role': 'user', 'content':
                    f"你跳过了必要步骤：{'；'.join(missing)}。请先完成这些步骤再出最终报告。{hint}"})
                continue

            report_start = response.index('[最终报告]')
            report = response[report_start + len('[最终报告]'):].strip()
            return report, full_log

        tool_name, params = parse_action(response)
        if tool_name is None:
            messages.append({'role': 'assistant', 'content': response})
            messages.append({'role': 'user', 'content': '请继续分析。如需调工具，请用 [工具: 工具名] 格式。如已有足够信息，请输出 [最终报告]。'})
            continue

        called_tools.add(tool_name)
        print(f"[Step {step+1}/{max_steps}] 调用工具: {tool_name}...")

        if tool_name in tools:
            tool = tools[tool_name]
            try:
                if params:
                    result = tool.execute(**params)
                else:
                    result = tool.execute()
                observation = json.dumps(result, ensure_ascii=False, indent=2)

                hint = ""
                if tool_name == 'list_data_files':
                    all_data_files = [f['filename'] for f in result.get('files', [])]
                    hint = f"\n\n【系统提示】共{len(all_data_files)}个文件。接下来请对每个有fail的文件调用analyze_fail_items，然后必须调用find_persistent_fails做跨轮次分析。"
                    hint += f"\n文件列表: {', '.join(all_data_files)}"
                elif tool_name == 'analyze_fail_items':
                    filename = params.get('filename', '')
                    if filename:
                        analyzed_files.add(filename)
                        remaining = [f for f in all_data_files if f not in analyzed_files]
                        if remaining:
                            hint = f"\n\n【系统提示】已分析 {filename}。还剩 {len(remaining)} 个文件: {', '.join(remaining)}"
                        else:
                            hint = "\n\n【系统提示】所有文件已分析完毕！接下来⚠️必须调用 find_persistent_fails 做跨轮次持续fail分析，这是核心步骤！"
                elif tool_name == 'find_persistent_fails':
                    hint = "\n\n【系统提示】跨轮次分析完成。如果发现了持续fail芯片，建议用 track_chip_across_rounds 追踪重点芯片。然后综合所有数据输出最终报告。"
                elif tool_name == 'track_chip_across_rounds':
                    hint = "\n\n【系统提示】芯片追踪完成。如需追踪更多芯片继续调用，否则可以综合所有数据输出最终报告。"

                if hint:
                    observation += hint

            except Exception as e:
                observation = f"工具执行错误: {e}"
        else:
            observation = f"未知工具: {tool_name}，可用工具: {', '.join(tools.keys())}"

        full_log.append(f"[观察] {tool_name} 返回: {observation[:600]}")

        messages.append({'role': 'assistant', 'content': response})
        messages.append({'role': 'user', 'content': f"工具 {tool_name} 返回结果:\n{observation}"})

    # 超过最大步数，强制总结
    final_prompt = f"你已经分析了{max_steps}步。"
    missing = []
    if 'find_persistent_fails' not in called_tools:
        missing.append("未做跨轮次持续fail分析")
    if all_data_files:
        analyzed = len(analyzed_files)
        total = len(all_data_files)
        final_prompt += f"已分析{analyzed}/{total}个数据文件。"
    if missing:
        final_prompt += f"注意：{'；'.join(missing)}。请在报告中注明缺失的分析。"
    final_prompt += "请基于已有信息输出 [最终报告]。"

    response = llm.chat(messages + [{'role': 'user', 'content': final_prompt}])
    full_log.append(f"\n--- Final ---\n{response}")

    if '[最终报告]' in response:
        report_start = response.index('[最终报告]')
        return response[report_start + len('[最终报告]'):].strip(), full_log
    return response, full_log


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='ATE数据分析Agent (ReAct)')
    parser.add_argument('--request', '-r', help='分析请求，如"分析B2024-0321批次"')
    parser.add_argument('--interactive', '-i', action='store_true', help='交互模式')
    parser.add_argument('--max-steps', type=int, default=15, help='最大思考步数')

    args = parser.parse_args()

    if args.interactive:
        print("=" * 60)
        print("ATE数据分析Agent (ReAct循环)")
        print("支持跨轮次追踪和持续fail分析")
        print("=" * 60)
        print("输入分析请求（输入 quit 退出）")
        print("示例：分析当前批次的ATE数据")
        print("示例：对比所有QC和FT轮次的数据")
        print("示例：找出多轮持续fail的芯片")
        print("示例：追踪芯片chip_id=11292在各轮次的表现")
        print("-" * 60)

        while True:
            try:
                user_input = input("\n>>> ").strip()
                if user_input.lower() in ('quit', 'exit', 'q'):
                    break
                if not user_input:
                    continue

                print("\n[Agent] 正在分析...\n")
                report, log = run_agent(user_input, args.max_steps)
                print("\n" + "=" * 60)
                print("[最终报告]")
                print(report)
                print("=" * 60)

            except KeyboardInterrupt:
                print("\n\n已中断")
                break

    else:
        request = args.request or "分析当前批次的ATE测试数据，重点关注跨轮次持续fail的芯片，输出诊断报告"
        print(f"[Agent] 请求: {request}")
        print("[Agent] 开始ReAct循环分析...\n")

        report, log = run_agent(request, args.max_steps)

        print("\n" + "=" * 60)
        print("[最终报告]")
        print(report)
        print("=" * 60)

        output_file = 'ATE分析报告_Agent版.md'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"# ATE数据分析报告\n\n")
            f.write(report)
            f.write("\n\n---\n")
            f.write("## Agent分析日志\n\n")
            f.write("```\n")
            for entry in log:
                f.write(entry + "\n")
            f.write("```\n")
        print(f"\n报告已保存到 {output_file}")
