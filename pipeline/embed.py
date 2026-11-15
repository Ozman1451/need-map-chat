"""Step 3: embeddings (stub; Phase 2)."""
from _cli import parser


def main() -> None:
    p = parser("Step 3: embeddings")
    args = p.parse_args()
    print(f"embed [{args.dataset}]: not implemented yet (Phase 2)")


if __name__ == "__main__":
    main()
