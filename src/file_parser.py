"""
file_parser.py - 多格式文件解析模块
支持遍历文件夹，解析 PDF、DOCX、TXT、MD 格式文件
PDF 解析策略：pymupdf → pdfplumber → OCR（扫描版兜底）
OCR 引擎：RapidOCR（基于 onnxruntime，不依赖 PyTorch，中文识别质量好）
支持页级缓存与断点续传：中断后重跑只处理未完成的页
"""

import os
import re
import warnings

# 抑制无害警告
warnings.filterwarnings("ignore")

from pathlib import Path
from typing import List, Dict

from docx import Document

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}

# OCR 最大处理页数，防止超大文件跑太久
OCR_MAX_PAGES = 500
# OCR 渲染 DPI（大文件降低 DPI 加速）
OCR_DPI_DEFAULT = 200
OCR_DPI_LARGE = 150
LARGE_FILE_MB = 20

# OCR 页级缓存目录（断点续传：已 OCR 的页存为 txt，重跑时跳过）
PROJECT_ROOT = Path(__file__).parent.parent
OCR_CACHE_DIR = PROJECT_ROOT / "output" / ".ocr_cache"


def _format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _safe_cache_name(name: str) -> str:
    """把文件名转成安全的缓存目录名"""
    stem = Path(name).stem
    return re.sub(r"[^\w一-龥]", "_", stem)


# RapidOCR 全局单例
_rapidocr = None


def _get_rapidocr():
    """懒加载 RapidOCR（首次调用时下载模型，约 10MB）"""
    global _rapidocr
    if _rapidocr is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            print("    初始化 RapidOCR 引擎...")
            _rapidocr = RapidOCR()
        except ImportError:
            return None
    return _rapidocr


def _ocr_available() -> bool:
    """检查 RapidOCR 是否可用"""
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def _chinese_ratio(text: str) -> float:
    """计算中文字符占比，用于 OCR 质量检验"""
    if not text:
        return 0.0
    chinese = sum(1 for c in text if "一" <= c <= "鿿")
    return chinese / len(text)


def _ocr_pages(file_path: str, page_indices: List[int]) -> Dict[int, str]:
    """
    用 RapidOCR 识别 PDF 的指定页，支持页级缓存与断点续传。
    返回 {页码: 文本}。只有传入的页会被 OCR，其余页不动。
    """
    import fitz
    import numpy as np

    reader = _get_rapidocr()
    if reader is None or not page_indices:
        return {}

    cache_dir = OCR_CACHE_DIR / _safe_cache_name(Path(file_path).name)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 大文件降低 DPI 加速
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    dpi = OCR_DPI_LARGE if file_size_mb > LARGE_FILE_MB else OCR_DPI_DEFAULT

    doc = fitz.open(file_path)
    results = {}
    total = len(page_indices)

    for idx, i in enumerate(page_indices):
        cache_file = cache_dir / f"page_{i:04d}.txt"
        if cache_file.exists():
            results[i] = cache_file.read_text(encoding="utf-8")
            continue

        page = doc[i]
        pix = page.get_pixmap(dpi=dpi)
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        if img_array.shape[2] == 4:
            img_array = img_array[:, :, :3]  # RGBA -> RGB

        try:
            result, _ = reader(img_array)
            if result:
                texts = [item[1] for item in result]
                # RapidOCR 每项为 [box, text, score]，取置信度
                scores = [
                    float(item[2]) if len(item) > 2 and item[2] is not None else 1.0
                    for item in result
                ]
                page_text = "\n".join(texts)
                avg_score = sum(scores) / len(scores)
            else:
                page_text = ""
                avg_score = 0.0
        except Exception:
            page_text = ""
            avg_score = 0.0

        # 质量检验：防止乱码污染向量库
        cn_ratio = _chinese_ratio(page_text)
        if page_text and avg_score < 0.3 and cn_ratio < 0.1:
            # 置信度极低且几乎无中文 → 判定乱码，丢弃
            print(f"\n    [警告] 第{i + 1}页疑似乱码(置信度{avg_score:.2f},中文{cn_ratio:.0%})，已丢弃")
            page_text = ""
        elif page_text and avg_score < 0.5:
            print(f"\n    [提示] 第{i + 1}页识别质量一般(置信度{avg_score:.2f})，可能含图表/公式")

        cache_file.write_text(page_text, encoding="utf-8")
        results[i] = page_text

        if (idx + 1) % 5 == 0 or (idx + 1) == total:
            print(f"\r    OCR 进度: {idx + 1}/{total} 扫描页", end="", flush=True)

    doc.close()
    if total > 0:
        print()
    return results


