"""
syllabus_generator.py - 考纲自动生成模块
读取考纲文件（PDF/DOCX/TXT），调用 LLM API 提取考点并按考试占比组织，
自动生成 syllabus.txt，免去手动编写考纲文件
"""

import json
from pathlib import Path

from src.file_parser import parse_file
from src.llm_client import call_llm

PROJECT_ROOT = Path(__file__).parent.parent
SYLLABUS_PATH = PROJECT_ROOT / "data" / "syllabus.txt"
CONFIG_PATH = PROJECT_ROOT / "config.json"


def _load_config() -> dict:
    """加载学科配置文件"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "subject": {"name": "专业课", "code": "", "exam_type": "考研"},
    }


def _build_syllabus_prompt() -> str:
    """根据 config.json 动态构建考纲生成 prompt"""
    cfg = _load_config()
    subject = cfg["subject"]

    subject_full = f"{subject['name']}"
    if subject["code"]:
        subject_full = f"{subject['code']}{subject['name']}"
    exam_type = subject.get("exam_type", "考研")

    # 示例标题
    example_title = f"# {subject_full} 考试大纲"

    return f"""你是一位{subject_full}{exam_type}命题研究专家。
请阅读提供的【考纲原文】，提取全部考点，并按考试部分组织成考纲文件。

输出格式要求（严格遵循，便于程序解析）：
1. 文件开头用 # 写一行标题注释，如：{example_title}
2. 每个部分用一行注释标记，格式必须严格为：
   # ===== 第X部分：部分名称（约N%）=====
   其中 X 为中文数字（一、二、三...），N 为该部分在考试中的占比百分比（从考纲原文中读取，若无明确占比则按要点数量合理估算）。
3. 部分标记之下，每行写一个考点（简洁的考点名称，不要编号、不要解释、不要标点结尾）。
4. 每个部分之间空一行。
5. 只输出考纲内容本身，不要输出任何前言、解释或 Markdown 代码块标记。

示例：
{example_title}

# ===== 第一部分：量子力学基础（约25%）=====
微观粒子的波粒二象性与德布罗意关系
不确定性原理及其应用

# ===== 第二部分：原子结构（约20%）=====
氢原子薛定谔方程的求解与量子数
"""


SYLLABUS_SYSTEM_PROMPT = _build_syllabus_prompt()


def generate_syllabus(source_path: str, output_path: str = None) -> str:
    """
    读取考纲文件，调用 LLM 提取考点并按占比组织，生成 syllabus.txt。
    source_path: 考纲原文文件路径（PDF/DOCX/TXT/MD 均可）
    output_path: 输出路径，默认 data/syllabus.txt
    返回生成的考纲文本。
    """
    out = Path(output_path) if output_path else SYLLABUS_PATH

    print(f"\n读取考纲文件: {source_path}")
    # 考纲文件默认开启 OCR（若是扫描版考纲也能处理；文字版自动跳过 OCR）
    content = parse_file(source_path, use_ocr=True)
    if not content.strip():
        raise ValueError(f"无法从 {source_path} 提取文本，请检查文件")

    print(f"  提取文本: {len(content)} 字符")
    print("调用 LLM 提取考点并按考试占比组织考纲...")
    syllabus = call_llm(
        SYLLABUS_SYSTEM_PROMPT,
        f"【考纲原文】\n{content}",
        max_tokens=4096,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(syllabus.strip() + "\n")
    print(f"  考纲已保存至: {out}")
    print(f"  共 {len([l for l in syllabus.splitlines() if l.strip() and not l.startswith('#')])} 个考点")
    return syllabus
