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
import sys, os, json, re, logging, time
from datetime import datetime
from openai import OpenAI

# 上下文管理常量
MAX_OBSERVATION_CHARS = 8000   # 单次工具返回结果最大字符数
MAX_CONTEXT_CHARS = 120000     # 对话历史总字符数阈值（约对应 30K-40K token）

# ═══════════════════════════════════════════
# 日志配置
# ═══════════════════════════════════════════

def _setup_logging():
    level_name = os.getenv("ATE_LOG_LEVEL", "INFO").upper()
    console_level = getattr(logging, level_name, logging.INFO)

    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    # 日志文件: logs/ate_agent_20260522_143052.log
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"ate_agent_{timestamp}.log")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 终端: INFO及以上（可通过 ATE_LOG_LEVEL 调整）
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(console)

    # 文件: 全部记录DEBUG及以上
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s",
                                       datefmt="%H:%M:%S"))
    root.addHandler(fh)

    logging.info("日志文件: %s", log_file)
    return log_file

_log_file = _setup_logging()
log = logging.getLogger("ate_agent")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ═══════════════════════════════════════════
# LLM客户端
# ═══════════════════════════════════════════

LLM_TIMEOUT = 120  # 单次 LLM 调用超时秒数

class LLM:
    def __init__(self):
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            raise ValueError("LLM_API_KEY 环境变量未设置或为空，请 export LLM_API_KEY=你的密钥")
        self.client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
            timeout=LLM_TIMEOUT,
        )
        self.model = os.getenv("LLM_MODEL", "deepseek-chat")

    def chat(self, messages, max_retries=3):
        cleaned = []
        for m in messages:
            content = m['content']
            if isinstance(content, str):
                content = content.encode('utf-8', errors='replace').decode('utf-8')
            cleaned.append({'role': m['role'], 'content': content})

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                r = self.client.chat.completions.create(
                    model=self.model, messages=cleaned,
                    temperature=0.1, top_p=0.9
                )
                return r.choices[0].message.content
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                # 4xx 客户端错误（请求本身有误）不重试
                is_client_error = any(code in err_str for code in ('400', '401', '403', '404', '422'))
                if is_client_error or attempt >= max_retries:
                    break
                # 429 限流或 5xx 服务端错误，指数退避重试
                delay = 2 ** attempt
                log.warning("LLM 调用失败(第%d次)，%ds 后重试: %s", attempt + 1, delay, e)
                time.sleep(delay)

        raise RuntimeError(f"LLM调用失败(重试{max_retries}次后仍失败): {last_err}") from last_err

_llm = None

def _get_llm():
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm

# ═══════════════════════════════════════════
# Agent工具集 — 从ate_agent_tools.py导入
# ═══════════════════════════════════════════

from ate_agent_tools import (
    ListDataFiles,
    GetSummaryStats,
    AnalyzeFailItems,
    CompareFiles,
    FindPersistentFails,
    TrackChipAcrossRounds,
    ValidateData,
    GenerateCharts
)

tools = {
    "list_data_files": ListDataFiles(),
    "get_summary_stats": GetSummaryStats(),
    "analyze_fail_items": AnalyzeFailItems(),
    "compare_files": CompareFiles(),
    "find_persistent_fails": FindPersistentFails(),
    "track_chip_across_rounds": TrackChipAcrossRounds(),
    "validate_data": ValidateData(),
    "generate_charts": GenerateCharts(),
}

