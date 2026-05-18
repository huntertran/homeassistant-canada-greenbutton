"""HTTP endpoint accepting GreenButton XML uploads from external fetchers."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_SAFE_SOURCE = re.compile(r"[^a-z0-9_-]")
MAX_BYTES = 25 * 1024 * 1024  # 25 MB cap


class GreenButtonUploadView(HomeAssistantView):
    """POST /api/canada_greenbutton/upload — raw XML body, bearer auth."""

    url = "/api/canada_greenbutton/upload"
    name = "api:canada_greenbutton:upload"
    requires_auth = True

    def __init__(self, hass: HomeAssistant, watch_dir: Path) -> None:
        self.hass = hass
        self.watch_dir = watch_dir

    async def post(self, request: web.Request) -> web.Response:
        raw_source = (request.headers.get("X-Source") or request.query.get("source") or "upload").lower()
        source = _SAFE_SOURCE.sub("", raw_source) or "upload"

        body = await request.read()
        if not body:
            return self.json_message("empty body", status_code=400)
        if len(body) > MAX_BYTES:
            return self.json_message("payload too large", status_code=413)
        if not body.lstrip().startswith(b"<"):
            return self.json_message("not XML", status_code=400)

        await self.hass.async_add_executor_job(self.watch_dir.mkdir, 0o755, True, True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        target = self.watch_dir / f"{source}_{ts}.xml"
        tmp = target.with_suffix(".xml.part")

        def _write_atomic() -> None:
            tmp.write_bytes(body)
            tmp.replace(target)

        try:
            await self.hass.async_add_executor_job(_write_atomic)
        except OSError as err:
            _LOGGER.exception("Failed to write upload: %s", err)
            return self.json_message("write failed", status_code=500)

        _LOGGER.info("Accepted GreenButton upload: %s (%d bytes)", target, len(body))
        return self.json({"ok": True, "path": str(target), "bytes": len(body)})