def parse_pdf(file_path: str, use_ocr: bool = False) -> str:
    """
    解析 PDF，逐页智能处理：
    - 有文字层的页：直接提取（快，不走 OCR）
    - 无文字层的扫描页：用 RapidOCR 识别（需 use_ocr=True）
    混合型 PDF 也能完整提取，文字页不浪费 OCR。
    """
    import fitz

    doc = fitz.open(file_path)
    total = min(len(doc), OCR_MAX_PAGES)

    # 第一遍：逐页提取文字层，记录需 OCR 的页
    page_texts: Dict[int, str] = {}
    ocr_pages: List[int] = []
    for i in range(total):
        page_text = doc[i].get_text()
        if page_text and page_text.strip():
            page_texts[i] = page_text.strip()
        else:
            ocr_pages.append(i)
    doc.close()

    # 全部有文字层，直接返回（不触发 OCR）
    if not ocr_pages:
        return "\n".join(page_texts[i] for i in range(total))

    # 有扫描页：开启 OCR 时只 OCR 这些页（文字页保持原样）
    if use_ocr and _ocr_available():
        print(f"    检测到 {len(ocr_pages)} 个扫描页需 OCR（{total - len(ocr_pages)} 页已有文字层）")
        ocr_texts = _ocr_pages(file_path, ocr_pages)
        for i in ocr_pages:
            page_texts[i] = ocr_texts.get(i, "")
        return "\n".join(page_texts.get(i, "") for i in range(total))

    # 未开 OCR：返回已有的文字页（扫描页丢弃）
    if page_texts:
        return "\n".join(page_texts[i] for i in range(total))
    return ""


def parse_docx(file_path: str) -> str:
    """解析 Word 文档，提取段落文本"""
    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def parse_text(file_path: str) -> str:
    """解析纯文本文件（TXT / MD）"""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def parse_file(file_path: str, use_ocr: bool = False) -> str:
    """根据文件扩展名选择解析器，返回纯文本"""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return parse_pdf(file_path, use_ocr=use_ocr)
    elif ext in (".docx", ".doc"):
        return parse_docx(file_path)
    elif ext in (".txt", ".md"):
        return parse_text(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def scan_folder(folder_path: str, use_ocr: bool = False) -> List[Dict[str, str]]:
    """
    遍历文件夹，解析所有支持的文件。
    use_ocr: 是否启用OCR处理扫描版PDF（默认关闭，需手动加 --ocr 开启）
    返回列表，每项包含 source（文件名）和 content（文本内容）。
    """
    documents = []
    skipped_empty = []
    folder = Path(folder_path)

    if not folder.exists():
        print(f"[警告] 文件夹不存在: {folder_path}")
        return documents

    # 收集所有待解析文件
    files = sorted(
        [f for f in folder.rglob("*") if f.suffix.lower() in SUPPORTED_EXTENSIONS]
    )
    total = len(files)
    print(f"  发现 {total} 个文件，开始解析...\n")

    for idx, file_path in enumerate(files, 1):
        size_mb = file_path.stat().st_size / (1024 * 1024)
        print(f"  [{idx}/{total}] {file_path.name} ({_format_size(file_path.stat().st_size)})", end="", flush=True)

        if size_mb > LARGE_FILE_MB:
            print(f" [大文件]", end="")

        try:
            content = parse_file(str(file_path), use_ocr=use_ocr)
            if content.strip():
                documents.append({
                    "source": file_path.name,
                    "path": str(file_path),
                    "content": content,
                })
                print(f" -> 成功 ({len(content)} 字符)")
            else:
                skipped_empty.append(file_path.name)
                print(f" -> 跳过 (无文字层)")
        except Exception as e:
            print(f" -> 失败: {e}")

    print(f"\n  解析完成: 成功 {len(documents)} 个", end="")
    if skipped_empty:
        print(f", 跳过 {len(skipped_empty)} 个")
        if use_ocr and not _ocr_available():
            print(f"  (扫描版，但 RapidOCR 未安装: pip install rapidocr_onnxruntime)")
        elif not use_ocr:
            print(f"  (扫描版，加 --ocr 启用 OCR)")
    else:
        print()

    return documents
