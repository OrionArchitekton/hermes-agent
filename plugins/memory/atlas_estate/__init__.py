"""Atlas estate read-only recall provider.

This provider bridges Hermes to the Orion Atlas memory executor using the
existing MemoryProvider interface. It only performs governed read calls against
``/internal/memory/search`` and exposes no model tools, so it adds recall
context without growing the per-turn tool schema.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from agent.memory_provider import MemoryProvider
from hermes_cli.config import cfg_get

logger = logging.getLogger(__name__)


DEFAULT_CONFIG: Dict[str, Any] = {
    "base_url": "http://100.80.188.24:8097",
    "user_id": "service:mcp",
    "tenant_id": "orion",
    "namespace": "ops",
    "top_k": 5,
    "timeout": 3.0,
    "max_chars": 2500,
    "enabled": True,
}


def _load_config() -> Dict[str, Any]:
    try:
        from hermes_constants import get_hermes_home
        import yaml

        config_path = get_hermes_home() / "config.yaml"
        if not config_path.exists():
            return dict(DEFAULT_CONFIG)
        with open(config_path, encoding="utf-8-sig") as f:
            root = yaml.safe_load(f) or {}
        configured = cfg_get(root, "memory", "atlas_estate", default={}) or {}
        if not isinstance(configured, dict):
            configured = {}
        merged = dict(DEFAULT_CONFIG)
        merged.update(configured)
        return merged
    except Exception:
        return dict(DEFAULT_CONFIG)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _as_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _clean_base_url(value: Any) -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return raw


class AtlasEstateMemoryProvider(MemoryProvider):
    """Read-only Atlas memory recall for Orion estate context."""

    def __init__(self, config: Dict[str, Any] | None = None):
        self._config = config or _load_config()
        self._session_id = ""

    @property
    def name(self) -> str:
        return "atlas_estate"

    def is_available(self) -> bool:
        if not _as_bool(self._config.get("enabled", True)):
            return False
        return bool(
            _clean_base_url(self._config.get("base_url"))
            and str(self._config.get("user_id", "")).strip()
            and str(self._config.get("tenant_id", "")).strip()
            and str(self._config.get("namespace", "")).strip()
        )

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id

    def system_prompt_block(self) -> str:
        namespace = str(self._config.get("namespace", DEFAULT_CONFIG["namespace"])).strip()
        return (
            "# Atlas Estate Recall\n"
            "Read-only Atlas memory recall is active for Orion estate context. "
            f"Namespace: {namespace}. Treat recalled items as historical context; "
            "verify live state before operational claims or changes."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not query or not self.is_available():
            return ""
        try:
            response = self._search(query)
        except Exception as exc:
            logger.debug("Atlas estate recall failed: %s", exc)
            return ""

        hits = response.get("hits") or []
        if not isinstance(hits, list) or not hits:
            return ""

        max_chars = _as_int(self._config.get("max_chars"), 2500, minimum=500, maximum=8000)
        lines = ["## Atlas Estate Recall", "Read-only historical context from Atlas memory:"]
        used_chars = sum(len(line) + 1 for line in lines)

        for hit in hits:
            if not isinstance(hit, dict):
                continue
            content = str(hit.get("content") or "").strip()
            if not content:
                continue
            namespace = str(hit.get("namespace") or "").strip()
            similarity = hit.get("similarity")
            prefix = f"- [{namespace or unknown}"
            if isinstance(similarity, (float, int)):
                prefix += f" sim={similarity:.3f}"
            prefix += "] "
            line = prefix + " ".join(content.split())
            remaining = max_chars - used_chars
            if remaining <= 0:
                break
            if len(line) > remaining:
                line = line[: max(0, remaining - 4)].rstrip() + "..."
            lines.append(line)
            used_chars += len(line) + 1
            if used_chars >= max_chars:
                break

        return "\n".join(lines) if len(lines) > 2 else ""

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: List[Dict[str, Any]] | None = None,
    ) -> None:
        return None

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return []

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {"key": "base_url", "description": "Atlas memory base URL", "default": DEFAULT_CONFIG["base_url"]},
            {"key": "user_id", "description": "Atlas internal read principal", "default": DEFAULT_CONFIG["user_id"]},
            {"key": "tenant_id", "description": "Atlas memory tenant id", "default": DEFAULT_CONFIG["tenant_id"]},
            {"key": "namespace", "description": "Atlas memory namespace/lane", "default": DEFAULT_CONFIG["namespace"]},
            {"key": "top_k", "description": "Maximum hits to recall", "default": str(DEFAULT_CONFIG["top_k"])},
        ]

    def _search(self, query: str) -> Dict[str, Any]:
        base_url = _clean_base_url(self._config.get("base_url"))
        top_k = _as_int(self._config.get("top_k"), 5, minimum=1, maximum=20)
        timeout = _as_float(self._config.get("timeout"), 3.0, minimum=0.5, maximum=15.0)
        payload = {
            "user_id": str(self._config.get("user_id", DEFAULT_CONFIG["user_id"])).strip(),
            "tenant_id": str(self._config.get("tenant_id", DEFAULT_CONFIG["tenant_id"])).strip(),
            "namespace": str(self._config.get("namespace", DEFAULT_CONFIG["namespace"])).strip(),
            "query_text": query,
            "top_k": top_k,
            "envelope": None,
        }
        request = urllib.request.Request(
            f"{base_url}/internal/memory/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(1024 * 1024).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            logger.debug("Atlas estate recall denied: HTTP %s", exc.code)
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}


def register(ctx) -> None:
    ctx.register_memory_provider(AtlasEstateMemoryProvider())
