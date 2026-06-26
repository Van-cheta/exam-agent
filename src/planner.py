"""
planner.py - 考纲解析与复习计划生成模块
读取 syllabus.txt，按各部分考试占比加权分配天数，输出 JSON 格式复习计划
占比高的部分分到更多天（每天考点少、复习更细）；占比低的部分天数少
"""

import json
import math
import re
from pathlib import Path
from typing import List, Dict

PROJECT_ROOT = Path(__file__).parent.parent
SYLLABUS_PATH = PROJECT_ROOT / "data" / "syllabus.txt"
PLAN_PATH = PROJECT_ROOT / "output" / "study_plan.json"

# 匹配部分标记行，如 "# ===== 第一部分：量子力学基础（约25%）====="
SECTION_PATTERN = re.compile(
    r"第[一二三四五六七八九十\d]+部分[：:]\s*(.+?)[（(]\s*约?\s*(\d+)\s*%\s*[）)]"
)


def parse_syllabus(syllabus_path: str = None) -> List[Dict]:
    """
    解析考纲文件，按"部分"分组。
    返回 [{"name": 部分名, "weight": 占比, "topics": [考点,...]}, ...]
    部分标记行格式：# ===== 第X部分：名称（约N%）=====
    其余非注释非空行视为该部分下的考点。
    """
    path = Path(syllabus_path) if syllabus_path else SYLLABUS_PATH
    if not path.exists():
        raise FileNotFoundError(f"考纲文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    sections: List[Dict] = []
    current: Dict = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("#"):
            m = SECTION_PATTERN.search(line)
            if m:
                # 保存上一个部分
                if current is not None:
                    sections.append(current)
                current = {
                    "name": m.group(1).strip(),
                    "weight": int(m.group(2)),
                    "topics": [],
                }
            continue

        # 普通行 = 考点
        if current is None:
            # 考纲开头没有部分标记的考点，归入"其他"
            current = {"name": "其他", "weight": 0, "topics": []}
        current["topics"].append(line)

    if current is not None:
        sections.append(current)

    return sections


def _alloc_days(sections: List[Dict], total_days: int) -> List[int]:
    """按各部分占比加权分配天数，保证每部分至少 1 天，总和等于 total_days"""
    total_weight = sum(s["weight"] for s in sections) or 1

    # 初始按占比取整（每部分至少 1 天）
    alloc = [max(1, round(total_days * s["weight"] / total_weight)) for s in sections]

    # 调整总和：多了从占比最小的部分减，少了加到占比最大的部分
    while sum(alloc) > total_days and len(alloc) > 1:
        idx = min(range(len(sections)), key=lambda i: (sections[i]["weight"], -alloc[i]))
        if alloc[idx] > 1:
            alloc[idx] -= 1
        else:
            break
    while sum(alloc) < total_days:
        idx = max(range(len(sections)), key=lambda i: sections[i]["weight"])
        alloc[idx] += 1

    return alloc


def generate_plan(total_days: int = 30, syllabus_path: str = None) -> Dict:
    """
    按各部分考试占比加权分配天数，生成复习计划。
    返回格式: {"total_days": N, "total_topics": M, "sections": [...], "days": [...]}
    """
    sections = parse_syllabus(syllabus_path)
    if not sections or not any(s["topics"] for s in sections):
        raise ValueError("考纲文件为空或没有考点，无法生成计划")

    alloc = _alloc_days(sections, total_days)
    total_topics = sum(len(s["topics"]) for s in sections)

    plan = {
        "total_days": total_days,
        "total_topics": total_topics,
        "sections": [
            {
                "name": s["name"],
                "weight": s["weight"],
                "topic_count": len(s["topics"]),
                "days": a,
            }
            for s, a in zip(sections, alloc)
        ],
        "days": [],
    }

    # 各部分内：考点均分到该部分的天数
    day = 1
    for section, n_days in zip(sections, alloc):
        topics = section["topics"]
        if not topics:
            continue
        per_day = math.ceil(len(topics) / n_days)
        for d in range(n_days):
            start = d * per_day
            end = min(start + per_day, len(topics))
            day_topics = topics[start:end]
            if day_topics:
                plan["days"].append({
                    "day": day,
                    "section": section["name"],
                    "weight": section["weight"],
                    "topics": day_topics,
                })
                day += 1

    return plan


def save_plan(plan: Dict):
    """将复习计划保存为 JSON 文件"""
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PLAN_PATH, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"  复习计划已保存至: {PLAN_PATH}")


def load_plan() -> Dict:
    """加载已有的复习计划"""
    if not PLAN_PATH.exists():
        raise FileNotFoundError("复习计划不存在，请先执行 --plan 生成计划")
    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_day_topics(day: int) -> List[str]:
    """获取指定天数的考点列表"""
    plan = load_plan()
    for entry in plan["days"]:
        if entry["day"] == day:
            return entry["topics"]
    raise ValueError(f"计划中没有第 {day} 天的安排（共 {len(plan['days'])} 天）")
