"""Map Apify JSON to tables (stub; Phase 5)."""
from _cli import parser


def main() -> None:
    p = parser("Map Apify JSON to tables")
    args = p.parse_args()
    print(f"map_apify [{args.dataset}]: not implemented yet (Phase 5)")


if __name__ == "__main__":
    main()
