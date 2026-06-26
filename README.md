# 考研辅助 Agent - 全学科通用

基于 RAG（检索增强生成）的考研每日试卷生成工具。读取本地课本和题库，结合考纲自动生成练习试卷与参考答案。**通过 `config.json` 配置文件适配任意学科**（如结构化学、高等数学、英语、政治等）。

## 功能

- 解析多格式文件（PDF、Word、TXT、Markdown）
- 逐页智能 OCR：有文字层的页直接提取，仅扫描页走 OCR（RapidOCR）
- OCR 质量检验：置信度+中文占比双重判断，乱码页自动丢弃并警告
- 调用 API 从考纲文件自动生成 `syllabus.txt`（无需手写考纲）
- 按考试占比加权生成复习计划（占比高的部分分配更多天）
- 本地向量检索（sentence-transformers + numpy 余弦相似度，无需外部数据库）
- 调用 Claude / DeepSeek API 智能出题（自动检测）
- 支持单个文件增量导入向量库
- Markdown 格式输出试卷与答案

## 快速开始

### 1. 安装依赖

```bash
cd kaoyan_agent-for_all
pip install -r requirements.txt
```

### 2. 配置学科信息

编辑 `config.json`，设置你的学科：

```json
{
  "subject": {
    "name": "结构化学",
    "code": "851",
    "exam_type": "考研"
  },
  "exam_constraints": {
    "no_calculator": true,
    "additional_notes": ""
  }
}
```

| 字段 | 说明 |
|------|------|
| `subject.name` | 学科名称（如"高等数学"、"英语"） |
| `subject.code` | 科目代码（如"851"、"301"，没有可留空） |
| `subject.exam_type` | 考试类型（默认"考研"） |
| `exam_constraints.no_calculator` | 是否禁止计算器（`true`/`false`，如化学/物理类通常为 true） |
| `exam_constraints.additional_notes` | 额外的命题约束或要求（可选） |

Prompt 会根据配置自动适配——例如 `no_calculator: true` 时会强调字母推导、禁止复杂数值计算；`no_calculator: false` 时则不添加该约束。

### 3. 配置 LLM

编辑 `.env` 文件，填入三行即可（`.env` 中已包含所有主流提供商的配置示例）：

```bash
LLM_API_KEY=sk-xxxxx                     # 你的 API Key
LLM_BASE_URL=https://api.deepseek.com    # 接口地址
LLM_MODEL=deepseek-chat                  # 模型名称
```

