"""Download and unpack Microsoft Build of OpenJDK archives."""
import hashlib
import os
import platform
import posixpath
import re
import shutil
import stat
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from .java_runtime import major_version

from .localization import tr

ProgressCallback = Callable[[int, int, str], None]
_SUPPORTED_MAJORS = (11, 17, 21, 25)
_CHUNK_SIZE = 1024 * 1024


def compatible_major(required: int) -> int | None:
    """Return the lowest Microsoft LTS JDK major that can run the target bytecode."""
    return next((major for major in _SUPPORTED_MAJORS if major >= required), None)


def _platform_archive() -> tuple[str, str, str]:
    system = platform.system()
    system_key = {"Windows": "windows", "Linux": "linux", "Darwin": "macOS"}.get(system)
    machine = platform.machine().lower()
    arch = {
        "amd64": "x64", "x86_64": "x64", "x64": "x64",
        "arm64": "aarch64", "aarch64": "aarch64",
    }.get(machine)
    if not system_key or not arch:
        raise RuntimeError(
            tr('java_downloader.automatic_microsoft_jdk_downloads_are_not_supported_on_this_platform', v_a=system or platform.system(), v_b=machine or platform.machine())
        )
    extension = "zip" if system == "Windows" else "tar.gz"
    return system_key, arch, extension


def _archive_path(base: Path, name: str) -> Path:
    """Resolve a validated archive member below its extraction directory."""
    normalized = name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if (not normalized or member.is_absolute() or ".." in member.parts
            or (member.parts and ":" in member.parts[0]) or "\0" in normalized):
        raise RuntimeError(tr('java_downloader.microsoft_jdk_archive_contains_an_unsafe_path', v_a=repr(name)))
    return base.joinpath(*member.parts)


def _extract_zip(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = _archive_path(destination, member.filename)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise RuntimeError(tr('java_downloader.the_microsoft_jdk_zip_contains_an_unsupported_symbolic_link'))
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, _CHUNK_SIZE)


def _extract_tar(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            target = _archive_path(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError(tr('java_downloader.could_not_extract_jdk_file', v_a=member.name))
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, _CHUNK_SIZE)
                try:
                    target.chmod(member.mode & 0o777)
                except OSError:
                    pass
            elif member.issym() or member.islnk():
                link_name = member.linkname.replace("\\", "/")
                link_path = PurePosixPath(link_name)
                if link_path.is_absolute() or (link_path.parts and ":" in link_path.parts[0]):
                    raise RuntimeError(tr('java_downloader.microsoft_jdk_archive_contains_an_unsafe_link', v_a=repr(member.name)))
                if member.issym():
                    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), link_name))
                else:
                    resolved = posixpath.normpath(link_name)
                if resolved == ".." or resolved.startswith("../"):
                    raise RuntimeError(tr('java_downloader.microsoft_jdk_archive_contains_a_link_outside_the_extraction_directory', v_a=repr(member.name)))
                target.parent.mkdir(parents=True, exist_ok=True)
                link_target = _archive_path(destination, resolved)
                if member.issym():
                    os.symlink(link_name, target)
                else:
                    if not link_target.is_file():
                        raise RuntimeError(tr('java_downloader.microsoft_jdk_archive_hard_link_target_does_not_exist', v_a=repr(member.linkname)))
                    os.link(link_target, target)
            else:
                raise RuntimeError(tr('java_downloader.microsoft_jdk_archive_contains_an_unsupported_file_type', v_a=repr(member.name)))


def _find_java(directory: Path) -> Path | None:
    binary_name = "java.exe" if platform.system() == "Windows" else "java"
    for candidate in directory.rglob(binary_name):
        if candidate.parent.name.lower() == "bin" and candidate.is_file():
            return candidate
    return None


