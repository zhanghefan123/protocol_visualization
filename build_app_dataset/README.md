# 应用层数据集（IANA 知名端口）

与 `build_network_dataset/` 对称的流程：**种子生成脚本** + **`rfc_editor_graph.py` 构图**。

| 脚本 | 作用 |
|------|------|
| `generate_app_seeds.py` | 读 `output/rfc_fetch/iana_wellknown_ports_rfcs.csv` → `output/app_graph/protocol_seeds.yaml` |
| `core_app_protocol_seeds.py` | 额外锚点协议（并入 YAML，不落盘单独文件） |
| `rfc_editor_graph.py` | 读任意 `protocol_seeds*.yaml`，写 `nodes.csv` / `edges.csv`；默认构图缓存 `--cache=output/app_graph/cache/` |

RFC 参考文献解析时的 **正文（.txt）** 与全仓库共用 **`output/cache/rfc_body`**（会先查磁盘再下载；仍可读取旧路径 `output/rfc_fetch/rfc_txt` 并迁入新目录）。详见仓库根目录 `README.md`。
