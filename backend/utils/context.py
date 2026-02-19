from contextvars import ContextVar
from typing import Optional

session_id_ctx: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
