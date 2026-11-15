"""Import hand-collected CSV into real (stub; Phase 5)."""
from _cli import parser


def main() -> None:
    p = parser("Import hand-collected CSV into real")
    args = p.parse_args()
    print(f"import_csv [{args.dataset}]: not implemented yet (Phase 5)")


if __name__ == "__main__":
    main()
