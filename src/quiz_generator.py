"""
quiz_generator.py - 试卷生成模块
结合 RAG 检索与 LLM API，根据当日考点生成试卷和答案
LLM 调用逻辑封装在 llm_client.py，支持 Claude 和 DeepSeek
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List

from src.llm_client import call_llm
from src.planner import get_day_topics
from src.vector_store import (
    query_collection,
    TEXTBOOK_COLLECTION,
    QUESTION_BANK_COLLECTION,
)

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
CONFIG_PATH = PROJECT_ROOT / "config.json"


def _load_config() -> dict:
    """加载学科配置文件"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    # 默认配置（兜底）
    return {
        "subject": {"name": "专业课", "code": "", "exam_type": "考研"},
        "exam_constraints": {"no_calculator": False, "additional_notes": ""},
    }


def _build_prompts():
    """根据 config.json 动态构建 system prompt"""
    cfg = _load_config()
    subject = cfg["subject"]
    constraints = cfg["exam_constraints"]

    subject_full = f"{subject['name']}"
    if subject["code"]:
        subject_full = f"{subject['name']}（{subject['code']}{subject['name']}）"
    exam_type = subject.get("exam_type", "考研")

    # 计算器约束段落（条件渲染）
    calculator_block = ""
    if constraints.get("no_calculator", False):
        calculator_block = f"""
【重要】{exam_type}不允许使用计算器，因此：
- 严禁出现需要复杂数值计算的题目（如多位数乘除、开方、三角函数查表等）
- 优先用字母符号推导和论证（如 $E_n = n^2h^2/8ml^2$ 这类代数推导）
- 若必须涉及数值，请直接在题目中给出关键中间量或最终结果（如"已知经计算 $\\lambda = 1.226/\\sqrt{{V}}$ nm，V=100V 时 $\\lambda \\approx 0.123$ nm"），让考生侧重物理意义的判断而非算术运算
- 侧重考查概念辨析、公式推导、物理图像和逻辑论证，而非数字计算能力
"""
    extra_notes = constraints.get("additional_notes", "")
    if extra_notes:
        calculator_block += f"\n【附加要求】{extra_notes}\n"

    quiz_prompt = f"""你是一位严格的{exam_type}命题专家，专注于{subject_full}方向。
请根据提供的【今日考纲考点】、【课本相关内容】和【题库参考】，生成一份精简的每日小试卷。

要求：
1. 题量精简但题型全覆盖，具体为：
   - 选择题：2题（单选，考查基本概念）
   - 简答/简算题：2题（考查理解与基本推导）
   - 综合题：1题（考查综合分析与推导能力）
2. 题目需紧扣今日考纲考点，难度贴近{exam_type}真题
3. 使用规范的学术用语，公式用 LaTeX 格式
4. 每道题标注分值（总分约50分）{calculator_block}
5. 输出格式为 Markdown"""

    answer_prompt = f"""你是一位经验丰富的{subject['name']}教师。
请为以下试卷生成完整的参考答案与详细解析。

要求：
1. 每道题给出标准答案
2. 附带解题思路和关键知识点解析
3. 指出常见错误和易混淆的概念
4. 公式推导需写出关键步骤
5. 输出格式为 Markdown"""

    # Answer 的约束提示（条件渲染）
    if constraints.get("no_calculator", False):
        answer_prompt += f"""

【重要】{exam_type}不允许使用计算器，因此解析时：
- 以字母符号推导和论证为主，清晰展示代数变形与物理逻辑
- 避免冗长的数值计算；如确需数值，只给出代入公式后的关键一步和最终结果，跳过中间算术过程
- 重点讲清物理图像、公式含义和推导思路，而非数字运算"""

    return quiz_prompt, answer_prompt


# 模块加载时构建 prompt（后续可改为按需刷新）
QUIZ_SYSTEM_PROMPT, ANSWER_SYSTEM_PROMPT = _build_prompts()


def retrieve_context(topics: List[str], top_k: int = 5) -> dict:
    """根据考点关键词从向量库检索相关内容"""
    query_text = "；".join(topics)

    textbook_results = query_collection(TEXTBOOK_COLLECTION, query_text, top_k=top_k)
    question_results = query_collection(QUESTION_BANK_COLLECTION, query_text, top_k=top_k)

    return {
        "textbook_context": textbook_results,
        "question_context": question_results,
    }


def format_context(context: dict) -> str:
    """将检索到的上下文格式化为 Prompt 文本"""
    parts = []

    parts.append("【课本相关内容】")
    for item in context["textbook_context"]:
        parts.append(f"[来源: {item['source']}]\n{item['text']}\n")

    parts.append("\n【题库参考】")
    for item in context["question_context"]:
        parts.append(f"[来源: {item['source']}]\n{item['text']}\n")

    return "\n".join(parts)


def generate_quiz(day: int):
    """生成指定天数的试卷和答案"""
    print(f"\n{'='*50}")
    print(f"  生成第 {day} 天的试卷")
    print(f"{'='*50}")

    # 获取当天考点
    topics = get_day_topics(day)
    print(f"  今日考点: {', '.join(topics)}")

    # RAG 检索
    print("  正在检索相关资料...")
    context = retrieve_context(topics)
    context_text = format_context(context)

    # 组装试卷生成 Prompt
    topics_text = "\n".join(f"  - {t}" for t in topics)
    quiz_prompt = f"【今日考纲考点】\n{topics_text}\n\n{context_text}"

    # 生成试卷
    print("  正在生成试卷...")
    quiz_content = call_llm(QUIZ_SYSTEM_PROMPT, quiz_prompt)

    # 生成答案
    print("  正在生成参考答案...")
    answer_prompt = f"以下是今天的试卷内容，请生成参考答案：\n\n{quiz_content}"
    answer_content = call_llm(ANSWER_SYSTEM_PROMPT, answer_prompt)

    # 保存文件
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")

    quiz_path = OUTPUT_DIR / f"day{day:02d}_{date_str}_试卷.md"
    answer_path = OUTPUT_DIR / f"day{day:02d}_{date_str}_答案.md"

    quiz_header = f"# 第 {day} 天 每日小试卷\n\n**考点**: {', '.join(topics)}\n\n---\n\n"
    answer_header = f"# 第 {day} 天 参考答案与解析\n\n---\n\n"

    with open(quiz_path, "w", encoding="utf-8") as f:
        f.write(quiz_header + quiz_content)

    with open(answer_path, "w", encoding="utf-8") as f:
        f.write(answer_header + answer_content)

    print(f"\n  试卷已保存: {quiz_path}")
    print(f"  答案已保存: {answer_path}")
    print("  完成!")
