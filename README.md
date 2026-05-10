# visualization_new：IANA 端口 / RFC 与时间线图

把 **IANA 分配的知名端口**、**RFC 文档** 和 **协议依赖关系** 串成数据与一张可在浏览器里打开的时间线图。仓库里所有**生成结果**默认写在同一目录：**项目根下的 `output/`**（路径集中在 `project_paths.py`，改一处即可全局一致）。

---

## 零基础：我要怎么跑起来？

### 你需要先有什么？

1. 一台能上网的电脑，已安装 **Python 3.10 或更高**（推荐 3.10+）。
2. 打开终端（Windows 可用 **PowerShell** 或 **cmd**）。

### 第一步：进入项目文件夹

把下面路径换成你电脑上**实际的路径**（文件夹名是 `visualization_new`）：

```powershell
cd C:\Users\zhf\Desktop\visualization_new
```

### 第二步：安装图谱脚本依赖（只需一次）

时间线图和 `nodes.csv` / `edges.csv` 依赖几个 Python 包：

```powershell
pip install -r build_app_dataset\requirements.txt
```

> **说明**：`python -m rfc_fetch` 还需要 **`tqdm`**（进度条；`pip install tqdm` 或 `pip install -r rfc_fetch/requirements.txt`）。完整流水线与画图请安装 `build_app_dataset/requirements.txt`。

### 第三步（推荐）：一条命令跑完全流程

在**项目根目录**执行：

```powershell
python run_full_pipeline.py
```

这会依次做完：**应用层种子 → 应用层图 → 网络层种子 → 网络层图 → 时间线 HTML**（与下面三个开关无关；除非你加了 **`--no-network`**，才会跳过网络层并让可视化只合并应用层）。

**缺文件时会自动补下载**（不必手写后面两个参数）：

- 若没有 `output/rfc_fetch/iana_wellknown_ports_rfcs.csv`，会先自动执行 **`python -m rfc_fetch`**。
- 若没有 `output/cache/network/protocol-numbers-1.csv`，网络层种子那一步会自动带上 **`--fetch`**，从 IANA 拉协议号表。

下面三个参数都是**可选**的，只在你要「强制刷新」或「改图的外观」时用：

| 参数 | 何时需要 |
|------|----------|
| `--fetch-iana-ports` | 端口 CSV **已经存在**，但仍想**重新**拉 IANA + Datatracker（更新数据；较慢）。 |
| `--fetch-protocol-numbers` | 协议号 CSV **已经存在**，但仍想**重新下载**一份再生成网络层种子。 |
| `--foundation` | 时间线图里是否**额外画出** IP/TCP/UDP 等合成锚点；不加也会正常生成 `timeline_graph.html`，只是图上少了这层「骨架」节点。 |

等价示例（按需叠加）：

```powershell
python run_full_pipeline.py --fetch-iana-ports --fetch-protocol-numbers --foundation
```

跑完后请打开：

```text
output\viz\timeline_graph.html
```

用 **Chrome / Edge / Firefox** 双击打开即可（需联网加载图表库）。

### 如果你只想更新端口表 CSV（不跑整图）

仍在项目根目录：

```powershell
python -m rfc_fetch
```

结果在 `output/rfc_fetch/`（见下一节）。

---

## 所有输出在哪里？（统一 `output/`）