TOOL_DESCRIPTIONS = """
可用工具（每次思考后只能调用一个，得到结果后再思考下一步）：

1. validate_data
   描述: 【首先调用】校验ATE数据完整性，检查芯片数跨轮次一致性、chip_id缺失、测试项数量变化、异常哨兵值等
   参数: 无
   返回: 校验警告列表，数据完整性评估

2. list_data_files
   描述: 列出data目录下所有ATE数据文件及概要
   参数: 无
   返回: 文件名、测试类型、芯片数、测试项数

3. get_summary_stats
   描述: 获取整体良率汇总（从summary.xlsx）
   参数: 无
   返回: 总芯片数、PASS/FAIL数量、良率、Fail Bin分布

4. analyze_fail_items
   描述: 深入分析指定数据文件的fail项和边界值风险芯片
   参数: filename (字符串，如"WQ7037AXB_260508_QC_R0.csv")
   返回: 该文件的fail项详情、边界值风险芯片、TOP10 fail项及其规格、fail值、fail芯片的chip_id(硅ID)

5. compare_files
   描述: 对比多个ATE数据文件的关键指标
   参数: filenames (数组，如["FT_R0.csv", "QC_R0.csv"])
   返回: 各文件的芯片数、测试项数、fail数对比

6. find_persistent_fails
   描述: 【核心分析】找出在多个轮次中持续fail的芯片，以及fail测试项之间的关联关系（Jaccard共现分析）。
   参数: min_rounds (可选整数，默认2，至少在几轮中fail)
   返回: 持续fail芯片列表、每颗芯片的持续fail测试项及fail轮次、TOP持续fail测试项、测试项关联分析（共现关系高的项对）

7. track_chip_across_rounds
   描述: 追踪单颗芯片在所有轮次中的测试表现，查看它从FT→QC各轮次的pass/fail变化
   参数: chip_id (字符串，芯片的硅ID，如"11292")
   返回: 该芯片在各轮次的测试结果、fail项列表、是否有持续fail项

8. generate_charts
   描述: 生成分析图表（Fail项柱状图、良率饼图、良率趋势折线图），保存为PNG
   参数: 无
   返回: 图表文件路径列表，在报告中用 ![描述](路径) 引用
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

【测试流程】
- FT（初测校准）：对芯片进行初次测试和校准。可能有 FT_R0/R1/R2，R0是初测，R1/R2是复测。
- QC（加载FT校准值测试）：使用FT阶段校准值对芯片做质量验证。可能有 QC_R0/R1/R2，同上。
- 同一批芯片走一套 FT + QC 完整流程，FT 在前，QC 在后。

【复测规则】
- R1/R2是复测，可能是全量复测，也可能只复测之前fail的芯片。
- 复测pass即为pass。但R0 fail + R1 pass的芯片需关注——后续轮次未测试，稳定性不确定。
- FT和QC良率独立计算，不跨类型判定。

【芯片追踪】
- 同一颗芯片在各文件中的chip_id(硅ID)相同，例如chip_id=11510在FT_R0和QC_R0中是同一颗物理芯片。
- chip_id是芯片的硅ID(chip_id_1_l列)，不是PART_ID(顺序编号)。
- 不要用PART_ID追踪芯片，不同文件中同一PART_ID对应不同物理芯片。
- chip_id=0或负值的芯片，ID无法读取（通常是严重fail导致ID读不出），系统会回退到PART_ID做文件内标识，格式为"PART_50@文件名"，这类芯片无法跨文件追踪。
- 同一文件中同一chip_id可能被测量多次（复测），系统自动取最后一次测量为最终结果，并标注测量次数。
- 不要将各轮次当成独立批次，不要累加芯片数。

【持续fail判定】
- 在同一测试类型(FT或QC)内部判定持续fail，跨类型(FT+QC)不算持续fail。
- 持续fail的芯片更可能是硬件缺陷，复测pass的芯片可能是偶发测试噪声。
- 如果某测试类型只有一轮(如FT仅R0)，则R0的结果就是最终结果，R0 fail即为fail。查看 by_test_type 中 single_round=true 的 r0_fail_chips 和 r0_fail_test_items。

强制分析流程（必须按序执行，不许跳过）：

第零步：调 validate_data — 检查数据完整性，如有问题需在报告中说明
第一步：调 get_summary_stats — 看FT和QC各自的良率
第二步：调 list_data_files — 看有哪些FT和QC轮次
第三步：对每个有fail的轮次，调 analyze_fail_items — 深入分析fail项
第四步：【必须】调 find_persistent_fails — 分别找出FT内部和QC内部持续fail的芯片
  这是区分偶发fail和硬件缺陷的关键步骤，绝不能跳过！
  注意返回的 by_test_type 结构，FT和QC分别看。
  注意 attention_list 中的需关注芯片（R0 fail + R1 pass 但无后续数据）。
第五步：对find_persistent_fails返回的重点芯片，调 track_chip_across_rounds 深入追踪
  返回的 final_status 会标注 PASS/RETEST_PASS/FAIL 和不确定性。
第六步：如果有多个轮次，调 compare_files 做对比（同类型内或跨类型）
第七步：调 generate_charts — 生成图表（Fail柱状图、良率饼图、趋势折线图）
  返回的图片路径用 ![描述](路径) 嵌入最终报告。
第八步：综合所有数据输出最终报告

注意：第0、1、2、4步是强制的。第4步(find_persistent_fails)是核心价值所在。
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
- 最终报告必须包含以下章节：
  1. "FT分析" — FT各轮次良率、持续fail芯片、需关注芯片
  2. "QC分析" — QC各轮次良率、持续fail芯片、需关注芯片
  3. "需关注芯片清单" — R0 fail + 复测pass但无后续数据的芯片
  4. "跨轮次分析" — 持续fail芯片详情"""


