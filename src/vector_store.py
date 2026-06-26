"""
vector_store.py - 本地向量数据库模块
使用 sentence-transformers + numpy 构建和查询向量库
课本和题库分别独立存储，用余弦相似度检索
"""

import os
import ssl
import pickle
from pathlib import Path
from typing import List, Dict

# 修复 Windows 下 SSL 证书验证失败 + 使用国内镜像加速下载
ssl._create_default_https_context = ssl._create_unverified_context
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import httpx
httpx._config.DEFAULT_CIPHERS = "ALL"
_original_client_init = httpx.Client.__init__
def _patched_client_init(self, *args, **kwargs):
    kwargs.setdefault("verify", False)
    _original_client_init(self, *args, **kwargs)
httpx.Client.__init__ = _patched_client_init

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = str(PROJECT_ROOT / "db")

# 文本切分参数
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100

# Collection 名称
TEXTBOOK_COLLECTION = "textbooks"
QUESTION_BANK_COLLECTION = "question_banks"

# 全局单例模型
_model = None


def _get_model() -> SentenceTransformer:
    """懒加载 sentence-transformers 模型（单例）"""
    global _model
    if _model is None:
        print("  加载 Embedding 模型: all-MiniLM-L6-v2 ...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def reset_db():
    """彻底清空数据库"""
    import shutil
    if os.path.exists(DB_PATH):
        shutil.rmtree(DB_PATH)
    os.makedirs(DB_PATH, exist_ok=True)


def _collection_path(name: str) -> Path:
    """返回某个 Collection 的存储文件路径"""
    return Path(DB_PATH) / f"{name}.pkl"


def split_documents(documents: List[Dict[str, str]]) -> List[Dict]:
    """将文档列表切分为小块，保留来源信息"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", ".", " "],
    )
    chunks = []
    for doc in documents:
        texts = splitter.split_text(doc["content"])
        for i, text in enumerate(texts):
            chunks.append({
                "text": text,
                "source": doc["source"],
            })
    return chunks


def build_collection(collection_name: str, documents: List[Dict[str, str]]):
    """构建向量库：切分文本 → 生成 embedding → 存为 pickle 文件"""
    model = _get_model()

    chunks = split_documents(documents)
    if not chunks:
        print(f"  [警告] {collection_name} 没有可用的文本块")
        return

    print(f"  正在生成 {len(chunks)} 个文本块的向量...")

    # 分批生成 embedding
    batch_size = 64
    all_embeddings = []
    for i in range(0, len(chunks), batch_size):
        batch_texts = [c["text"] for c in chunks[i:i + batch_size]]
        batch_vecs = model.encode(batch_texts, show_progress_bar=False)
        all_embeddings.append(batch_vecs)

    embeddings = np.vstack(all_embeddings).astype(np.float32)

    # 存到文件
    data = {
        "chunks": chunks,
        "embeddings": embeddings,
    }
    path = _collection_path(collection_name)
    with open(path, "wb") as f:
        pickle.dump(data, f)

    file_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"  [完成] {collection_name}: {len(chunks)} 块, {file_mb:.1f} MB")


def _load_collection(collection_name: str) -> dict:
    """从文件加载向量库"""
    path = _collection_path(collection_name)
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def query_collection(collection_name: str, query_text: str, top_k: int = 5) -> List[Dict]:
    """
    余弦相似度检索：输入查询文本，返回 top-k 相关片段
    """
    model = _get_model()
    data = _load_collection(collection_name)

    if data is None:
        print(f"  [错误] 向量库 '{collection_name}' 不存在，请先执行 --build-db")
        return []

    chunks = data["chunks"]
    embeddings = data["embeddings"]  # shape: (N, dim)

    # 查询向量
    query_vec = model.encode([query_text], show_progress_bar=False).astype(np.float32)

    # 余弦相似度
    query_norm = query_vec / (np.linalg.norm(query_vec, axis=1, keepdims=True) + 1e-10)
    doc_norms = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10)
    scores = (query_norm @ doc_norms.T).flatten()  # shape: (N,)

    # Top-K
    k = min(top_k, len(scores))
    top_indices = np.argsort(scores)[::-1][:k]

    results = []
    for idx in top_indices:
        results.append({
            "text": chunks[idx]["text"],
            "source": chunks[idx]["source"],
        })
    return results


def add_to_collection(collection_name: str, documents: List[Dict[str, str]]) -> int:
    """
    增量添加文档到已有向量库（不重建整个库）。
    返回新增的文本块数。
    """
    model = _get_model()
    chunks = split_documents(documents)
    if not chunks:
        print(f"  [警告] 没有可提取的文本块")
        return 0

    print(f"  正在生成 {len(chunks)} 个文本块的向量...")
    batch_size = 64
    all_embeddings = []
    for i in range(0, len(chunks), batch_size):
        batch_texts = [c["text"] for c in chunks[i:i + batch_size]]
        batch_vecs = model.encode(batch_texts, show_progress_bar=False)
        all_embeddings.append(batch_vecs)
    new_embeddings = np.vstack(all_embeddings).astype(np.float32)

    # 加载现有库并追加（不存在则新建）
    data = _load_collection(collection_name)
    if data is None:
        old_count = 0
        data = {"chunks": chunks, "embeddings": new_embeddings}
    else:
        old_count = len(data["chunks"])
        data["chunks"].extend(chunks)
        data["embeddings"] = np.vstack([data["embeddings"], new_embeddings])

    with open(_collection_path(collection_name), "wb") as f:
        pickle.dump(data, f)

    print(f"  [完成] {collection_name}: {old_count} -> {len(data['chunks'])} 块（新增 {len(chunks)}）")
    return len(chunks)


def list_collections() -> Dict[str, int]:
    """返回各向量库的文本块数量，用于查看现状"""
    result = {}
    for name in [TEXTBOOK_COLLECTION, QUESTION_BANK_COLLECTION]:
        data = _load_collection(name)
        result[name] = len(data["chunks"]) if data else 0
    return result
