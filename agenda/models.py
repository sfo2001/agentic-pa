from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

QUADRANT_BY_PRIORITY = {
    "A": "urgent_important",
    "B": "important_not_urgent",
    "C": "urgent_not_important",
    "D": "neither",
}


@dataclass
class Action:
    done: bool = False
    priority: str | None = None
    description: str = ""
    topics: list[str] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)
    due: date | None = None
    tickler: date | None = None
    updated: date | None = None
    id: str | None = None

    @property
    def quadrant(self) -> str | None:
        return QUADRANT_BY_PRIORITY.get(self.priority) if self.priority else None

    def to_dict(self) -> dict:
        return {
            # "text" is the serialized key for `description` — consumed by the engine/agenda tools
            "text": self.description,
            "priority": self.priority,
            "quadrant": self.quadrant,
            "topics": self.topics,
            "contexts": self.contexts,
            "due": self.due.isoformat() if self.due else None,
            "tickler": self.tickler.isoformat() if self.tickler else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "done": self.done,
            "id": self.id,
        }