def _download(url: str, destination: Path, callback: ProgressCallback | None,
              description: str) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "easystartermc"})
            with urllib.request.urlopen(request, timeout=45) as response:
                total = int(response.headers.get("Content-Length", "0") or 0)
                completed = 0
                if callback:
                    callback(0, max(total, 1), description)
                with destination.open("wb") as output:
                    while True:
                        chunk = response.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        output.write(chunk)
                        completed += len(chunk)
                        if callback:
                            callback(completed, max(total, completed, 1), description)
                if total and completed != total:
                    raise OSError(tr('java_downloader.download_size_mismatch_expected_received_bytes', v_a=total, v_b=completed))
            return
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(attempt)
    raise RuntimeError(tr('java_downloader.microsoft_jdk_download_failed_after_attempts', v_a=url, v_b=last_error)) from last_error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_target(target: Path, parent: Path) -> None:
    if target.is_symlink():
        target.unlink()
    elif target.exists():
        if target.resolve().parent != parent.resolve():
            raise RuntimeError(tr('java_downloader.refusing_to_remove_a_path_outside_the_runtime_directory', v_a=target))
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()


def ensure_microsoft_jdk(required_major: int, runtime_root: Path,
                         progress_callback: ProgressCallback | None = None) -> tuple[Path, int]:
    """Download a Microsoft LTS JDK into the launcher's private runtime directory."""
    jdk_major = compatible_major(required_major)
    if jdk_major is None:
        raise RuntimeError(
            tr('java_downloader.microsoft_build_of_openjdk_has_no_supported_lts_release_for_java', v_a=required_major)
        )

    os_key, arch, extension = _platform_archive()
    cache_name = f"jdk-{jdk_major}-{os_key.lower()}-{arch}"
    install_parent = runtime_root / "microsoft-openjdk"
    target = install_parent / cache_name
    if target.is_dir():
        cached_java = _find_java(target)
        if cached_java and major_version(cached_java) == jdk_major:
            return cached_java, jdk_major

    install_parent.mkdir(parents=True, exist_ok=True)
    file_platform = os_key.lower() if os_key != "macOS" else "macOS"
    filename = f"microsoft-jdk-{jdk_major}-{file_platform}-{arch}.{extension}"
    url = f"https://aka.ms/download-jdk/{filename}"
    checksum_url = f"{url}.sha256sum.txt"

    with tempfile.TemporaryDirectory(prefix="jdk-download-", dir=install_parent) as temp_name:
        temp = Path(temp_name)
        archive_path = temp / filename
        checksum_path = temp / "checksum.txt"
        unpacked = temp / "unpacked"
        unpacked.mkdir()

        _download(url, archive_path, progress_callback, tr('java_downloader.downloading_microsoft_jdk', v_a=jdk_major))
        _download(checksum_url, checksum_path, None, tr('java_downloader.downloading_microsoft_jdk_checksum'))
        checksum_text = checksum_path.read_text(encoding="ascii", errors="replace")
        expected = re.search(r"\b([0-9a-fA-F]{64})\b", checksum_text)
        if not expected:
            raise RuntimeError(tr('java_downloader.microsoft_jdk_checksum_file_is_invalid', v_a=checksum_url))
        actual = _sha256(archive_path)
        if actual.lower() != expected.group(1).lower():
            raise RuntimeError(tr('java_downloader.microsoft_jdk_sha_verification_failed_the_archive_was_not_extracted'))

        if progress_callback:
            progress_callback(0, 1, tr('java_downloader.checksum_verified_extracting_microsoft_jdk', v_a=jdk_major))
        if extension == "zip":
            _extract_zip(archive_path, unpacked)
        else:
            _extract_tar(archive_path, unpacked)

        java_path = _find_java(unpacked)
        actual_major = major_version(java_path) if java_path else None
        if actual_major != jdk_major:
            raise RuntimeError(
                tr('java_downloader.microsoft_jdk_version_check_failed_after_extraction_expected_java_detected', v_a=jdk_major, v_b=actual_major or tr('java_downloader.unknown'))
            )

        _remove_target(target, install_parent)
        unpacked.replace(target)
        java_path = _find_java(target)
        if not java_path:
            raise RuntimeError(tr('java_downloader.could_not_find_the_java_executable_after_installing_microsoft_jdk'))

    if progress_callback:
        progress_callback(1, 1, tr('java_downloader.microsoft_jdk_is_ready', v_a=jdk_major))
    return java_path, jdk_major
