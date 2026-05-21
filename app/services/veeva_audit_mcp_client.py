import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)


class VeevaAuditMcpClientError(Exception):
    def __init__(self, message: str, status_code: int = 502, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data or {}


class VeevaAuditMcpClient:
    """Small adapter for the standalone Veeva MCP server.

    This client never stores or sends Vault credentials. Credentials stay in
    the sibling veeva_mcp_server process and its local environment.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.VEEVA_MCP_BASE_URL.rstrip("/")
        self.timeout = httpx.Timeout(45.0)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(method, url, json=json_payload)
        except httpx.TimeoutException as exc:
            logger.warning("Veeva MCP request timed out.", extra={"mcp_base_url": self.base_url, "path": path})
            raise VeevaAuditMcpClientError(
                "Veeva MCP server request timed out.",
                data={"mcp_base_url": self.base_url},
            ) from exc
        except httpx.RequestError as exc:
            logger.warning(
                "Veeva MCP server is unavailable.",
                extra={"mcp_base_url": self.base_url, "path": path, "error_type": type(exc).__name__},
            )
            raise VeevaAuditMcpClientError(
                "Veeva MCP server is unavailable. Confirm it is running and reachable.",
                data={"mcp_base_url": self.base_url},
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning(
                "Veeva MCP server returned a non-JSON response.",
                extra={"mcp_base_url": self.base_url, "path": path, "status_code": response.status_code},
            )
            raise VeevaAuditMcpClientError(
                "Veeva MCP server returned an unexpected response.",
                data={"mcp_base_url": self.base_url, "mcp_status_code": response.status_code},
            ) from exc

        if not isinstance(payload, dict):
            raise VeevaAuditMcpClientError(
                "Veeva MCP server returned an invalid response shape.",
                data={"mcp_base_url": self.base_url, "mcp_status_code": response.status_code},
            )

        payload.setdefault("_mcp_status_code", response.status_code)
        return payload

    async def health_check(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def get_audit_trail(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/tools/get_veeva_audit_trail", json_payload=payload)
