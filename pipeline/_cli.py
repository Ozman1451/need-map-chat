"""Shared argparse helper for pipeline step scripts."""
import argparse
from pathlib import Path

DATASETS = ["synthetic", "real", "sample"]


def parser(desc: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=desc)
    p.add_argument("--dataset", choices=DATASETS, default="synthetic")
    return p


ROOT = Path(__file__).resolve().parents[1]


def raw_dir(dataset: str) -> Path:
    return ROOT / "data" / "sample" if dataset == "sample" else ROOT / "data" / "raw" / dataset
