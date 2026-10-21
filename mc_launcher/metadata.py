"""Mojang official version manifest access."""
import json
import time
from urllib.request import Request, urlopen
from typing import Any

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
USER_AGENT = "MC-TUI/0.2 (Minecraft Java launcher)"


def get_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"读取官方元数据重试 3 次后失败：{url} ({last_error})") from last_error


def version_list() -> dict[str, Any]:
    return get_json(MANIFEST_URL)


def version_metadata(manifest: dict[str, Any], version_id: str) -> dict[str, Any]:
    item = next((entry for entry in manifest.get("versions", []) if entry.get("id") == version_id), None)
    if item is None:
        raise ValueError(f"官方版本清单中没有 {version_id}。")
    return get_json(item["url"])
