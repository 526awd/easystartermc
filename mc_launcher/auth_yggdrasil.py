"""Yggdrasil third-party authentication and authlib-injector integration."""
import base64
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .localization import tr

TOKEN_SERVICE = "mc-tui-yggdrasil-tokens"
INJECTOR_API = "https://authlib-injector.yushi.moe/artifact/latest.json"


def _keyring() -> Any:
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError(tr('auth_yggdrasil.third_party_sign_in_requires_keyring_install_the_dependencies_in_requirements_txt')) from exc
    try:
        if keyring.get_keyring().priority <= 0:
            raise RuntimeError(tr('auth_yggdrasil.no_system_credential_store_is_available_configure_windows_credential_manager_macos_keychain_or_secret_service'))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(tr('auth_yggdrasil.could_not_access_the_system_credential_store', v_a=exc)) from exc
    return keyring


def _validate_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError(tr('auth_yggdrasil.authentication_server_url_cannot_be_empty'))
    if "://" not in url:
        url = "https://" + url
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(tr('auth_yggdrasil.authentication_server_url_must_be_a_valid_http_s_url'))
    if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(tr('auth_yggdrasil.the_authentication_server_must_use_https_http_is_allowed_only_for_localhost_loopback_addresses'))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/", "", ""))


def _get(url: str) -> tuple[bytes, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "MC-TUI/0.3"})
    try:
        with urlopen(request, timeout=30) as response:
            final_url = _validate_url(response.geturl())
            if urlsplit(final_url).scheme == "http" and urlsplit(final_url).hostname not in (
                    "localhost", "127.0.0.1", "::1"):
                raise RuntimeError(tr('auth_yggdrasil.the_authentication_server_redirected_to_insecure_public_http_the_connection_was_rejected'))
            if urlsplit(response.geturl()).scheme != "https" and urlsplit(url).scheme == "https":
                raise RuntimeError(tr('auth_yggdrasil.the_authentication_server_downgraded_an_https_request_to_insecure_http_the_connection_was_rejected'))
            return response.read(), response.headers
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(tr('auth_yggdrasil.authentication_server_request_failed_http', v_a=exc.code, v_b=detail)) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(tr('auth_yggdrasil.could_not_connect_to_the_authentication_server', v_a=exc)) from exc


def resolve_server(address: str) -> tuple[str, dict[str, Any]]:
    """Resolve an authlib-injector API root and fetch its metadata."""
    url = _validate_url(address)
    body, headers = _get(url)
    indication = headers.get("X-Authlib-Injector-API-Location")
    if indication:
        target = urljoin(url, indication)
        target = _validate_url(target)
        if target != url:
            url = target
            body, _ = _get(url)
    try:
        metadata = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(tr('auth_yggdrasil.the_authentication_server_url_did_not_return_valid_yggdrasil_metadata')) from exc
    if not isinstance(metadata, dict):
        raise RuntimeError(tr('auth_yggdrasil.authentication_server_metadata_is_invalid'))
    return url, metadata


def _request(url: str, payload: dict[str, Any], allow_empty: bool = False) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={
        "Accept": "application/json", "Content-Type": "application/json",
        "User-Agent": "MC-TUI/0.3",
    })
    try:
        with urlopen(request, timeout=30) as response:
            final_url = _validate_url(response.geturl())
            if urlsplit(final_url).scheme == "http" and urlsplit(final_url).hostname not in (
                    "localhost", "127.0.0.1", "::1"):
                raise RuntimeError(tr('auth_yggdrasil.the_yggdrasil_request_redirected_to_insecure_public_http_credentials_were_not_sent'))
            if urlsplit(url).scheme == "https" and urlsplit(response.geturl()).scheme != "https":
                raise RuntimeError(tr('auth_yggdrasil.the_yggdrasil_service_downgraded_https_to_http_credentials_were_not_sent'))
            raw = response.read()
    except HTTPError as exc:
        raw = exc.read()
        try:
            error = json.loads(raw.decode("utf-8"))
            message = error.get("errorMessage") or error.get("error") or raw.decode("utf-8", errors="replace")[:1000]
        except ValueError:
            message = raw.decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(tr('auth_yggdrasil.yggdrasil_sign_in_request_failed_http', v_a=exc.code, v_b=message)) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(tr('auth_yggdrasil.could_not_connect_to_the_yggdrasil_authentication_service', v_a=exc)) from exc
    if not raw and allow_empty:
        return {}
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(tr('auth_yggdrasil.the_yggdrasil_authentication_service_returned_an_invalid_response')) from exc
    if not isinstance(result, dict):
        raise RuntimeError(tr('auth_yggdrasil.the_yggdrasil_authentication_service_returned_an_unrecognized_response'))
    return result


