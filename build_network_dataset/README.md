# 网络层（IP 协议号）种子

从 IANA **`protocol-numbers-1.csv`**（IP 首部 *Protocol* 字段的分配表）生成与 `output/app_graph/protocol_seeds.yaml` **相同结构**的 `protocol_seeds_network.yaml`（默认在 **`output/network_graph/`**），供 `build_app_dataset/rfc_editor_graph.py` 使用。

| 脚本 | 作用 |
|------|------|
| `generate_network_seeds.py` | CLI：拉 CSV、`datatracker_merge`、写 YAML、`core_internet_protocol_seeds` |
| `datatracker_merge.py` | Datatracker 标题检索并入种子（与本目录 CLI 同属网络层流水线） |
| `rfc_decimal_verify.py` | 用 RFC 正文筛掉与 IANA Decimal 不符的 Datatracker 命中 |
| `core_internet_protocol_seeds.py` | 核心 IP 等锚点注入 |

数据源：<https://www.iana.org/assignments/protocol-numbers/protocol-numbers-1.csv>

说明：表中同时包含 ICMP、TCP、UDP 等——这是 **IANA IP 协议号** 语义，不等于 OSI「只有第三层」。需要纯第三层可自行在生成的 YAML 里删掉 TCP/UDP 等条目。

## 生成 YAML

在项目根目录执行（需已安装 `PyYAML`，与 `build_app_dataset` 相同）：

```powershell
python build_network_dataset/generate_network_seeds.py --fetch
```

- `--fetch`：从 IANA 拉取 CSV 写入 `output/cache/network/protocol-numbers-1.csv` 再生成。
- 已有本地 CSV 时：`python build_network_dataset/generate_network_seeds.py -i path/to/protocol-numbers-1.csv`

每条（非 Reserved、且非 decimal 4/41）都会形成一个 seed：**Reference 里没有 RFC 的行也会走 Datatracker**，若标题检索命中 RFC 则写入 `rfcs`；IANA 里已有 RFC 的则会 **并集**。Datatracker 短语除 *Protocol* 列外，还会从 **Keyword** 生成变体：**词内连字符改为空格**（如 `IPv6-Opts` → `IPv6 Opts`），并在 **`for` / `over` / `and` / `via`** 处切段附加查询（如 `ISIS over IPv4` → 整串 + `ISIS` + `IPv4`）。

默认还会拉 RFC Editor 的 `.txt`，**丢弃正文中看不出对应 IANA Decimal（协议号）** 的 Datatracker 命中；关闭：`--no-verify-network-datatracker-decimal-in-rfc-body`。RFC 正文与应用层、构图脚本共用统一缓存 **`output/cache/rfc_body`**（仍会读取旧路径 `output/rfc_fetch/rfc_txt` 以便迁移）。

YAML 里只保留最终 **至少有一条 RFC** 的协议。Datatracker JSON 缓存：`output/network_graph/network_datatracker_cache.json`（写入的是 **过滤后** 的 hits）。关闭 Datatracker：`--no-network-datatracker`。

默认还会把 **IPv6 扩展头 Next Header** 在表里的独立行（`HOPOPT`、`IPV6-ICMP`、`IPV6-NONXT`、`IPV6-OPTS`）**折叠进 `IPV6`** 种子（RFC 并集），避免与 **IPV6** 重复占位。需要与 IANA 表一一对应时用 **`--iana-ipv6-extension-rows`**。

**IPv4 / IPv6 核心规范**：IANA 表里 decimal **4**、**41** 引用的是 **封装/隧道**（RFC2003、RFC2473），不是「互联网协议本体」的教学锚点；脚本会 **跳过这两行**，并 **显式注入** `IPV4`（RFC791）与 `IPV6`（**仅 RFC8200**；IANA decimal 41 对应的是封装文档 RFC2473，与「IPv6 本体」不同），再折叠 IPv6 扩展头行。**ETHERNET** 等其余与教学语义不一致的条目仍由 **`apply_iana_protocol_number_semantics`** 修正。

## 构建 nodes / edges（可选）

```powershell
python build_app_dataset/rfc_editor_graph.py ^
  --seeds output/network_graph/protocol_seeds_network.yaml ^
  --out output/network_graph
```

输出：`output/network_graph/nodes.csv` 与 `edges.csv`。  
RFC Editor 索引与参考文献缓存默认为 **`output/app_graph/cache/`**（与一键流水线、`rfc_editor_graph.py` 默认 `--cache` 一致）。

与 **应用层** `output/app_graph/` 合并后出时间线图：在项目根目录直接运行  
`python viz/render_timeline_echarts.py`（默认会自动合并两处；仅用应用层可加 `--no-merge-network`）。
