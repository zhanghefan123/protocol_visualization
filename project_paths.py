"""
Single layout for generated artifacts: everything under ``output/`` at the repo root.

Scripts may import this module (ensure the repo root is on ``sys.path`` when running from subdirs).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

OUTPUT_DIR = REPO_ROOT / "output"

# --- rfc_fetch (IANA ports CSV, Datatracker cache, RFC .txt cache for port verification) ---
OUTPUT_RFC_FETCH = OUTPUT_DIR / "rfc_fetch"
IANA_PORTS_CSV = OUTPUT_RFC_FETCH / "iana_wellknown_ports_rfcs.csv"
IANA_DATATRACKER_CACHE = OUTPUT_RFC_FETCH / "iana_datatracker_cache.json"

# Unified RFC Editor plaintext cache for rfc_fetch, graphs, decimal/port verify.
RFC_BODY_CACHE_DIR = OUTPUT_DIR / "cache" / "rfc_body"
# Older default location; still consulted for reads and migrated into RFC_BODY_CACHE_DIR on hit.
LEGACY_RFC_FETCH_TXT_DIR = OUTPUT_RFC_FETCH / "rfc_txt"
# Backwards-compatible alias: same as RFC_BODY_CACHE_DIR (was under rfc_fetch/rfc_txt).
OUTPUT_RFC_FETCH_TXT_CACHE = RFC_BODY_CACHE_DIR

# --- Application-layer protocol graph (well-known port seeds) ---
OUTPUT_APP_GRAPH = OUTPUT_DIR / "app_graph"
APP_PROTOCOL_SEEDS_YAML = OUTPUT_APP_GRAPH / "protocol_seeds.yaml"
APP_NODES_CSV = OUTPUT_APP_GRAPH / "nodes.csv"
APP_EDGES_CSV = OUTPUT_APP_GRAPH / "edges.csv"
# rfc-index.xml + rfc*.refs.txt for build_app_dataset/rfc_editor_graph.py (app + network graph runs)
OUTPUT_CACHE_RFC_EDITOR = OUTPUT_APP_GRAPH / "cache"

# --- Network-layer graph (IANA protocol numbers) ---
OUTPUT_NETWORK_GRAPH = OUTPUT_DIR / "network_graph"
NETWORK_PROTOCOL_SEEDS_YAML = OUTPUT_NETWORK_GRAPH / "protocol_seeds_network.yaml"
NETWORK_DATATRACKER_CACHE = OUTPUT_NETWORK_GRAPH / "network_datatracker_cache.json"
NETWORK_NODES_CSV = OUTPUT_NETWORK_GRAPH / "nodes.csv"
NETWORK_EDGES_CSV = OUTPUT_NETWORK_GRAPH / "edges.csv"

# --- Downloads (IANA snapshots, etc.) ---
OUTPUT_CACHE_NETWORK = OUTPUT_DIR / "cache" / "network"
NETWORK_PROTOCOL_NUMBERS_CSV = OUTPUT_CACHE_NETWORK / "protocol-numbers-1.csv"

# --- Visualization ---
OUTPUT_VIZ = OUTPUT_DIR / "viz"
TIMELINE_HTML = OUTPUT_VIZ / "timeline_graph.html"
