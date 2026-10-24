"""Concurrent URL downloads with size/hash verification and atomic replacement."""
import hashlib
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen
from typing import Any, Callable

from .download_sources import OFFICIAL, candidates
from .metadata import USER_AGENT

from .localization import tr

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
                 size: int | None = None, retries: int = 3,
                 source: str = OFFICIAL) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if valid_file(destination, sha1, size):
        return False
    last_error: Exception | None = None
    for candidate in candidates(url, source):
        for attempt in range(retries + 1):
            try:
                return _download_attempt(candidate, destination, sha1, size)
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(tr('downloader.the_selected_and_official_download_sources_failed_after_retries', v_a=url, v_b=last_error)) from last_error


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
            raise IOError(tr('downloader.file_size_mismatch', v_a=received, v_b=size, v_c=url))
        if sha1 and digest.hexdigest().lower() != sha1.lower():
            raise IOError(tr('downloader.sha_verification_failed', v_a=url))
        os.replace(temp_name, destination)
        temp_name = None
        return True
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def download_many(jobs: list[tuple[str, Path, str | None, int | None]],
                  progress: Progress | None = None, workers: int = 12,
                  source: str = OFFICIAL) -> None:
    total = len(jobs)
    if total == 0:
        return
    errors: list[Exception] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, *job, source=source): job[1] for job in jobs}
        for done, future in enumerate(as_completed(futures), 1):
            try:
                future.result()
            except Exception as exc:
                errors.append(exc)
            if progress:
                progress(done, total, futures[future].name)
    if errors:
        first = errors[0]
        raise RuntimeError(tr('downloader.file_downloads_failed_first_error', v_a=len(errors), v_b=first)) from first

