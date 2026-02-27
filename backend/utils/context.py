from contextvars import ContextVar
from typing import Optional

session_id_ctx: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
mcp_client_name_ctx: ContextVar[Optional[str]] = ContextVar("mcp_client_name", default=None)
mcp_client_scopes_ctx: ContextVar[list[str]] = ContextVar("mcp_client_scopes", default=[])
