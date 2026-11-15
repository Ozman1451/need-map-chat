"""Scrape Instagram via Apify (stub; Phase 5)."""
from _cli import parser


def main() -> None:
    p = parser("Scrape Instagram via Apify")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    print(f"scrape_apify [{args.dataset}]: not implemented yet (Phase 5)")


if __name__ == "__main__":
    main()
