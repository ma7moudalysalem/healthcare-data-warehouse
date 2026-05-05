"""End-to-end local demo - no Azure needed.

Runs everything that can run on a laptop:
  1. Generate a small claims feed (5K rows).
  2. Boot the provider API into the background, dump providers.json.
  3. Generate 30s of stdout vitals.
  4. Build the Streamlit demo Parquet fixtures.
  5. Print a one-line "now run streamlit" hint.

Skips the Spark pipelines and the Synapse / Power BI sides - those need
the cloud bits. For a smoke run that touches *those*, see
docs/architecture/overview.md.

Usage:
    python -m scripts.demo_local
    python -m scripts.demo_local --claims 1000
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], **kwargs) -> None:
    print(f"\n>>> {' '.join(args)}", file=sys.stderr)
    subprocess.check_call(args, cwd=ROOT, **kwargs)


def _spawn(args: list[str]) -> subprocess.Popen:
    print(f"\n>>> [bg] {' '.join(args)}", file=sys.stderr)
    return subprocess.Popen(args, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=int, default=5000, help="Number of claim rows.")
    parser.add_argument("--vitals-seconds", type=int, default=30,
                        help="How long to run the vitals simulator.")
    parser.add_argument("--skip-provider-api", action="store_true",
                        help="Don't boot the Flask service (only dump providers.json).")
    args = parser.parse_args()

    py = sys.executable

    # 1. Claims
    _run([py, "-m", "src.generators.generate_claims", "--count", str(args.claims)])

    # 2. Provider API - foreground for the dump, optionally background for live API
    print("\n>>> dumping providers.json", file=sys.stderr)
    # Run a short script that just bootstraps the registry without serving HTTP.
    _run([
        py, "-c",
        "from src.generators.provider_api import _bootstrap_registry; _bootstrap_registry()",
    ])

    api_proc = None
    if not args.skip_provider_api:
        api_proc = _spawn([py, "-m", "src.generators.provider_api"])
        time.sleep(2)  # give it a moment to bind
        print(">>> provider API up at http://localhost:5000/health", file=sys.stderr)

    try:
        # 3. Vitals - capped duration
        _run([
            py, "-m", "src.generators.simulate_vitals",
            "--rate", "2", "--devices", "5",
            "--duration", str(args.vitals_seconds), "--stdout",
        ], stdout=open(os.devnull, "w"))

        # 4. Streamlit demo data
        _run([py, str(ROOT / "dashboards" / "streamlit" / "build_demo_data.py")])

    finally:
        if api_proc is not None:
            print("\n>>> stopping provider API", file=sys.stderr)
            try:
                api_proc.send_signal(signal.SIGTERM)
                api_proc.wait(timeout=5)
            except Exception:
                api_proc.kill()

    print(
        "\n"
        "Demo data ready.\n"
        "\n"
        "  data/raw/claims.jsonl\n"
        "  data/raw/providers.json\n"
        "  dashboards/streamlit/demo_data/*.parquet\n"
        "\n"
        "Run the dashboard:\n"
        "    HCDW_DEMO_MODE=1 streamlit run dashboards/streamlit/app.py\n",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
