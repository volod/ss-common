"""Sidecar files next to a media file, and a small JSON client for HTTP sidecar services.

`HttpSidecarClient` needs the `web` extra (httpx), imported only when a request is made.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Row keys, in order, that carry a row's time; rows are sorted by the first one present.
TIME_KEYS = ("t", "timestamp")


def sidecar_path(media_path: str | Path, suffix: str) -> Path:
    """`media_path` with its suffix replaced by `suffix` (for example `.gps.jsonl`)."""
    return Path(media_path).with_suffix(suffix)


def _row_time(row: dict[str, Any]) -> float:
    for key in TIME_KEYS:
        if key in row:
            try:
                return float(row[key] or 0.0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def load_jsonl_sidecar(path: str | Path) -> list[dict[str, Any]]:
    """JSON-object rows of a JSONL file sorted by time; blank, invalid, and non-object lines
    are skipped, and an absent file yields no rows."""
    candidate = Path(path)
    if not candidate.is_file():
        return []
    rows: list[dict[str, Any]] = []
    skipped = 0
    with candidate.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if isinstance(payload, dict):
                rows.append(payload)
            else:
                skipped += 1
    if skipped:
        logger.debug("%s: skipped %d invalid sidecar lines", candidate.name, skipped)
    rows.sort(key=_row_time)
    return rows


def load_media_jsonl_sidecar(media_path: str | Path, suffix: str) -> list[dict[str, Any]]:
    return load_jsonl_sidecar(sidecar_path(media_path, suffix))


class HttpSidecarClient:
    """Base for HTTP-backed sidecars: unconfigured (empty base URL) clients return None."""

    def __init__(self, *, backend_name: str, base_url: str | None, timeout_sec: float) -> None:
        self._backend_name = str(backend_name or "").strip().lower()
        self._base_url = str(base_url or "").rstrip("/")
        self._timeout_sec = float(timeout_sec)

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url)

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> Any | None:
        """Decoded JSON response; None when unconfigured or (with `allow_404`) not found."""
        if not self.is_configured:
            return None
        import httpx

        async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
            resp = await client.request(method, f"{self._base_url}{path}", json=payload)
            if allow_404 and resp.status_code == httpx.codes.NOT_FOUND:
                return None
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def unwrap_dict_payload(data: Any, *, field: str | None = None) -> dict[str, Any] | None:
        """`data[field]` when it is an object, else `data` when it is an object, else None."""
        if not isinstance(data, dict):
            return None
        if field and isinstance(data.get(field), dict):
            nested: dict[str, Any] = data[field]
            return nested
        return data

    async def stats(self) -> dict[str, Any]:
        if not self.is_configured:
            return {"configured": False, "backend": self._backend_name}
        data = await self.request_json("GET", "/stats")
        if isinstance(data, dict):
            return {"configured": True, "backend": self._backend_name, **data}
        return {"configured": True, "backend": self._backend_name}
