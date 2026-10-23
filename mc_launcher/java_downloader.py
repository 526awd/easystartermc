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
            f"Microsoft JDK 自动下载暂不支持当前平台：{system or platform.system()} {machine or platform.machine()}"
        )
    extension = "zip" if system == "Windows" else "tar.gz"
    return system_key, arch, extension


def _archive_path(base: Path, name: str) -> Path:
    """Resolve a validated archive member below its extraction directory."""
    normalized = name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if (not normalized or member.is_absolute() or ".." in member.parts
            or (member.parts and ":" in member.parts[0]) or "\0" in normalized):
        raise RuntimeError(f"Microsoft JDK 压缩包包含不安全路径：{name!r}")
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
                raise RuntimeError("Microsoft JDK ZIP 中包含不支持的符号链接。")
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
                    raise RuntimeError(f"无法解压 JDK 文件：{member.name}")
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
                    raise RuntimeError(f"Microsoft JDK 压缩包包含不安全链接：{member.name!r}")
                if member.issym():
                    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), link_name))
                else:
                    resolved = posixpath.normpath(link_name)
                if resolved == ".." or resolved.startswith("../"):
                    raise RuntimeError(f"Microsoft JDK 压缩包包含越界链接：{member.name!r}")
                target.parent.mkdir(parents=True, exist_ok=True)
                link_target = _archive_path(destination, resolved)
                if member.issym():
                    os.symlink(link_name, target)
                else:
                    if not link_target.is_file():
                        raise RuntimeError(f"Microsoft JDK 压缩包硬链接目标不存在：{member.linkname!r}")
                    os.link(link_target, target)
            else:
                raise RuntimeError(f"Microsoft JDK 压缩包包含不支持的文件类型：{member.name!r}")


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
                    raise OSError(f"下载长度不匹配（预期 {total}，收到 {completed} 字节）")
            return
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(attempt)
    raise RuntimeError(f"Microsoft JDK 下载重试 3 次后仍失败：{url}（{last_error}）") from last_error


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
            raise RuntimeError(f"拒绝清理运行库目录之外的路径：{target}")
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
            f"Microsoft Build of OpenJDK 当前没有可用于 Java {required_major} 的受支持 LTS 版本。"
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

        _download(url, archive_path, progress_callback, f"下载 Microsoft JDK {jdk_major}")
        _download(checksum_url, checksum_path, None, "下载 Microsoft JDK 校验文件")
        checksum_text = checksum_path.read_text(encoding="ascii", errors="replace")
        expected = re.search(r"\b([0-9a-fA-F]{64})\b", checksum_text)
        if not expected:
            raise RuntimeError(f"Microsoft JDK 校验文件格式无效：{checksum_url}")
        actual = _sha256(archive_path)
        if actual.lower() != expected.group(1).lower():
            raise RuntimeError("Microsoft JDK SHA-256 校验失败，已拒绝解压。")

        if progress_callback:
            progress_callback(0, 1, f"校验通过，解压 Microsoft JDK {jdk_major}")
        if extension == "zip":
            _extract_zip(archive_path, unpacked)
        else:
            _extract_tar(archive_path, unpacked)

        java_path = _find_java(unpacked)
        actual_major = major_version(java_path) if java_path else None
        if actual_major != jdk_major:
            raise RuntimeError(
                f"Microsoft JDK 解压后版本校验失败（预期 Java {jdk_major}，检测到 {actual_major or '未知'}）。"
            )

        _remove_target(target, install_parent)
        unpacked.replace(target)
        java_path = _find_java(target)
        if not java_path:
            raise RuntimeError("Microsoft JDK 安装完成后未找到 Java 可执行文件。")

    if progress_callback:
        progress_callback(1, 1, f"Microsoft JDK {jdk_major} 已就绪")
    return java_path, jdk_major
