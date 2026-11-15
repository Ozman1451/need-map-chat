"""Step 7: write artifacts (stub; Phase 2)."""
from _cli import parser


def main() -> None:
    p = parser("Step 7: write artifacts")
    args = p.parse_args()
    print(f"artifacts [{args.dataset}]: not implemented yet (Phase 2)")


if __name__ == "__main__":
    main()
