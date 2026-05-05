"""Wrapper around the Synthea jar.

Synthea is a JVM application; this script handles downloading the jar (if
missing), invoking it with our `synthea.properties`, and post-processing the
CSVs into `data/raw/` so the rest of the pipeline doesn't need to know where
the jar lives.

Typical use:
    python -m src.synthea.run_synthea --population 1000   # quick smoke run
    python -m src.synthea.run_synthea --population 100000 # full project size

Notes:
* The jar download is ~50MB and is cached at src/synthea/synthea-with-dependencies.jar
* Java 11+ must be on PATH.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
JAR_NAME = "synthea-with-dependencies.jar"
JAR_PATH = THIS_DIR / JAR_NAME
JAR_URL = (
    "https://github.com/synthetichealth/synthea/releases/download/"
    "master-branch-latest/synthea-with-dependencies.jar"
)
PROPERTIES = THIS_DIR / "synthea.properties"
OUTPUT_DIR = THIS_DIR / "output"
RAW_TARGET = THIS_DIR.parents[1] / "data" / "raw"


def _ensure_jar() -> None:
    if JAR_PATH.exists():
        return
    print(f"Downloading Synthea jar to {JAR_PATH} (~50 MB) ...", file=sys.stderr)
    with urllib.request.urlopen(JAR_URL) as resp, JAR_PATH.open("wb") as f:
        shutil.copyfileobj(resp, f)
    print("Download complete.", file=sys.stderr)


def _check_java() -> None:
    if shutil.which("java") is None:
        print(
            "ERROR: 'java' not on PATH. Synthea needs Java 11 or newer.\n"
            "On Windows: install Eclipse Temurin and re-open the shell.",
            file=sys.stderr,
        )
        sys.exit(2)


def _run_synthea(population: int, state: str, seed: int | None) -> None:
    cmd = [
        "java",
        "-Xmx4g",
        "-jar",
        str(JAR_PATH),
        "-c",
        str(PROPERTIES),
        "-p",
        str(population),
    ]
    if seed is not None:
        cmd.extend(["-s", str(seed)])
    cmd.append(state)
    print("Running:", " ".join(cmd), file=sys.stderr)
    subprocess.check_call(cmd, cwd=THIS_DIR)


def _publish_to_raw() -> None:
    """Move/copy the CSVs Synthea produced into data/raw/synthea/.

    We don't want to disturb the Synthea output folder (it contains metadata
    files Synthea needs for incremental runs) so this is a copy rather than
    a move.
    """
    src = OUTPUT_DIR / "csv"
    if not src.exists():
        print(f"No CSV output found at {src}; did Synthea fail?", file=sys.stderr)
        return
    dst = RAW_TARGET / "synthea"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    files = sorted(p.name for p in dst.glob("*.csv"))
    print(f"Copied {len(files)} CSV files to {dst}:", file=sys.stderr)
    for fname in files:
        size_mb = (dst / fname).stat().st_size / (1024 * 1024)
        print(f"  - {fname:30s} {size_mb:8.2f} MB", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Synthea and publish CSVs to data/raw.")
    parser.add_argument("--population", type=int, default=1000)
    parser.add_argument("--state", default="Massachusetts",
                        help="Synthea state. Egypt is not bundled; we rewrite "
                             "addresses in the Silver layer.")
    parser.add_argument("--seed", type=int, default=20240212)
    parser.add_argument("--skip-publish", action="store_true",
                        help="Run Synthea but don't copy to data/raw.")
    args = parser.parse_args()

    _check_java()
    _ensure_jar()
    _run_synthea(args.population, args.state, args.seed)
    if not args.skip_publish:
        _publish_to_raw()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