def _endpoint(server: str, path: str) -> str:
    return urljoin(server, path)


def _profile_id(profile: dict[str, Any]) -> str:
    # Authentication responses use `id`; launcher profile records use `uuid`.
    value = str(profile.get("id") or profile.get("uuid", "")).replace("-", "")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", value):
        raise RuntimeError(tr('auth_yggdrasil.the_yggdrasil_service_returned_an_invalid_minecraft_uuid'))
    return value.lower()


def _token_key(server: str, player_uuid: str) -> str:
    return hashlib.sha256(f"{server}\n{player_uuid.lower()}".encode()).hexdigest()


def _save_tokens(keyring: Any, server: str, player_uuid: str, tokens: dict[str, str]) -> None:
    try:
        keyring.set_password(TOKEN_SERVICE, _token_key(server, player_uuid), json.dumps(tokens))
    except Exception as exc:
        raise RuntimeError(tr('auth_yggdrasil.could_not_save_the_sign_in_token_to_the_system_credential_store', v_a=exc)) from exc


def sign_in(server_address: str, username: str, password: str,
            choose_profile: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None) -> dict[str, str]:
    if not username.strip() or not password:
        raise ValueError(tr('auth_yggdrasil.account_name_and_password_cannot_be_empty'))
    server, _ = resolve_server(server_address)
    keyring = _keyring()
    client_token = str(uuid.uuid4())
    response = _request(_endpoint(server, "authserver/authenticate"), {
        "agent": {"name": "Minecraft", "version": 1}, "username": username.strip(),
        "password": password, "clientToken": client_token, "requestUser": True,
    })
    access_token = response.get("accessToken")
    if not access_token:
        raise RuntimeError(tr('auth_yggdrasil.the_yggdrasil_service_did_not_return_an_accesstoken'))
    client_token = str(response.get("clientToken") or client_token)
    selected = response.get("selectedProfile")
    if not selected:
        profiles = response.get("availableProfiles") or []
        if not profiles:
            raise RuntimeError(tr('auth_yggdrasil.this_account_has_no_available_minecraft_profile'))
        if len(profiles) == 1:
            selected = profiles[0]
        elif choose_profile:
            selected = choose_profile(profiles)
        else:
            raise RuntimeError(tr('auth_yggdrasil.this_account_has_multiple_game_profiles_select_one_in_the_launcher'))
        response = _request(_endpoint(server, "authserver/refresh"), {
            "accessToken": access_token, "clientToken": client_token,
            "selectedProfile": {"id": selected["id"], "name": selected["name"]},
            "requestUser": True,
        })
        access_token = response.get("accessToken") or access_token
        client_token = str(response.get("clientToken") or client_token)
        selected = response.get("selectedProfile") or selected
    player_uuid = _profile_id(selected)
    name = str(selected.get("name", ""))
    if not name:
        raise RuntimeError(tr('auth_yggdrasil.the_yggdrasil_service_did_not_return_a_game_profile_name'))
    _save_tokens(keyring, server, player_uuid, {"accessToken": str(access_token), "clientToken": client_token})
    return {"name": name, "uuid": player_uuid, "type": "yggdrasil", "auth_server": server,
            "profile_key": "yggdrasil:" + _token_key(server, player_uuid)}


