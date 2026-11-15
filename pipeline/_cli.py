"""Shared argparse + path helpers for pipeline step scripts.

PIPELINE_OUT (env) redirects data/processed/ and artifacts/ to another root (tests).
"""
import argparse
import logging
import os
import sys
from pathlib import Path

DATASETS = ["synthetic", "real", "sample"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))  # `app` importable even without `pip install -e`


def parser(desc: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=desc)
    p.add_argument("--dataset", choices=DATASETS, default="synthetic")
    return p


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "google_genai", "google.genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _out_root() -> Path:
    return Path(os.environ["PIPELINE_OUT"]) if os.environ.get("PIPELINE_OUT") else ROOT


def raw_dir(dataset: str) -> Path:
    return ROOT / "data" / "sample" if dataset == "sample" else ROOT / "data" / "raw" / dataset


def processed_dir(dataset: str) -> Path:
    d = _out_root() / "data" / "processed" / dataset
    d.mkdir(parents=True, exist_ok=True)
    return d


def artifacts_dir(dataset: str) -> Path:
    d = _out_root() / "artifacts" / dataset
    d.mkdir(parents=True, exist_ok=True)
    return d
