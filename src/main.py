"""
main.py - CLI 入口
提供命令行接口：--build-db / --plan / --day N
"""

import argparse
import json
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.file_parser import scan_folder, parse_file
from src.vector_store import (
    build_collection,
    add_to_collection,
    reset_db,
    TEXTBOOK_COLLECTION,
    QUESTION_BANK_COLLECTION,
)
from src.planner import generate_plan, save_plan, load_plan
from src.quiz_generator import generate_quiz


DATA_DIR = PROJECT_ROOT / "data"


def cmd_build_db(use_ocr: bool = False):
    """构建本地向量数据库"""
    reset_db()  # 每次构建前清空旧库，避免索引损坏

    print("\n[1/2] 解析课本文件夹...")
    textbook_docs = scan_folder(str(DATA_DIR / "textbooks"), use_ocr=use_ocr)

    print("\n[2/2] 解析题库文件夹...")
    question_docs = scan_folder(str(DATA_DIR / "question_banks"), use_ocr=use_ocr)

    if not textbook_docs and not question_docs:
        print("\n[错误] 未找到任何文件，请先将课本放入 data/textbooks/，题库放入 data/question_banks/")
        return

    print("\n正在构建向量数据库...")
    if textbook_docs:
        build_collection(TEXTBOOK_COLLECTION, textbook_docs)
    if question_docs:
        build_collection(QUESTION_BANK_COLLECTION, question_docs)

    print("\n向量数据库构建完成!")


def cmd_plan(days: int):
    """生成复习计划"""
    print(f"\n正在生成 {days} 天复习计划...")
    plan = generate_plan(total_days=days)
    save_plan(plan)

    print(f"\n  计划概览：共 {plan['total_topics']} 个考点，分配到 {len(plan['days'])} 天")
    for entry in plan["days"][:5]:
        print(f"    第{entry['day']:2d}天: {', '.join(entry['topics'][:3])}{'...' if len(entry['topics']) > 3 else ''}")
    if len(plan["days"]) > 5:
        print(f"    ... (共 {len(plan['days'])} 天)")


def cmd_generate(day: int):
    """生成指定天数的试卷"""
    generate_quiz(day)


def cmd_gen_syllabus(source_path: str):
    """从考纲文件调用 LLM 自动生成 syllabus.txt"""
    from src.syllabus_generator import generate_syllabus
    if not Path(source_path).exists():
        print(f"[错误] 文件不存在: {source_path}")
        return
    generate_syllabus(source_path)


def cmd_add_file(file_path: str, collection: str):
    """导入单个文件到指定向量库（增量，不重建整个库）"""
    if collection == "textbooks":
        col_name = TEXTBOOK_COLLECTION
    elif collection == "question_banks":
        col_name = QUESTION_BANK_COLLECTION
    else:
        print(f"[错误] --to 必须是 textbooks 或 question_banks")
        return

    p = Path(file_path)
    if not p.exists():
        print(f"[错误] 文件不存在: {file_path}")
        return

    print(f"\n导入文件: {p.name}")
    print(f"目标向量库: {col_name}")

    # 单文件导入默认开启 OCR（parse_pdf 内部会智能跳过已有文字层的页）
    content = parse_file(str(p), use_ocr=True)
    if not content.strip():
        print(f"[错误] 无法提取文本（可能是扫描版且 OCR 失败）")
        return

    print(f"提取文本: {len(content)} 字符")
    docs = [{"source": p.name, "content": content}]
    add_to_collection(col_name, docs)
    print(f"\n导入完成!")


def main():
    parser = argparse.ArgumentParser(
        description="考研辅助 Agent - 每日试卷生成工具（支持全学科）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python src/main.py --gen-syllabus "data/考纲.pdf"   从考纲文件调用API自动生成 syllabus.txt
  python src/main.py --build-db          构建向量数据库（默认开启OCR，首次使用必须执行）
  python src/main.py --build-db --no-ocr 构建数据库但跳过OCR（仅处理有文字层的PDF）
  python src/main.py --add-file "path/to/file.pdf" --to textbooks
                                         导入单个文件到指定向量库（增量）
  python src/main.py --plan              生成30天复习计划
  python src/main.py --plan --days 45    生成45天复习计划
  python src/main.py --day 1             生成第1天的试卷和答案
        """,
    )

    parser.add_argument("--gen-syllabus", type=str, help="从考纲文件(PDF等)调用API自动生成 syllabus.txt")
    parser.add_argument("--build-db", action="store_true", help="构建/更新本地向量数据库")
    parser.add_argument("--no-ocr", action="store_true", help="构建数据库时跳过OCR（仅处理有文字层的PDF）")
    parser.add_argument("--add-file", type=str, help="导入单个文件到向量库（增量，不重建）")
    parser.add_argument("--to", type=str, choices=["textbooks", "question_banks"],
                        help="--add-file 的目标向量库（不指定则按路径自动判断）")
    parser.add_argument("--plan", action="store_true", help="解析考纲并生成复习计划")
    parser.add_argument("--days", type=int, default=30, help="复习总天数（默认30天）")
    parser.add_argument("--day", type=int, help="生成第N天的试卷和答案")

    args = parser.parse_args()

    if not any([args.build_db, args.plan, args.day, args.add_file, args.gen_syllabus]):
        parser.print_help()
        return

    if args.gen_syllabus:
        cmd_gen_syllabus(args.gen_syllabus)
    elif args.build_db:
        cmd_build_db(use_ocr=not args.no_ocr)
    elif args.add_file:
        # 自动判断目标库（未指定 --to 时按路径关键词判断）
        collection = args.to
        if collection is None:
            fp = args.add_file.lower()
            if "textbook" in fp or "课本" in fp or "教材" in fp:
                collection = "textbooks"
            elif "question" in fp or "题库" in fp or "试题" in fp or "习题" in fp:
                collection = "question_banks"
            else:
                print("[错误] 无法自动判断目标库，请用 --to textbooks 或 --to question_banks 指定")
                return
        cmd_add_file(args.add_file, collection)
    elif args.plan:
        cmd_plan(args.days)
    elif args.day:
        cmd_generate(args.day)


if __name__ == "__main__":
    main()
