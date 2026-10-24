"""Offline profiles and environment-provided official account credentials."""
import hashlib
import re
import uuid
from typing import Any

from .localization import tr


def offline_profile(username: str) -> dict[str, Any]:
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", username):
        raise ValueError(tr('accounts.offline_player_names_must_contain_english_letters_digits_or_underscores'))
    # Matches Java's UUID.nameUUIDFromBytes("OfflinePlayer:<name>".getBytes(UTF_8)).
    raw = bytearray(hashlib.md5(("OfflinePlayer:" + username).encode("utf-8")).digest())
    raw[6] = (raw[6] & 0x0F) | 0x30
    raw[8] = (raw[8] & 0x3F) | 0x80
    player_uuid = uuid.UUID(bytes=bytes(raw))
    return {"name": username, "uuid": str(player_uuid), "type": "offline"}


def current_profile(config: dict[str, Any]) -> dict[str, Any]:
    profiles = config.get("profiles", [])
    active = config.get("active_profile", "")
    for profile in profiles:
        if profile.get("profile_key", profile.get("name")) == active:
            return profile
    if profiles:
        config["active_profile"] = profiles[0].get("profile_key", profiles[0].get("name", ""))
        return profiles[0]
    # Migrate the earlier single-profile settings on first launch.
    if config.get("username"):
        profile = {"name": config["username"], "uuid": config.get("uuid", ""), "type": "microsoft"}
        config["profiles"] = [profile]
        config["active_profile"] = profile["name"]
        return profile
    return {}


def launch_identity(profile: dict[str, Any], client_id: str | None = None) -> dict[str, str]:
    if profile.get("type") == "offline":
        return {"name": profile["name"], "uuid": profile["uuid"].replace("-", ""),
                "token": "0", "user_type": "legacy"}
    if profile.get("type") == "microsoft" and profile.get("client_id"):
        from .auth_microsoft import OFFICIAL_CLIENT_ID, minecraft_identity
        return minecraft_identity(profile, profile.get("client_id") or client_id or OFFICIAL_CLIENT_ID)
    if profile.get("type") == "yggdrasil":
        from .auth_yggdrasil import minecraft_identity
        return minecraft_identity(profile)
    # Compatibility for profiles created before OAuth support.
    import os
    token = os.environ.get("MC_ACCESS_TOKEN", "")
    if not token or not profile.get("uuid"):
        raise RuntimeError(tr('accounts.this_profile_has_no_microsoft_oauth_session_sign_in_from_the_accounts_menu'))
    return {"name": profile["name"], "uuid": profile["uuid"].replace("-", ""), "token": token, "user_type": "msa"}