| 路径 | 内容 |
|------|------|
| `output/rfc_fetch/iana_wellknown_ports_rfcs.csv` | IANA 知名端口 + Datatracker 匹配结果 |
| `output/rfc_fetch/iana_datatracker_cache.json` | Datatracker 查询缓存（避免重复请求） |
| `output/cache/rfc_body/` | **统一** RFC `.txt` 全文磁盘缓存（端口校验、网络层 Decimal 校验、`rfc_editor_graph` 参考文献解析；旧目录 `output/rfc_fetch/rfc_txt` 仍可被读取并自动迁到新目录） |
| `output/app_graph/protocol_seeds.yaml` | 应用层协议种子 |
| `output/app_graph/nodes.csv`、`edges.csv` | 应用层协议关系图 |
| `output/network_graph/protocol_seeds_network.yaml` | 网络层种子（IANA ∪ Datatracker；默认再校验 RFC 正文是否含对应 **Decimal**） |
| `output/network_graph/network_datatracker_cache.json` | 网络层 Datatracker 查询缓存 |
| `output/network_graph/nodes.csv`、`edges.csv` | 网络层图 |
| `output/app_graph/cache/` | RFC Editor 索引 `rfc-index.xml` 与各 RFC 参考文献缓存（`rfc_editor_graph.py`；体积会变大，属正常） |
| `output/cache/network/protocol-numbers-1.csv` | 下载的 IANA 协议号表（使用 `--fetch` 时） |
| `output/viz/timeline_graph.html` | 最终时间线网页 |

**代码里如何改默认路径**：编辑仓库根目录的 `project_paths.py`。

---

## 项目结构（代码 vs 生成物）

```text
visualization_new/
├── README.md
├── project_paths.py          # 统一约定 output/ 下各子路径
├── run_full_pipeline.py      # 一键流水线（建议在仓库根目录运行）
├── rfc_fetch/                # IANA + Datatracker → CSV（仅需 tqdm + urllib）
├── build_app_dataset/        # generate_app_seeds.py + core_app_protocol_seeds + rfc_editor_graph.py
├── build_network_dataset/    # generate_network_seeds.py + datatracker_merge + rfc_decimal_verify
├── viz/                      # 时间线图渲染
└── output/                   # ★ 所有默认生成物（运行后才有，可加入 .gitignore）
    ├── rfc_fetch/
    ├── app_graph/
    │   └── cache/            # rfc-index.xml、rfc*.refs.txt（与 nodes/edges 同层应用层产物下）
    ├── network_graph/
    ├── cache/                # 如 RFC 全文 `rfc_body/`；IANA protocol-numbers 快照 `network/`
    └── viz/
```

---

## 分步运行（不用一键脚本时）

以下顺序与 **`run_full_pipeline.py` 在未加 `--fetch-*` / `--no-network`** 时的行为一致：**工作目录请始终在仓库根目录**（这样才能正确解析 `project_paths.py` 与相对路径）。

### 前置：依赖与路径约定

| 用途 | 建议安装 |
|------|-----------|
| 构图与时间线（第 3、5、6 步） | `pip install -r build_app_dataset/requirements.txt`（PyYAML、requests、lxml、tqdm） |
| 仅端口 CSV（第 1 步） | `pip install tqdm` 或 `pip install -r rfc_fetch/requirements.txt` |

**默认关键路径（均可在代码里改成一处）**：  
CSV 端口表 → `output/rfc_fetch/iana_wellknown_ports_rfcs.csv`；应用种子 → `output/app_graph/protocol_seeds.yaml`；网络种子 → `output/network_graph/protocol_seeds_network.yaml`；协议号表 → `output/cache/network/protocol-numbers-1.csv`。  
RFC 全文磁盘缓存：**`output/cache/rfc_body/`**（`rfc_fetch`、网络层小数校验、`rfc_editor_graph` 参考文献解析共用；旧目录 `output/rfc_fetch/rfc_txt` 仍可被读取并迁到新路径）。  
`rfc_editor_graph` 的索引与 **`rfc*.refs.txt`**：`output/app_graph/cache/`（`--cache` 默认）。

### 手动步骤（顺序不要打乱）

#### 步骤 1：端口 + Datatracker → CSV（可选但通常需要）

在还没有 **`output/rfc_fetch/iana_wellknown_ports_rfcs.csv`** 时必须先执行本步。**若需整表重跑**（刷新 Datatracker 缓存与 RFC 正文校验），可随时再运行同一条命令。

```powershell
python -m rfc_fetch
```

