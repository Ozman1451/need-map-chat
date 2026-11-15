"""Step 1: clean comments (stub; Phase 2)."""
from _cli import parser


def main() -> None:
    p = parser("Step 1: clean comments")
    args = p.parse_args()
    print(f"clean [{args.dataset}]: not implemented yet (Phase 2)")


if __name__ == "__main__":
    main()
