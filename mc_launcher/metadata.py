"""Mojang official version manifest access."""
import json
import time
from urllib.request import Request, urlopen
from typing import Any

from .download_sources import OFFICIAL, candidates

from .localization import tr

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
USER_AGENT = "MC-TUI/0.2 (Minecraft Java launcher)"


def get_json(url: str, source: str = OFFICIAL) -> dict[str, Any]:
    last_error: Exception | None = None
    for candidate in candidates(url, source):
        request = Request(candidate, headers={"User-Agent": USER_AGENT})
        for attempt in range(4):
            try:
                with urlopen(request, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(2 ** attempt)
    raise RuntimeError(tr('metadata.could_not_read_official_metadata_after_attempts', v_a=url, v_b=last_error)) from last_error


def version_list(source: str = OFFICIAL) -> dict[str, Any]:
    return get_json(MANIFEST_URL, source)


def version_metadata(manifest: dict[str, Any], version_id: str,
                     source: str = OFFICIAL) -> dict[str, Any]:
    item = next((entry for entry in manifest.get("versions", []) if entry.get("id") == version_id), None)
    if item is None:
        raise ValueError(tr('metadata.version_is_not_in_the_official_version_manifest', v_a=version_id))
    return get_json(item["url"], source)
