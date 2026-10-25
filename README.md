# easystartermc

A terminal launcher for Minecraft: Java Edition. Install game versions from Mojang metadata and launch them with offline, Microsoft, or Yggdrasil accounts.

[简体中文](README.md) | [English](README.en.md)

## Installation

Download the latest package for your operating system and processor from [GitHub Releases](https://github.com/526awd/easystartermc/releases). Prebuilt packages do not require Python. If the required Java version is missing, the launcher downloads a compatible Microsoft JDK and stores it under `runtime/microsoft-openjdk` in the Minecraft directory. This requires an internet connection and additional disk space.

| Platform | Download | Install and launch |
| --- | --- | --- |
| Windows x64 | [easystartermc-windows-x64.zip](https://github.com/526awd/easystartermc/releases/download/latest/easystartermc-windows-x64.zip) | Extract the entire ZIP folder and run `easystartermc.exe`. Keep the DLLs and other files beside it. |
| Linux x64 | [easystartermc-linux-x64.tar.gz](https://github.com/526awd/easystartermc/releases/download/latest/easystartermc-linux-x64.tar.gz) | Extract the archive, enter the `easystartermc` folder, and run `./easystartermc` in a terminal. If it is not executable, run `chmod +x easystartermc` first. This package is built on Ubuntu 22.04. |
| macOS Intel | [easystartermc-macos-x64.pkg](https://github.com/526awd/easystartermc/releases/download/latest/easystartermc-macos-x64.pkg) | Download and open the PKG, follow the installer, then run `easystartermc` in a terminal. |
| macOS Apple Silicon | [easystartermc-macos-arm64.pkg](https://github.com/526awd/easystartermc/releases/download/latest/easystartermc-macos-arm64.pkg) | Download and open the PKG, follow the installer, then run `easystartermc` in a terminal. |

Fully extract Windows ZIP and Linux archive packages; do not copy only the main executable. The macOS installer places files in `/usr/local/lib/easystartermc` and creates a launcher command in `/usr/local/bin`.

### First launch on macOS

The current macOS package is not signed or notarized. If Gatekeeper blocks it, first confirm that the package came from this project's GitHub Releases and that you trust it. Then open **System Settings → Privacy & Security** and choose **Open Anyway** in the Security section. Only do this for software you trust and obtained from a known source. See [Apple Support: Open an app safely on your Mac](https://support.apple.com/en-us/102445).

## First run

1. The launcher reads the required Java major version from the game metadata and prefers an installed exact match. If it is missing, the launcher looks for a compatible Microsoft LTS JDK and downloads one from Microsoft when needed. Downloads require an internet connection. Runtime files are stored in `runtime/microsoft-openjdk` inside the Minecraft directory. You can also set a Java executable path in **S Settings**; enter `auto` to clear the fixed path and restore automatic selection.
2. Choose **I Install**, select a version with the arrow keys, and press Enter; use PageUp/PageDown to change pages and Esc to go back. You can also search with `/keyword` or filter with `installed` and `available`. Without `prompt_toolkit`, enter a number and use `n`/`p` to change pages. The launcher downloads version metadata, the client, libraries, and game assets from the selected source and verifies downloaded files. The first installation requires internet access and enough disk space.
3. Choose **A Accounts** to add an offline profile, sign in with Microsoft, or use a Yggdrasil third-party authentication server.
4. Return to the main menu, choose **L Launch**, and select an installed version.

The launch, delete, and account-profile selectors also support arrow-key navigation. Press Esc to cancel and return.

Choose **D Delete** in the main menu to remove an installed version. Select it and enter `y` to confirm. This deletes only that version's directory; shared assets and libraries are kept.

Before launching, the launcher checks runtime libraries and retries downloads for missing or invalid files up to three times per file.

### Download sources

In **S Settings**, choose the **official Mojang source** or the **BMCLAPI mirror**. Mojang is used by default. When BMCLAPI is selected, the version list, metadata, game assets, and Minecraft Maven libraries are fetched from the mirror first. Failed requests or checksum mismatches are retried and then fall back to the official URL. Files are checked against metadata SHA-1 hashes and sizes. The install screen shows the active source. BMCLAPI is a community mirror; see the [BMCLAPI documentation](https://bmclapidoc.bangbang93.com/).

## Accounts

- **Offline profile:** Enter a player name containing 1–16 English letters, digits, or underscores. This works in single-player and on servers that allow offline players. Servers requiring premium authentication will reject offline profiles.
- **Microsoft account:** Choose **O Microsoft Sign In** in the Accounts menu. After browser authorization, the launcher retrieves the Minecraft Java profile. Login tokens are stored in the system credential store, not in `launcher.json`.
- **Yggdrasil third-party account:** Choose **Y Third-party Sign In**, then enter the authentication server API URL, account name, and password. The password is only used for the sign-in request and is not saved; tokens are stored in the system credential store. The server must support the Yggdrasil/authlib-injector specifications. The launcher checks and refreshes tokens when needed.

Third-party authentication URLs use HTTPS by default. Public HTTP URLs are rejected; HTTP is allowed only for localhost loopback addresses. Initial sign-in and token refresh require internet access. On Linux, Microsoft and third-party sign-in require an available Secret Service credential store.

## Java, game directory, and settings

The required Java version depends on the Minecraft version. The launcher reads `javaVersion.majorVersion` from version metadata, or infers the requirement from the Minecraft version for older metadata. If an exact version is not installed, it looks for a compatible Microsoft LTS release and downloads one from Microsoft's official URLs when needed. The downloaded archive is checked with SHA-256 before extraction and is kept under `runtime/microsoft-openjdk`; system Java settings are not changed. Microsoft currently provides JDK 11, 17, 21, and 25. When the exact requested major is unavailable, the launcher uses the lowest supported major that is not older than the requirement (for example, JDK 11 for Java 8 and JDK 17 for Java 16).

Default game directories are `%APPDATA%\.minecraft` on Windows, `~/Library/Application Support/minecraft` on macOS, and `$XDG_DATA_HOME/minecraft` or `~/.local/share/minecraft` on Linux. Set `MINECRAFT_DIR` to use a different directory.

`launcher.json` stores settings and account profiles, but not login tokens. Windows/Linux packages save the configuration beside the program; macOS saves it to `~/Library/Application Support/MC TUI/launcher.json`. When a profile is deleted, the launcher also attempts to remove its token from the system credential store.

Use **S Settings** to choose the interface language: Simplified Chinese, English, or the system language. The default is automatic language detection. Localization resources are in `mc_launcher/locales/`.

## Run from source

Running from source requires Python 3.10 or later. Java is downloaded automatically when the required runtime is missing.

```bash
git clone https://github.com/526awd/easystartermc.git
cd easystartermc
python -m venv .venv
```

Activate the virtual environment and install dependencies:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux or macOS
source .venv/bin/activate
```

Then run:

```bash
python -m pip install -r requirements.txt
python mc_tui.py
```

## Release workflow

Pushing a version tag beginning with `v` (for example, `v1.2`) automatically builds packages for Windows, Linux, Intel macOS, and Apple Silicon, then creates a GitHub Release with generated notes and the build artifacts. Create and push a signed tag with:

```bash
git tag -s v1.2 -m "v1.2"
git push origin v1.2
```

If a tag build fails, open **Actions → Build desktop packages → Run workflow**, enter the existing `release_tag` (for example, `v1.1.2`), and rerun the build and release.

## Project modules

- `tui.py`: terminal menus, tables, and installation progress
- `tui_selection.py`: reusable keyboard navigation and text-input fallback
- `localization.py` and `locales/`: language settings and localization. The UI uses alphabetic semantic keys, with Chinese and English text stored in `zh_CN.json` and `en_US.json`
- `accounts.py`: account profiles and launch identities
- `auth_microsoft.py`: Microsoft OAuth, PKCE, Xbox/XSTS, and Minecraft token exchange
- `auth_yggdrasil.py`: Yggdrasil sign-in, token management, and authlib-injector
- `download_sources.py`: official and BMCLAPI URL mapping
- `java_runtime.py` and `java_downloader.py`: Java discovery and Microsoft JDK installation
- `metadata.py`: Mojang version manifest
- `downloader.py`: concurrent downloads, integrity checks, and atomic writes
- `installer.py`: game clients, libraries, and assets
- `version_manager.py`: safe deletion of installed versions
- `launcher.py`: JVM arguments, native extraction, and game process launch
- `platforms.py`: operating-system rules and native library selection
- `config.py`: game directory and local settings

References: [Minecraft launcher tutorial](https://github.com/Kakumi/CustomMC-Launcher), [Microsoft authorization-code flow with PKCE](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow), [authlib-injector launcher specification](https://yushijinhun.github.io/authlib-injector/en/launcher-technical-specification.html), and [Yggdrasil server specification](https://yushijinhun.github.io/authlib-injector/en/yggdrasil-server-technical-specification.html).

## Star History

<a href="https://www.star-history.com/?repos=526awd%2Feasystartermc&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=526awd/easystartermc&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=526awd/easystartermc&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=526awd/easystartermc&type=date&legend=top-left" />
 </picture>
</a>
