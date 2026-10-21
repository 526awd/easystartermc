"""Install vanilla Java versions and their assets/libraries from Mojang metadata."""
import json
import os
import platform
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .downloader import download_many
from .metadata import version_metadata
from .platforms import allowed, native_artifact

InstallProgress = Callable[[int, int, str], None]


def safe_relative(value: str) -> Path:
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError(f"官方元数据包含非法路径：{value}")
    return Path(*posix.parts)


def maven_path(coordinate: str) -> str:
    parts = coordinate.split(":")
    if len(parts) < 3:
        raise ValueError(f"无效 Maven 坐标：{coordinate}")
    group, artifact, version = parts[:3]
    classifier = parts[3] if len(parts) > 3 else ""
    extension = parts[4] if len(parts) > 4 else "jar"
    filename = f"{artifact}-{version}{('-' + classifier) if classifier else ''}.{extension}"
    return "/".join([group.replace(".", "/"), artifact, version, filename])


def _library_jobs(metadata: dict[str, Any], root: Path) -> list[tuple[str, Path, str | None, int | None]]:
    jobs = []
    for library in metadata.get("libraries", []):
        if not allowed(library.get("rules")):
            continue
        downloads = library.get("downloads", {})
        artifact = downloads.get("artifact")
        if artifact:
            rel_path = artifact.get("path") or maven_path(library["name"])
            destination = root / "libraries" / safe_relative(rel_path)
            url = artifact.get("url")
            if not url:
                url = library.get("url", "https://libraries.minecraft.net/").rstrip("/") + "/" + rel_path
            jobs.append((url, destination, artifact.get("sha1"), artifact.get("size")))
        # A downloads block containing classifiers but no artifact describes a
        # native-only dependency. Do not invent a plain JAR URL for it.
        elif library.get("name") and not downloads:
            rel_path = maven_path(library["name"])
            destination = root / "libraries" / safe_relative(rel_path)
            base_url = library.get("url", "https://libraries.minecraft.net/").rstrip("/")
            jobs.append((base_url + "/" + rel_path, destination, None, None))
        native = native_artifact(library)
        if native:
            destination = root / "libraries" / safe_relative(native["path"])
            jobs.append((native["url"], destination, native.get("sha1"), native.get("size")))
    return jobs


def ensure_libraries(root: Path, metadata: dict[str, Any],
                     progress: InstallProgress | None = None) -> None:
    """Download any absent or hash-invalid runtime libraries for an installed version."""
    jobs = _library_jobs(metadata, root)
    download_many(jobs, progress)


def install(root: Path, version_id: str, manifest: dict[str, Any],
            progress: InstallProgress | None = None) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    metadata = version_metadata(manifest, version_id)
    version_dir = root / "versions" / version_id
    version_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = version_dir / f"{version_id}.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    jobs = _library_jobs(metadata, root)
    downloads = metadata.get("downloads", {})
    client = downloads.get("client")
    if not client:
        raise RuntimeError(f"版本 {version_id} 没有官方客户端 JAR 下载项。")
    jobs.append((client["url"], version_dir / f"{version_id}.jar", client.get("sha1"), client.get("size")))

    asset_index_info = metadata.get("assetIndex")
    asset_index: dict[str, Any] | None = None
    if asset_index_info:
        index_path = root / "assets" / "indexes" / safe_relative(asset_index_info["id"] + ".json")
        download_many([(asset_index_info["url"], index_path, asset_index_info.get("sha1"), asset_index_info.get("size"))])
        asset_index = json.loads(index_path.read_text(encoding="utf-8"))
        for item in asset_index.get("objects", {}).values():
            digest = item["hash"]
            object_path = root / "assets" / "objects" / digest[:2] / digest
            jobs.append((f"https://resources.download.minecraft.net/{digest[:2]}/{digest}", object_path,
                         digest, item.get("size")))
    logging_file = metadata.get("logging", {}).get("client", {}).get("file", {})
    if logging_file.get("url") and logging_file.get("id"):
        log_path = root / "assets" / "log_configs" / safe_relative(logging_file["id"])
        jobs.append((logging_file["url"], log_path, logging_file.get("sha1"), logging_file.get("size")))

    def report(done: int, total: int, filename: str) -> None:
        if progress:
            progress(done, total, filename)

    download_many(jobs, report)
    if asset_index and asset_index.get("map_to_resources"):
        virtual = root / "assets" / "virtual" / safe_relative(asset_index_info["id"])
        for logical_name, item in asset_index["objects"].items():
            digest = item["hash"]
            source = root / "assets" / "objects" / digest[:2] / digest
            destination = virtual / safe_relative(logical_name)
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(source, destination)
                except OSError:
                    shutil.copy2(source, destination)
    return metadata
