#!/usr/bin/env python3
"""
One-shot pipeline (project root as cwd). All generated files go under ``output/`` — see ``project_paths.py``.

  optional: python -m rfc_fetch  →  output/rfc_fetch/
  1. build_dataset/generate_seeds.py  →  output/app_graph/protocol_seeds.yaml
  2. build_dataset/rfc_editor_graph.py  →  output/app_graph/nodes.csv, edges.csv
  3. build_network_dataset/generate_network_seeds.py  →  output/network_graph/protocol_seeds_network.yaml
  4. build_dataset/rfc_editor_graph.py (network seeds)  →  output/network_graph/nodes.csv, edges.csv
  5. viz/render_timeline_echarts.py  →  output/viz/timeline_graph.html

Requires: pip install -r build_dataset/requirements.txt (PyYAML, requests, lxml).
``python -m rfc_fetch`` uses only the stdlib. Missing ``output/rfc_fetch/iana_wellknown_ports_rfcs.csv``
triggers rfc_fetch automatically; missing ``output/cache/network/protocol-numbers-1.csv`` adds ``--fetch``
to ``generate_network_seeds``. Use ``--fetch-iana-ports`` / ``--fetch-protocol-numbers`` only to force
refresh when those files already exist. ``--foundation`` only changes viz output (extra anchor nodes).

Usage::

  python run_full_pipeline.py
  python run_full_pipeline.py --fetch-iana-ports --fetch-protocol-numbers --foundation
  python run_full_pipeline.py --foundation --max-nodes 400

Any ``render_timeline_echarts.py`` flag not listed above is forwarded (e.g. ``--max-nodes``, ``--out``).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence

ROOT = Path(__file__).resolve().parent
from project_paths import (
    APP_PROTOCOL_SEEDS_YAML,
    IANA_PORTS_CSV,
    NETWORK_PROTOCOL_NUMBERS_CSV,
    NETWORK_PROTOCOL_SEEDS_YAML,
    OUTPUT_APP_GRAPH,
    OUTPUT_CACHE_RFC_EDITOR,
    OUTPUT_NETWORK_GRAPH,
)


def _run(title: str, cmd: Sequence[str]) -> None:
    print(f"\n=== {title} ===\n+ {' '.join(cmd)}", flush=True)
    subprocess.run(list(cmd), cwd=ROOT, check=True)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run seeds → RFC graph CSVs → timeline HTML in one command (from repo root)."
    )
    ap.add_argument(
        "--fetch-iana-ports",
        action="store_true",
        help="Always run python -m rfc_fetch first (refresh). If omitted, rfc_fetch runs only when the port CSV is missing.",
    )
    ap.add_argument(
        "--fetch-protocol-numbers",
        action="store_true",
        help="Always pass --fetch to generate_network_seeds (re-download protocol-numbers CSV). "
        "If omitted, --fetch is still added when that CSV is missing under output/cache/network/.",
    )
    ap.add_argument(
        "--no-network",
        action="store_true",
        help="Skip network seeds + network graph (steps 3–4); viz uses --no-merge-network",
    )
    ap.add_argument("--workers", type=int, default=16, help="Parallel workers for rfc_editor_graph.py")
    ap.add_argument(
        "--skip-proto-refs",
        action="store_true",
        help="Pass --skip-proto-refs to both rfc_editor_graph runs (faster, fewer proto→proto edges)",
    )
    ap.add_argument(
        "--foundation",
        action="store_true",
        help="Pass --foundation to viz/render_timeline_echarts.py",
    )
    ap.add_argument(
        "--no-merge-network",
        action="store_true",
        help="Pass --no-merge-network to render_timeline_echarts.py (ignore output/network_graph even if present)",
    )
    if argv is None:
        argv = sys.argv[1:]
    args, viz_extra = ap.parse_known_args(argv)

    exe = sys.executable
    graph_base = [
        exe,
        str(ROOT / "build_dataset" / "rfc_editor_graph.py"),
        "--workers",
        str(int(args.workers)),
        "--cache",
        str(OUTPUT_CACHE_RFC_EDITOR),
    ]
    if args.skip_proto_refs:
        graph_base.append("--skip-proto-refs")

    try:
        if args.fetch_iana_ports or not IANA_PORTS_CSV.is_file():
            if not IANA_PORTS_CSV.is_file():
                print(
                    f"\nPort CSV not found ({IANA_PORTS_CSV}); running rfc_fetch first…\n",
                    flush=True,
                )
            _run("rfc_fetch (IANA well-known ports + Datatracker)", [exe, "-m", "rfc_fetch"])

        _run(
            "generate_seeds (application protocol_seeds.yaml)",
            [exe, str(ROOT / "build_dataset" / "generate_seeds.py")],
        )

        _run(
            "rfc_editor_graph (application → output/app_graph)",
            [*graph_base, "--seeds", str(APP_PROTOCOL_SEEDS_YAML), "--out", str(OUTPUT_APP_GRAPH)],
        )

        if not args.no_network:
            net_seed_cmd = [exe, str(ROOT / "build_network_dataset" / "generate_network_seeds.py")]
            if args.fetch_protocol_numbers or not NETWORK_PROTOCOL_NUMBERS_CSV.is_file():
                if not NETWORK_PROTOCOL_NUMBERS_CSV.is_file():
                    print(
                        f"\nProtocol-numbers CSV not found ({NETWORK_PROTOCOL_NUMBERS_CSV}); "
                        "using --fetch for generate_network_seeds…\n",
                        flush=True,
                    )
                net_seed_cmd.append("--fetch")
            _run("generate_network_seeds (protocol_seeds_network.yaml)", net_seed_cmd)

            _run(
                "rfc_editor_graph (network → output/network_graph)",
                [
                    *graph_base,
                    "--seeds",
                    str(NETWORK_PROTOCOL_SEEDS_YAML),
                    "--out",
                    str(OUTPUT_NETWORK_GRAPH),
                ],
            )

        viz_cmd = [exe, str(ROOT / "viz" / "render_timeline_echarts.py")]
        if args.foundation:
            viz_cmd.append("--foundation")
        if args.no_network or args.no_merge_network:
            viz_cmd.append("--no-merge-network")
        viz_cmd.extend(viz_extra)

        _run("render_timeline_echarts (output/viz/timeline_graph.html)", viz_cmd)

    except subprocess.CalledProcessError as e:
        print(f"\nPipeline stopped: command exited with {e.returncode}", file=sys.stderr)
        return int(e.returncode) if e.returncode else 1
    except FileNotFoundError as e:
        print(f"\nPipeline stopped: {e}", file=sys.stderr)
        return 127

    print("\n=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
