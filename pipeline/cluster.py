"""Step 4: clustering (stub; Phase 2)."""
from _cli import parser


def main() -> None:
    p = parser("Step 4: clustering")
    args = p.parse_args()
    print(f"cluster [{args.dataset}]: not implemented yet (Phase 2)")


if __name__ == "__main__":
    main()