支持任意 OpenAI 兼容接口，详见[支持的 LLM](#支持的-llm)章节。

### 4. 准备资料

- 将课本文件放入 `data/textbooks/`（支持 pdf、docx、txt、md）
- 将题库文件放入 `data/question_banks/`
- 将考纲文件（PDF/DOCX/TXT）放入 `data/`，用 `--gen-syllabus` 自动生成 `syllabus.txt`（见下）

### 5. 生成考纲文件 syllabus.txt（调用 API 自动生成）

把官方考纲文件（如 PDF）放进 `data/`，运行：

```bash
python src/main.py --gen-syllabus "data/考纲.pdf"
```

程序会解析考纲文件，调用 LLM 提取全部考点并按考试占比组织成 `data/syllabus.txt`，格式如下（程序自动生成，无需手写）：

```
# 851结构化学 考试大纲

# ===== 第一部分：量子力学基础（约25%）=====
微观粒子的波粒二象性与德布罗意关系
不确定性原理及其应用
...
```

> 标题格式会根据 `config.json` 中的 `subject.code` 和 `subject.name` 自动生成。部分标记行 `# ===== 第X部分：名称（约N%）=====` 会被 planner 读取，用于按占比加权分配复习天数。也可手动编辑 `syllabus.txt` 调整考点。

### 6. 构建向量数据库（首次使用必须执行）

```bash
python src/main.py --build-db                # 默认开启 OCR
python src/main.py --build-db --no-ocr       # 跳过 OCR（仅处理有文字层的 PDF）
```

### 7. 生成复习计划

```bash
python src/main.py --plan              # 默认30天
python src/main.py --plan --days 45    # 自定义天数
```

复习计划按各部分考试占比加权分配天数：占比高的部分分到更多天，每天考点少、复习更细；占比低的部分天数少。

### 8. 生成每日试卷

```bash
python src/main.py --day 1    # 生成第1天的试卷和答案
```

生成的文件保存在 `output/` 目录下。

## 命令一览

| 命令 | 作用 |
|------|------|
| `--gen-syllabus <考纲文件>` | 调用 API 从考纲文件自动生成 syllabus.txt |
| `--build-db` | 构建向量数据库（默认开启 OCR，首次必须执行） |
| `--build-db --no-ocr` | 构建数据库但跳过 OCR |
| `--add-file <路径> --to <库>` | 导入单个文件到向量库（增量，不重建） |
| `--plan [--days N]` | 生成复习计划 |
| `--day N` | 生成第 N 天的试卷和答案 |

## 单文件增量导入

不想重建整个向量库时，可以单独导入一个文件。导入后会增量切块、向量化并追加到指定库：

```bash
# 指定目标库
python src/main.py --add-file "data/textbooks/新教材.pdf" --to textbooks
python src/main.py --add-file "新题库.pdf" --to question_banks

# 不指定 --to 时按路径关键词自动判断
# （路径含 "课本/教材/textbook" → textbooks；含 "题库/试题/习题/question" → question_banks）
python src/main.py --add-file "data/textbooks/xxx.pdf"
```

导入时会打印目标库的块数变化，例如：`question_banks: 19 -> 20 块（新增 1）`，便于确认导入成功。

> 单文件导入默认开启 OCR，但 `parse_pdf` 会逐页智能判断——有文字层的页直接提取不走 OCR，仅扫描页才 OCR，因此对文字版 PDF 不会有额外开销。

## OCR 与扫描版 PDF 处理

### 逐页智能判断

PDF 解析采用逐页策略，避免浪费 OCR：

- **有文字层的页**：直接用 pymupdf 提取（毫秒级，不走 OCR）
- **无文字层的扫描页**：用 RapidOCR 识别（仅这些页）
- **纯文字 PDF**：完全不触发 OCR
- **混合型 PDF**：文字页 + 扫描页 OCR，内容完整提取

### OCR 引擎：RapidOCR

使用 [RapidOCR](https://github.com/RapidAI/RapidOCR)（基于 onnxruntime），不依赖 PyTorch，中文识别质量好、稳定不卡死：

```bash
pip install rapidocr_onnxruntime   # 已包含在 requirements.txt
```

### OCR 质量检验

为防止 OCR 识别出一堆乱码污染向量库，每页 OCR 后做双重质量检验：

- **置信度**：RapidOCR 返回的识别置信度（0~1）
- **中文占比**：结果中中文字符的比例

判断规则：

| 情况 | 处理 |
|------|------|
| 置信度 < 0.3 且中文占比 < 10% | 判定乱码，**丢弃该页**并警告 |
| 置信度 < 0.5（但非乱码） | 保留，提示"识别质量一般，可能含图表/公式" |
| 其他 | 正常保留 |

被丢弃的乱码页不会写入向量库，避免垃圾内容干扰检索。

### 页级缓存与断点续传

每个 PDF 的每页 OCR 结果缓存到 `output/.ocr_cache/<文件名>/page_XXXX.txt`：

- 首次 OCR 较慢（每页约 6 秒），但只跑一次
- 中断后重跑自动跳过已完成的页（断点续传）
- 之后重建向量库时直接读缓存，秒级完成

### OCR 参数调整

OCR 和文本切分的相关参数在 `src/file_parser.py` 和 `src/vector_store.py` 顶部定义，可根据需要修改：

#### 文件解析参数（`src/file_parser.py`）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `OCR_MAX_PAGES` | `500` | 单个 PDF 最大 OCR 处理页数。超过此页数的 PDF，超出部分会被截断。如果你的教材页数特别多（如 800 页的教材），可以调大此值。注意：值越大处理时间越长。 |
| `OCR_DPI_DEFAULT` | `200` | 普通 PDF 的 OCR 渲染分辨率。DPI 越高识别越准，但处理越慢、图片越大。200 是质量和速度的平衡点。 |
| `OCR_DPI_LARGE` | `150` | 大文件 PDF 的 OCR 渲染分辨率。文件超过 `LARGE_FILE_MB` 时自动降低 DPI 以加速处理。 |
| `LARGE_FILE_MB` | `20` | 大文件判定阈值（MB）。超过此大小的 PDF 会自动降低 DPI（使用 `OCR_DPI_LARGE` 而非 `OCR_DPI_DEFAULT`）。 |

**调整示例：**

```python
# 如果你的教材多是扫描版但页数不多（<200页），可提高 DPI 获得更好识别质量
OCR_DPI_DEFAULT = 300

# 如果教材页数非常多（如 800 页），调大页数上限
OCR_MAX_PAGES = 800

# 如果电脑性能有限，降低 DPI 加速处理
OCR_DPI_DEFAULT = 150
OCR_DPI_LARGE = 100
```

#### 文本切分参数（`src/vector_store.py`）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `CHUNK_SIZE` | `500` | 文本切块的字符数。较大值让每块包含更多上下文，检索更连贯但可能不够精准；较小值检索更精准但可能丢失上下文。建议 300~800。 |
| `CHUNK_OVERLAP` | `100` | 相邻文本块之间的重叠字符数。重叠避免关键信息恰好被切断在块边界。通常设为 `CHUNK_SIZE` 的 15%~25%。 |

**调整示例：**

```python
# 如果检索结果感觉过于零碎，增大块大小
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

# 如果需要更精准的检索，减小块大小
CHUNK_SIZE = 300
CHUNK_OVERLAP = 60
```

> **注意**：修改切分参数后需要重新执行 `--build-db` 才能生效（向量库是基于切分后的文本块构建的）。

## 项目结构

```
kaoyan_agent-for_all/
├── config.json             # 学科配置（修改此文件切换学科）
├── data/
│   ├── textbooks/          # 课本文件
│   ├── question_banks/     # 题库文件
│   └── syllabus.txt        # 考纲（每行一个考点）
├── db/                     # 向量数据库存储（.pkl）
├── output/                 # 生成的试卷和答案
│   └── .ocr_cache/         # OCR 页级缓存（断点续传）
├── src/
│   ├── file_parser.py      # 文件解析（逐页智能 + RapidOCR + 质量检验）
│   ├── vector_store.py     # 向量库构建、检索、增量导入
│   ├── planner.py          # 考纲解析与计划生成（按占比加权）
│   ├── syllabus_generator.py # 调用API从考纲文件生成 syllabus.txt
│   ├── llm_client.py       # LLM 调用封装（Claude/DeepSeek 自动检测）
│   ├── quiz_generator.py   # 试卷生成（RAG + LLM）
│   └── main.py             # CLI 入口
├── .env                    # API Key 配置
└── requirements.txt
```

## 切换学科

只需两步：

1. 编辑 `config.json`，修改 `subject.name`、`subject.code`、`exam_constraints` 等字段
2. 替换 `data/textbooks/`、`data/question_banks/` 中的资料，并放入对应学科的考纲文件
3. 重新执行 `--gen-syllabus` → `--build-db` → `--plan` → `--day N`

## 支持的 LLM

程序通过 **OpenAI 兼容接口**支持市面上绝大多数 LLM 提供商。只需在 `.env` 中配置 `LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL` 三行即可。

### 已测试可用的提供商

| 提供商 | `LLM_BASE_URL` | `LLM_MODEL`（示例） | 备注 |
|--------|----------------|---------------------|------|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` | 推荐，性价比高 |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` | 需海外支付 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus` | 国产，中文能力强 |
| 通义千问 (Qwen) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | 阿里云，送免费额度 |
| Moonshot (Kimi) | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | 国产，长文本见长 |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3` | 聚合平台，模型丰富 |
| 零一万物 (Yi) | `https://api.lingyiwanwu.com/v1` | `yi-large` | 国产 |
| Anthropic Claude | *无需（自动识别）* | `claude-sonnet-4-20250514` | Key 以 `sk-ant-` 开头自动走原生 SDK |
| xAI Grok | `https://api.x.ai/v1` | `grok-3` | — |

> **任意 OpenAI 兼容接口**均可使用，只需填入对应的 `LLM_BASE_URL` 和 `LLM_MODEL` 即可，无需修改代码。

### 配置方式

编辑 `.env` 文件，填入三行：

```bash
LLM_API_KEY=sk-xxxxx               # 你的 API Key
LLM_BASE_URL=https://api.deepseek.com   # 接口地址
LLM_MODEL=deepseek-chat            # 模型名称
```

`.env` 文件中已包含所有主流提供商的配置示例，取消注释即可切换。

### 自动识别规则

- Key 以 `sk-ant-` 开头 → 自动走 **Anthropic 原生 SDK**（无需设置 `LLM_BASE_URL`）
- 其他 Key → 走 **OpenAI 兼容接口**（需设置 `LLM_BASE_URL`）
- 为兼容旧版，仍支持 `DEEPSEEK_API_KEY` / `ANTHROPIC_API_KEY` 变量（但不推荐新用户使用）

## 注意事项

- 首次运行会下载 embedding 模型（`all-MiniLM-L6-v2`，约 80MB），已配置国内镜像加速
- `--build-db` 默认开启 OCR；扫描版 PDF 首次 OCR 较慢，但有页级缓存可断点续传
- 增量导入新资料用 `--add-file`，无需重建整个库
- LLM API 调用会产生费用，请合理使用
- 是否禁用计算器请在 `config.json` 中配置（`exam_constraints.no_calculator`）
