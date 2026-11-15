"""Step 2: Gemini tagging (stub; Phase 2)."""
from _cli import parser


def main() -> None:
    p = parser("Step 2: Gemini tagging")
    args = p.parse_args()
    print(f"tag [{args.dataset}]: not implemented yet (Phase 2)")


if __name__ == "__main__":
    main()
