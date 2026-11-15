"""Generate synthetic dataset (stub; Phase 1)."""
from _cli import parser


def main() -> None:
    p = parser("Generate synthetic dataset")
    args = p.parse_args()
    print(f"seed_synthetic [{args.dataset}]: not implemented yet (Phase 1)")


if __name__ == "__main__":
    main()
