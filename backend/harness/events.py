from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class AgentEvent:
    type: str
    turn_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_sse(self) -> str:
        return f"event: {self.type}\ndata: {json.dumps(asdict(self), ensure_ascii=False, default=str)}\n\n"