- **产出**：主文件为 **`output/rfc_fetch/iana_wellknown_ports_rfcs.csv`**；Datatracker 缓存 **`output/rfc_fetch/iana_datatracker_cache.json`**；开启默认「正文带端口」校验时会写入 **`output/cache/rfc_body/rfc*.txt`**。  
- **耗时**：较慢（大量 Datatracker 与 RFC Editor 下载）。详见下文「`rfc_fetch` 说明摘要」。  
- **等价于一键脚本**：若端口 CSV **已存在**，手动流程里可跳过本步（与 `run_full_pipeline.py` 只在缺失时才跑 `rfc_fetch` 一致）。

#### 步骤 2：CSV → 应用层种子 YAML

```powershell
python build_app_dataset/generate_app_seeds.py
```

- **输入**：默认 `-i output/rfc_fetch/iana_wellknown_ports_rfcs.csv`。  
- **产出**：`**output/app_graph/protocol_seeds.yaml**`。  
- **是否联网**：**否**（只读 CSV + 内置 `core_app_protocol_seeds`）。

#### 步骤 3：应用层 RFC 图

```powershell
python build_app_dataset/rfc_editor_graph.py --workers 16
```

等价于指定默认种子与输出目录时可写：

```powershell
python build_app_dataset/rfc_editor_graph.py --workers 16 --seeds output/app_graph/protocol_seeds.yaml --out output/app_graph
```

- **产出**：`**output/app_graph/nodes.csv**`、`**edges.csv**`；`**--cache**` 默认 **`output/app_graph/cache/`**（含 `rfc-index.xml`、各 `rfc*.refs.txt`）。  
- **是否联网**：若缓存齐全可完全离线；否则可能下载 **`rfc-index.xml`** 与缺失的 **`rfcN.txt`**（见 `--rfc-body-cache`，默认 `output/cache/rfc_body`）。  
- **加速**：`--skip-proto-refs` 可少算协议间引用边（与一键脚本的同名参数一致）。

#### 步骤 4：网络层种子 YAML

若本地还没有 **`output/cache/network/protocol-numbers-1.csv`**，请加上 **`--fetch`** 从 IANA 拉表（与一键脚本在缺失时自动加 `--fetch` 一致）：

```powershell
python build_network_dataset/generate_network_seeds.py --fetch
```

若 CSV 已在上述路径，可省略 `--fetch`：

```powershell
python build_network_dataset/generate_network_seeds.py
```

- **产出**：`**output/network_graph/protocol_seeds_network.yaml**`；Datatracker 缓存 **`output/network_graph/network_datatracker_cache.json`**；正文过滤会复用 **`output/cache/rfc_body/`**。  
- **默认**：会对「IANA Reference 无 RFC」的协议号行做 Datatracker 并集，并用 RFC 正文校验 **IANA Decimal（协议号）**；只要 IANA 里已有 RFC 则**不**再查 Datatracker。仅想保留 IANA 时可加 **`--no-network-datatracker`**（见 `python build_network_dataset/generate_network_seeds.py --help`）。

#### 步骤 5：网络层 RFC 图

与步骤 3 **同一脚本**，换种子与输出目录；**建议与一键脚本相同**，显式传入 **`--cache`**，与应用层共用 `rfc-index.xml` 与 refs 缓存，避免重复下载索引：

```powershell
python build_app_dataset/rfc_editor_graph.py --workers 16 --cache output/app_graph/cache --seeds output/network_graph/protocol_seeds_network.yaml --out output/network_graph
```

- **产出**：`**output/network_graph/nodes.csv**`、`**edges.csv**`。

#### 步骤 6：合并两图 → 时间线 HTML

最简（与 **`run_full_pipeline.py` 默认不传 `--foundation`** 一致）：若第 5 步已完成，会自动合并 **`output/network_graph/`**；

```powershell
python viz/render_timeline_echarts.py
```

需要 **合成 IPv4/TCP/UDP 等锚点**，便于与 IANA「知名端口→传输」边对齐时，可加 **`--foundation`**（与时间线图小节说明一致）：

```powershell
python viz/render_timeline_echarts.py --foundation
```

