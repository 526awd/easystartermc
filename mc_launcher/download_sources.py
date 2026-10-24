"""Official and BMCLAPI download source URL mapping."""
from urllib.parse import urlsplit, urlunsplit

from .localization import tr

OFFICIAL = "official"
BMCLAPI = "bmclapi"
BMCLAPI_BASE = "https://bmclapi2.bangbang93.com"

SOURCE_LABELS = {OFFICIAL: 'download_sources.official_mojang', BMCLAPI: 'download_sources.bmclapi_mirror'}


def label(source: str) -> str:
    return tr(SOURCE_LABELS.get(source, SOURCE_LABELS[OFFICIAL]))


def mirror_url(url: str, source: str) -> str:
    """Map Mojang resource URLs to their documented BMCLAPI paths."""
    if source != BMCLAPI:
        return url
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host == "resources.download.minecraft.net":
        prefix = "/assets"
    elif host == "libraries.minecraft.net":
        prefix = "/maven"
    elif host in {
        "piston-meta.mojang.com",
        "piston-data.mojang.com",
        "launchermeta.mojang.com",
        "launcher.mojang.com",
    }:
        prefix = ""
    else:
        return url
    path = f"{prefix}{parsed.path}"
    return urlunsplit(("https", "bmclapi2.bangbang93.com", path, parsed.query, parsed.fragment))


def candidates(url: str, source: str) -> list[str]:
    """Return the selected source first, followed by official fallback."""
    primary = mirror_url(url, source)
    if primary == url:
        return [url]
    return [primary, url]
