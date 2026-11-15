"""Shared argparse helper for pipeline step scripts."""
import argparse

DATASETS = ["synthetic", "real", "sample"]


def parser(desc: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=desc)
    p.add_argument("--dataset", choices=DATASETS, default="synthetic")
    return p
