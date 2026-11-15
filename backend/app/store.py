"""In-memory store over artifacts/<dataset>/ (stub; Phase 3)."""
from .config import settings


class Store:
    def __init__(self) -> None:
        self.dataset: str | None = None
        self.manifest: dict = {}

    def load(self, dataset: str = settings.dataset) -> None:
        self.dataset = dataset
        self.manifest = {}


store = Store()