def _truncate_observation(text, max_chars=MAX_OBSERVATION_CHARS):
    """截断工具返回结果，保留关键信息不撑爆上下文

    原理：LLM 推理不需要看每个芯片的完整数值列表。
    保留前部（通常包含汇总/摘要）和尾部（可能包含系统提示），
    中间截断并标注原始长度。
    """
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars // 4
    return (text[:head]
            + f"\n\n... [已截断，完整数据共 {len(text)} 字符，仅保留前后部分] ...\n\n"
            + text[-tail:])


def _estimate_context_chars(messages):
    """估算对话历史的总字符数"""
    return sum(len(m.get('content', '')) for m in messages)


def _compact_messages(messages, target_chars=MAX_CONTEXT_CHARS // 2):
    """压缩对话历史：将早期步骤的工具观察结果替换为简短摘要

    原理：ReAct 循环中，早期步骤的观察细节在后续推理中价值递减。
    保留 system prompt + 最后 4 轮交互的完整内容，
    中间的工具观察替换为一行摘要。
    """
    if len(messages) <= 6:
        return messages

    total = _estimate_context_chars(messages)
    if total <= MAX_CONTEXT_CHARS:
        return messages

    log.info("上下文过长(%d 字符)，开始压缩历史", total)

    # 始终保留：system prompt + 最后 4 条消息（2 轮交互）
    preserved_tail = 4
    result = []
    tail = messages[-preserved_tail:] if len(messages) > preserved_tail else messages[:]

    for m in messages[:-preserved_tail]:
        content = m.get('content', '')
        # 工具观察结果（user 角色，以"工具"开头）压缩为一行摘要
        if m['role'] == 'user' and content.startswith('工具 ') and len(content) > 500:
            first_line = content.split('\n')[0][:200]
            result.append({'role': m['role'], 'content': first_line + ' [历史数据已压缩]'})
        else:
            result.append(m)

    result.extend(tail)
    new_total = _estimate_context_chars(result)
    log.info("上下文压缩: %d → %d 字符", total, new_total)
    return result


def parse_action(response_text):
    """解析Agent输出，提取工具调用

    返回 (tool_name, params, parse_ok):
      parse_ok=True  — 参数解析成功（包括无参数的情况）
      parse_ok=False — 检测到工具调用但参数解析失败，需要提示LLM修正
    """
    # 匹配 [工具: xxx]，工具名允许字母、数字、下划线、连字符
    m = re.search(r'\[工具:\s*([\w-]+)\]', response_text)
    if not m:
        return None, None, True
    tool_name = m.group(1)

    # 收集 [工具: xxx] 之后、直到下一个标记或文本结尾的所有内容作为参数区
    after_match = response_text[m.end():]
    # 截断到下一个结构化标记
    param_region = re.split(r'\n\[(?:思考|工具|最终报告)', after_match, maxsplit=1)[0]

    # 去除 Markdown 代码围栏（LLM 经常用 ```json ... ``` 包裹）
    param_text = re.sub(r'^```(?:json)?\s*', '', param_region.strip())
    param_text = re.sub(r'\s*```\s*$', '', param_text.strip())
    param_text = param_text.strip()

    if not param_text:
        return tool_name, {}, True

    try:
        return tool_name, json.loads(param_text), True
    except json.JSONDecodeError as e:
        log.warning("工具 %s 参数JSON解析失败: %s, 原始: %r", tool_name, e, param_text[:200])
        return tool_name, {}, False


def run_agent(user_request, max_steps=15, messages=None, state=None, on_step=None):
    """运行ReAct Agent循环

    支持多轮对话：首次调用不传 messages 和 state；
    返回值中包含它们，传入后续调用即可追问。

    Args:
        user_request: 用户请求
        max_steps: 本次最大思考步数
        messages: 已有对话历史（多轮对话时传入）
        state: 已有状态 dict，含 called_tools/analyzed_files/all_data_files
        on_step: 步骤回调 on_step(step, max_steps, tool_name, info)

    Returns:
        (report, full_log, messages, state)
    """
    called_tools = state.get('called_tools', set()) if state else set()
    analyzed_files = state.get('analyzed_files', set()) if state else set()
    all_data_files = state.get('all_data_files', []) if state else []
    is_followup = messages is not None

    if messages is None:
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': f"用户请求：{user_request}\n\n请开始分析。一步步思考和调用工具。完成分析后输出 [最终报告]。"}
        ]
    else:
        messages.append({'role': 'user', 'content': f"用户追问：{user_request}\n\n你可以基于已有分析数据直接回答，也可以调用工具获取更多信息。完成回答后输出 [最终报告]。"})

    state = {
        'called_tools': called_tools,
        'analyzed_files': analyzed_files,
        'all_data_files': all_data_files,
    }
    full_log = []
    consecutive_idle = 0  # 连续无有效动作计数

    for step in range(max_steps):
        log.info("Step %d/%d 思考中...", step+1, max_steps)
        if on_step:
            on_step(step + 1, max_steps, None, '思考中...')

        # LLM 调用带异常恢复：上下文过长时压缩后重试
        try:
            response = _get_llm().chat(messages)
        except RuntimeError as e:
            log.warning("LLM 调用失败: %s", e)
            if 'context' in str(e).lower() or 'token' in str(e).lower() or 'length' in str(e).lower():
                log.info("疑似上下文过长，压缩后重试")
                messages = _compact_messages(messages)
                try:
                    response = _get_llm().chat(messages)
                except Exception as e2:
                    log.error("压缩后仍失败: %s", e2)
                    return f"LLM 调用失败（上下文过长）: {e2}", full_log, messages, state
            else:
                return f"LLM 调用失败: {e}", full_log, messages, state

        log.debug("Step %d response: %s", step+1, response)
        full_log.append(f"\n--- Step {step+1} ---\n{response}")
        log.info("Step %d/%d LLM 响应 (%d 字符)", step+1, max_steps, len(response))

        if '[最终报告]' in response:
            # 追问模式：跳过质量门控，直接输出
            if is_followup:
                report_start = response.index('[最终报告]')
                report = response[report_start + len('[最终报告]'):].strip()
                messages.append({'role': 'assistant', 'content': response})
                return report, full_log, messages, state

            # 首次分析：走质量门控
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
            messages.append({'role': 'assistant', 'content': response})

            # 报告结构完整性提示（不阻断，仅提醒）
            required_sections = ['FT分析', 'QC分析', '需关注芯片']
            missing_sections = [s for s in required_sections if s not in report]
            if missing_sections:
                log.warning("报告缺少章节: %s", missing_sections)
                messages.append({'role': 'user', 'content':
                    f"报告内容已收到，但建议补充以下章节使其更完整：{'、'.join(missing_sections)}。"
                    f"请直接输出补充后的完整 [最终报告]，无需重新调工具。"})
                # 给 LLM 一次补全机会，不消耗额外 max_steps
                try:
                    fix_response = _get_llm().chat(messages)
                    if '[最终报告]' in fix_response:
                        fix_start = fix_response.index('[最终报告]')
                        report = fix_response[fix_start + len('[最终报告]'):].strip()
                        messages.append({'role': 'assistant', 'content': fix_response})
                except Exception:
                    log.warning("报告补全调用失败，使用原始报告")

            return report, full_log, messages, state

        tool_name, params, parse_ok = parse_action(response)
        if tool_name is None:
            # 追问模式下，LLM 给出实质性回答但没调工具也没标记报告，直接返回
            if is_followup and len(response.strip()) > 50:
                messages.append({'role': 'assistant', 'content': response})
                return response.strip(), full_log, messages, state

            consecutive_idle += 1
            if consecutive_idle >= 3:
                log.warning("连续 %d 步无有效动作，强制格式提示", consecutive_idle)
                messages.append({'role': 'assistant', 'content': response})
                messages.append({'role': 'user', 'content':
                    '你已连续多步未调用工具。请严格按照以下格式操作：\n'
                    '调用工具: [工具: 工具名]\\n{"参数名": "参数值"}\n'
                    '输出报告: [最终报告]\\n报告内容\n'
                    '如果已有足够信息，请直接输出 [最终报告]。'})
                consecutive_idle = 0  # 重置，给一次机会
            else:
                messages.append({'role': 'assistant', 'content': response})
                messages.append({'role': 'user', 'content': '请继续分析。如需调工具，请用 [工具: 工具名] 格式。如已有足够信息，请输出 [最终报告]。'})
            continue

        # 参数解析失败时提示 LLM 修正格式，避免工具无参数执行崩溃
        if not parse_ok:
            consecutive_idle += 1
            messages.append({'role': 'assistant', 'content': response})
            messages.append({'role': 'user', 'content':
                f'工具 {tool_name} 的参数JSON格式有误，请检查后重新调用。'
                f'正确格式示例：[工具: {tool_name}]\n{{"参数名": "参数值"}}'})
            continue

        log.info("Step %d/%d 调用工具: %s", step+1, max_steps, tool_name)
        if on_step:
            on_step(step + 1, max_steps, tool_name, f'调用 {tool_name}')
        consecutive_idle = 0  # 有效工具调用，重置空转计数

        if tool_name in tools:
            tool = tools[tool_name]
            try:
                if params:
                    result = tool.execute(**params)
                else:
                    result = tool.execute()

                # 工具执行成功且未返回 error，才计入 called_tools
                if not isinstance(result, dict) or 'error' not in result:
                    called_tools.add(tool_name)

                observation = json.dumps(result, ensure_ascii=False, indent=2)
                observation = _truncate_observation(observation)

                hint = ""
                if tool_name == 'list_data_files':
                    all_data_files = [f['filename'] for f in result.get('files', [])]
                    hint = f"\n\n【系统提示】共{len(all_data_files)}个文件。接下来请对每个有fail的文件调用analyze_fail_items，然后必须调用find_persistent_fails做跨轮次分析。"
                    hint += f"\n文件列表: {', '.join(all_data_files)}"
                elif tool_name == 'analyze_fail_items':
                    # 只有非错误结果才计入 analyzed_files
                    filename = params.get('filename', '')
                    if filename and (not isinstance(result, dict) or 'error' not in result):
                        analyzed_files.add(filename)
                        remaining = [f for f in all_data_files if f not in analyzed_files]
                        if remaining:
                            hint = f"\n\n【系统提示】已分析 {filename}。还剩 {len(remaining)} 个文件: {', '.join(remaining)}"
                        else:
                            hint = "\n\n【系统提示】所有文件已分析完毕！接下来⚠️必须调用 find_persistent_fails 做跨轮次持续fail分析，这是核心步骤！"
                elif tool_name == 'find_persistent_fails':
                    # 将结果传给 GenerateCharts，避免重复计算
                    if not isinstance(result, dict) or 'error' not in result:
                        tools['generate_charts']._persistent_fails_data = result
                    hint = "\n\n【系统提示】跨轮次分析完成。如果发现了持续fail芯片，建议用 track_chip_across_rounds 追踪重点芯片。然后综合所有数据输出最终报告。"
                elif tool_name == 'track_chip_across_rounds':
                    hint = "\n\n【系统提示】芯片追踪完成。如需追踪更多芯片继续调用，否则可以综合所有数据输出最终报告。"

                if hint:
                    observation += hint

            except Exception as e:
                log.warning("工具 %s 执行异常: %s", tool_name, e)
                observation = f"工具执行错误: {e}"
        else:
            observation = f"未知工具: {tool_name}，可用工具: {', '.join(tools.keys())}"

        full_log.append(f"[观察] {tool_name} 返回: {observation[:600]}")
        log.debug("工具 %s 返回 (%d 字符)", tool_name, len(observation))

        # 同步 state
        state['called_tools'] = called_tools
        state['analyzed_files'] = analyzed_files
        state['all_data_files'] = all_data_files

        messages.append({'role': 'assistant', 'content': response})
        messages.append({'role': 'user', 'content': f"工具 {tool_name} 返回结果:\n{observation}"})

        # 上下文管理：超出阈值时压缩历史
        messages = _compact_messages(messages)

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

    response = _get_llm().chat(messages + [{'role': 'user', 'content': final_prompt}])
    full_log.append(f"\n--- Final ---\n{response}")
    messages.append({'role': 'assistant', 'content': response})

    if '[最终报告]' in response:
        report_start = response.index('[最终报告]')
        return response[report_start + len('[最终报告]'):].strip(), full_log, messages, state
    return response, full_log, messages, state


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='ATE数据分析Agent (ReAct)')
    parser.add_argument('--request', '-r', help='分析请求，如"分析B2024-0321批次"')
    parser.add_argument('--interactive', '-i', action='store_true', help='交互模式')
    parser.add_argument('--max-steps', type=int, default=15, help='最大思考步数')

    args = parser.parse_args()

    if args.interactive:
        print("=" * 60)
        print("ATE数据分析Agent (ReAct循环) — 多轮对话模式")
        print("支持跨轮次追踪和持续fail分析")
        print("=" * 60)
        print("输入分析请求（输入 quit 退出，new 开始新对话）")
        print("示例：分析当前批次的ATE数据")
        print("示例：对比所有QC和FT轮次的数据")
        print("示例：找出多轮持续fail的芯片")
        print("示例：追踪芯片chip_id=11292在各轮次的表现")
        print("-" * 60)

        messages = None
        state = None
        turn_count = 0

        print("\n请输入分析请求开始分析(默认自动分析文件)：")

        while True:
            try:
                user_input = input("\n>>> ").strip()
                if user_input.lower() in ('quit', 'exit', 'q'):
                    break
                if not user_input:
                    if messages is None:
                        # 首次直接回车，用默认请求启动分析
                        user_input = "分析当前批次的ATE测试数据，重点关注fail芯片，输出诊断报告"
                        print(f"[系统] 使用默认请求：{user_input}")
                    else:
                        continue
                if user_input.lower() == 'new':
                    messages = None
                    state = None
                    turn_count = 0
                    print("[系统] 已重置对话，请输入新的分析请求：")
                    continue

                if messages is not None:
                    print("\n[Agent] 基于已有分析，回答追问...\n")
                else:
                    print("\n[Agent] 正在分析...\n")

                def _print_step(step, max_steps, tool_name, info):
                    if tool_name:
                        print(f"  [{step}/{max_steps}] {info}", flush=True)
                    else:
                        print(f"  [{step}/{max_steps}] {info}", end='', flush=True)

                report, log, messages, state = run_agent(
                    user_input, args.max_steps, messages, state, on_step=_print_step)
                turn_count += 1
                print("\n" + "=" * 60)
                print("[最终报告]")
                print(report)
                print("=" * 60)
                if turn_count == 1:
                    print('\n[提示] 你可以继续追问（如"芯片#11531为什么fail？"），输入 new 开始新分析，输入 quit 退出')
                else:
                    print("\n[提示] 继续追问，或输入 new / quit")

            except KeyboardInterrupt:
                print("\n\n已中断")
                break

    else:
        request = args.request or "分析当前批次的ATE测试数据，重点关注fail的芯片，给出fail芯片的相关fail项数据，输出诊断报告"
        log.info("请求: %s", request)
        log.info("开始ReAct循环分析...")

        report, log, _, _ = run_agent(request, args.max_steps)

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
