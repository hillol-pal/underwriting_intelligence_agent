"""Stop the next model call once the investigation deadline has passed.

This does not abort an HTTP call that has already started. The chat client's
60-second timeout bounds that call.
"""
import time
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, hook_config


class DeadlineMiddleware(AgentMiddleware):
    def __init__(self, deadline: float) -> None:
        super().__init__()
        self.deadline = deadline

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if time.monotonic() > self.deadline:
            return {"jump_to": "end"}
        return None

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if time.monotonic() > self.deadline:
            return {"jump_to": "end"}
        return None