def minecraft_identity(profile: dict[str, Any]) -> dict[str, str]:
    server = _validate_url(str(profile.get("auth_server", "")))
    player_uuid = _profile_id(profile)
    keyring = _keyring()
    try:
        raw = keyring.get_password(TOKEN_SERVICE, _token_key(server, player_uuid))
    except Exception as exc:
        raise RuntimeError(tr('auth_yggdrasil.could_not_read_the_system_credential_store', v_a=exc)) from exc
    if not raw:
        raise RuntimeError(tr('auth_yggdrasil.third_party_account_token_is_missing_sign_in_again_from_the_accounts_menu'))
    try:
        tokens = json.loads(raw)
        access_token, client_token = tokens["accessToken"], tokens["clientToken"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(tr('auth_yggdrasil.third_party_account_token_cache_is_corrupted_please_sign_in_again')) from exc
    try:
        _request(_endpoint(server, "authserver/validate"), {
            "accessToken": access_token, "clientToken": client_token,
        }, allow_empty=True)
    except RuntimeError:
        refreshed = _request(_endpoint(server, "authserver/refresh"), {
            "accessToken": access_token, "clientToken": client_token,
            "selectedProfile": {"id": player_uuid, "name": profile["name"]},
            "requestUser": True,
        })
        access_token = str(refreshed.get("accessToken", ""))
        client_token = str(refreshed.get("clientToken") or client_token)
        if not access_token:
            raise RuntimeError(tr('auth_yggdrasil.could_not_refresh_the_third_party_account_token_please_sign_in_again'))
        selected = refreshed.get("selectedProfile") or {}
        if selected and _profile_id(selected) != player_uuid:
            raise RuntimeError(tr('auth_yggdrasil.the_profile_returned_by_the_authentication_service_does_not_match_this_account_please_sign_in_again'))
        _save_tokens(keyring, server, player_uuid, {"accessToken": access_token, "clientToken": client_token})
    return {"name": profile["name"], "uuid": player_uuid, "token": str(access_token), "user_type": "mojang",
            "auth_server": server}


def remove_account(profile: dict[str, Any]) -> None:
    keyring = _keyring()
    server = _validate_url(str(profile.get("auth_server", "")))
    player_uuid = _profile_id(profile)
    name = _token_key(server, player_uuid)
    try:
        if keyring.get_password(TOKEN_SERVICE, name):
            keyring.delete_password(TOKEN_SERVICE, name)
    except Exception as exc:
        raise RuntimeError(tr('auth_yggdrasil.could_not_remove_the_third_party_sign_in_token_from_the_system_credential_store', v_a=exc)) from exc


def ensure_injector(root: Path) -> Path:
    """Download the official authlib-injector artifact and verify its SHA-256."""
    raw, _ = _get(INJECTOR_API)
    try:
        artifact = json.loads(raw.decode("utf-8"))
        expected = str(artifact["checksums"]["sha256"]).lower()
        url = str(artifact["download_url"])
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(tr('auth_yggdrasil.authlib_injector_download_metadata_is_invalid')) from exc
    if urlsplit(url).scheme != "https" or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError(tr('auth_yggdrasil.authlib_injector_download_metadata_has_no_valid_https_url_or_sha_checksum'))
    path = root / "libraries" / "authlib-injector.jar"
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
        return path
    data, _ = _get(url)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise RuntimeError(tr('auth_yggdrasil.authlib_injector_sha_verification_failed_expected_got', v_a=expected, v_b=actual))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".jar.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return path


def prefetched_metadata(server: str) -> str:
    _, metadata = resolve_server(server)
    return base64.b64encode(json.dumps(metadata, separators=(",", ":")).encode("utf-8")).decode("ascii")
