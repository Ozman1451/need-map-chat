"""Run pipeline steps 1-7 in order (SPEC §5)."""
import subprocess
import sys
from pathlib import Path

from _cli import parser

STEPS = ["clean", "tag", "embed", "cluster", "name", "metrics", "artifacts"]


def main() -> None:
    args = parser("Run full offline pipeline").parse_args()
    here = Path(__file__).parent
    for step in STEPS:
        subprocess.run([sys.executable, str(here / f"{step}.py"), "--dataset", args.dataset], check=True)


if __name__ == "__main__":
    main()