- **默认产出**：`**output/viz/timeline_graph.html**`。  
- **只要应用层**：跳过步骤 4–5，并在本步加 **`--no-merge-network`**。  
**更多旋钮**：`--max-nodes`、`--out`、`--no-iana-transport-edges`、`--rfc-click` 等见 `python viz/render_timeline_echarts.py --help`。

### 与一键脚本的对照

| 手动跳过 / 等价 | 一键脚本做法 |
|----------------|--------------|
| 不想重做端口 CSV（已存在） | 不传 `--fetch-iana-ports` |
| 强制重跑端口流水线 | `--fetch-iana-ports` |
| 强制重下协议号 CSV | `--fetch-protocol-numbers` |
| 不要做网络层 + 画图不并网络图 | `--no-network` |
| 构图线程数、`--skip-proto-refs` | `run_full_pipeline.py --workers …`、`--skip-proto-refs` |

完整参数：`python run_full_pipeline.py --help`、`python -m rfc_fetch --help`、`python build_network_dataset/generate_network_seeds.py --help`。

---

## `rfc_fetch` 说明摘要

- **数据源**：IANA `service-names-port-numbers.csv`；**Datatracker**：按 RFC 标题子串检索。
- **默认**：结果写入 `output/rfc_fetch/`；**默认开启**「RFC 正文需出现对应端口（如 port 80、80/tcp）」才保留 Datatracker 命中，可减少张冠李戴；关闭：`python -m rfc_fetch --no-verify-port-in-rfc-body`。
- **依赖**：请先 **`pip install tqdm`**（或 `-r rfc_fetch/requirements.txt`）；其余多为标准库。

### 常用参数

| 参数 | 默认 | 含义 |
|------|------|------|
| `-o`, `--output` | `output/rfc_fetch/iana_wellknown_ports_rfcs.csv` | 输出 CSV |
| `--cache-file` | `output/rfc_fetch/iana_datatracker_cache.json` | Datatracker JSON 缓存 |
| `--no-cache` | 关 | 不使用缓存 |
| `-j`, `--workers` | `24` | Datatracker 并发线程（遇 429 可降到 8–12） |
| `--verify-port-in-rfc-body` / `--no-verify-port-in-rfc-body` | 默认开 | 是否在 RFC 正文里校验端口 |
| `--max-datatracker-phrases` | `4` | 每个服务名最多尝试几条标题检索短语 |
| `--single-datatracker-query` | — | 等价 `--max-datatracker-phrases 1`，只查一次 |

---

## 时间线图（`viz/`）

- 默认读取 `output/app_graph/` 与 `output/network_graph/` 下的 `nodes.csv` / `edges.csv`；仅应用层可加 `--no-merge-network`。
- **Ctrl/Cmd + 单击**节点可打开 defining RFC（`--rfc-click all` 可全开）。
- **`--foundation`**：注入 IP/TCP/UDP 等合成锚点，便于和 IANA 端口传输边对齐。

---

## 数据源与合规

- **IANA**：[Service Names and Port Numbers](https://www.iana.org/assignments/service-names-port-numbers/)、[Protocol Numbers](https://www.iana.org/assignments/protocol-numbers/protocol-numbers-1.csv)。
- **Datatracker**、**RFC Editor**：请合理设置并发，优先利用本地缓存。

---

## 常见问题

**Q：第一次跑 `rfc_fetch` 很慢？**  
A：要向 Datatracker 发很多请求，并可能下载大量 RFC 正文做端口校验。第二次有缓存会快很多。

**Q：`nodes.csv` 为什么比端口 CSV 行数少？**  
A：端口表是「每端口/传输一行」；种子按 **协议名** 合并，且无名服务不进 `generate_app_seeds.py` 的协议表。详见此前说明或代码注释。

**Q：为什么 Datatracker 和 IANA Reference 里的 RFC 不一致？**  
A：IANA 是登记表引用；Datatracker 是**标题关键词**搜索，语义不同，可能相关但不是同一份文档。

---

版本信息见 `rfc_fetch.__version__`。
