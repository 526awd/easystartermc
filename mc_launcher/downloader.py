"""Concurrent URL downloads with size/hash verification and atomic replacement."""
import hashlib
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen
from typing import Any, Callable

from .metadata import USER_AGENT

Progress = Callable[[int, int, str], None]


def valid_file(path: Path, sha1: str | None, size: int | None = None) -> bool:
    if not path.is_file():
        return False
    if size is not None and path.stat().st_size != size:
        return False
    if sha1:
        digest = hashlib.sha1()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest().lower() == sha1.lower()
    return True


def download_one(url: str, destination: Path, sha1: str | None = None,
                 size: int | None = None, retries: int = 3) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if valid_file(destination, sha1, size):
        return False
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return _download_attempt(url, destination, sha1, size)
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"下载重试 {retries} 次后仍失败：{url} ({last_error})") from last_error


def _download_attempt(url: str, destination: Path, sha1: str | None,
                      size: int | None) -> bool:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    temp_name = None
    digest = hashlib.sha1()
    received = 0
    try:
        with urlopen(request, timeout=60) as response, tempfile.NamedTemporaryFile(
                mode="wb", dir=destination.parent, delete=False) as output:
            temp_name = output.name
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                digest.update(block)
                received += len(block)
        if size is not None and received != size:
            raise IOError(f"文件大小不符 ({received} != {size}): {url}")
        if sha1 and digest.hexdigest().lower() != sha1.lower():
            raise IOError(f"SHA-1 校验失败: {url}")
        os.replace(temp_name, destination)
        temp_name = None
        return True
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def download_many(jobs: list[tuple[str, Path, str | None, int | None]],
                  progress: Progress | None = None, workers: int = 12) -> None:
    total = len(jobs)
    if total == 0:
        return
    errors: list[Exception] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, *job): job[1] for job in jobs}
        for done, future in enumerate(as_completed(futures), 1):
            try:
                future.result()
            except Exception as exc:
                errors.append(exc)
            if progress:
                progress(done, total, futures[future].name)
    if errors:
        first = errors[0]
        raise RuntimeError(f"{len(errors)} 个文件下载失败，首个错误：{first}") from first

