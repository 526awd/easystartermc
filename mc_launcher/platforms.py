"""Platform matching helpers for Mojang version rules and native classifiers."""
import platform
import re
from typing import Any

OS_NAME = {"Windows": "windows", "Linux": "linux", "Darwin": "osx"}.get(platform.system(), "linux")
MACHINE = platform.machine().lower()
JAVA_ARCH = "64" if MACHINE in {"x86_64", "amd64", "aarch64", "arm64"} else "32"


def allowed(rules: list[dict[str, Any]] | None) -> bool:
    if not rules:
        return True
    result = False
    for rule in rules:
        os_rule = rule.get("os", {})
        if os_rule.get("name") and os_rule["name"] != OS_NAME:
            continue
        if os_rule.get("arch") and not re.search(os_rule["arch"], platform.machine()):
            continue
        if os_rule.get("version") and not re.search(os_rule["version"], platform.release()):
            continue
        features = rule.get("features", {})
        if any(bool(expected) for expected in features.values()):
            continue
        result = rule.get("action") == "allow"
    return result


def native_key() -> str:
    return {"windows": "natives-windows", "linux": "natives-linux", "osx": "natives-osx"}[OS_NAME]


def native_artifact(library: dict[str, Any]) -> dict[str, Any] | None:
    classifiers = library.get("downloads", {}).get("classifiers", {})
    prefix = library.get("natives", {}).get(OS_NAME)
    if not prefix:
        return None
    classifier = prefix.replace("${arch}", JAVA_ARCH)
    artifact = classifiers.get(classifier)
    if artifact is None:
        artifact = classifiers.get(native_key() + ("-64" if JAVA_ARCH == "64" else "-32"))
    if artifact is None and OS_NAME == "osx":
        artifact = classifiers.get(native_key())
    return artifact
