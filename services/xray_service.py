from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from node_validator import resolve_xray_path


XRAY_RELEASES_API = "https://api.github.com/repos/XTLS/Xray-core/releases"


def xray_root(root: Path) -> Path:
    return root / "tools" / "xray"


def xray_default_path(root: Path) -> Path:
    return xray_root(root) / "xray"


def xray_version(path: Path) -> str:
    try:
        result = subprocess.run(
            [str(path), "version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    output = (result.stdout or result.stderr or "").strip()
    return output.splitlines()[0] if output else ""


def runtime_status(root: Path) -> dict:
    default = xray_default_path(root)
    try:
        resolved = resolve_xray_path(default)
        available = True
    except FileNotFoundError:
        resolved = default
        available = False
    geoip = resolved.parent / "geoip.dat"
    geosite = resolved.parent / "geosite.dat"
    return {
        "path": str(resolved),
        "available": available,
        "version": xray_version(resolved) if available else "",
        "geoip": str(geoip),
        "geoip_available": geoip.exists(),
        "geosite": str(geosite),
        "geosite_available": geosite.exists(),
        "platform": platform.system().lower(),
        "machine": platform.machine().lower(),
    }


def _platform_alias(system: str) -> str:
    value = (system or "").lower()
    if value.startswith("win"):
        return "windows"
    if value.startswith("linux"):
        return "linux"
    if value.startswith("darwin") or value.startswith("mac"):
        return "macos"
    return value


def _arch_alias(machine: str) -> str:
    value = (machine or "").lower()
    if value in ("amd64", "x86_64", "x64"):
        return "64"
    if value in ("arm64", "aarch64"):
        return "arm64-v8a"
    return value


def release_asset_matches(asset_name: str, system: str, arch: str) -> bool:
    name = asset_name.lower()
    if not name.endswith(".zip"):
        return False
    platform_name = _platform_alias(system)
    arch_name = _arch_alias(arch)
    return "xray-" in name and platform_name in name and arch_name in name


def parse_releases(payload: List[dict], system: str = "", arch: str = "", limit: int = 30) -> List[dict]:
    releases = []
    for item in payload[: max(1, min(int(limit or 30), 100))]:
        assets = []
        for asset in item.get("assets") or []:
            name = str(asset.get("name") or "")
            download_url = str(asset.get("browser_download_url") or "")
            if not name or not download_url:
                continue
            assets.append({
                "name": name,
                "download_url": download_url,
                "size": int(asset.get("size") or 0),
                "matched": release_asset_matches(name, system, arch) if system and arch else False,
            })
        releases.append({
            "version": str(item.get("tag_name") or ""),
            "name": str(item.get("name") or item.get("tag_name") or ""),
            "published_at": str(item.get("published_at") or ""),
            "prerelease": bool(item.get("prerelease")),
            "assets": assets,
        })
    return releases


def fetch_releases(system: str = "", arch: str = "", limit: int = 30) -> List[dict]:
    request = urllib.request.Request(
        XRAY_RELEASES_API + "?per_page=" + str(max(1, min(int(limit or 30), 100))),
        headers={"Accept": "application/vnd.github+json", "User-Agent": "HuageNodeConsole/1.0"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_releases(payload, system, arch, limit)


def local_versions(root: Path) -> List[dict]:
    releases_dir = xray_root(root) / "releases"
    rows = []
    if not releases_dir.exists():
        return rows
    for directory in sorted((item for item in releases_dir.iterdir() if item.is_dir()), reverse=True):
        executable = directory / ("xray.exe" if os.name == "nt" else "xray")
        if not executable.exists():
            alt = directory / ("xray" if os.name == "nt" else "xray.exe")
            executable = alt if alt.exists() else executable
        rows.append({
            "version": directory.name,
            "path": str(directory),
            "executable": str(executable),
            "available": executable.exists(),
            "active": executable.exists() and str(executable.resolve()) == str(resolve_active_path(root).resolve()) if executable.exists() else False,
        })
    return rows


def resolve_active_path(root: Path) -> Path:
    try:
        return resolve_xray_path(xray_default_path(root))
    except FileNotFoundError:
        return xray_default_path(root)


def safe_version_name(version: str) -> str:
    cleaned = "".join(char for char in str(version or "").strip() if char.isalnum() or char in ("-", "_", "."))
    if not cleaned:
        raise ValueError("Xray 版本号不能为空")
    return cleaned[:80]


def download_release(root: Path, version: str, asset_url: str, asset_name: str) -> dict:
    if not asset_url.startswith("https://github.com/") and not asset_url.startswith("https://objects.githubusercontent.com/"):
        raise ValueError("只能下载 Xray 官方 GitHub 资源")
    version_name = safe_version_name(version)
    target_dir = xray_root(root) / "releases" / version_name
    target_dir.mkdir(parents=True, exist_ok=True)
    archive_path = target_dir / (Path(asset_name).name or "xray.zip")
    urllib.request.urlretrieve(asset_url, archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(target_dir)
    executable = next((item for item in target_dir.rglob("xray.exe") if item.is_file()), None)
    if executable is None:
        executable = next((item for item in target_dir.rglob("xray") if item.is_file()), None)
    if executable is None:
        raise ValueError("下载包中未找到 Xray 可执行文件")
    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {
        "version": version_name,
        "path": str(target_dir),
        "archive": str(archive_path),
        "executable": str(executable),
        "version_output": xray_version(executable),
    }


def activate_version(root: Path, version: str) -> dict:
    version_name = safe_version_name(version)
    target_dir = xray_root(root) / "releases" / version_name
    executable = next((item for item in target_dir.rglob("xray.exe") if item.is_file()), None)
    if executable is None:
        executable = next((item for item in target_dir.rglob("xray") if item.is_file()), None)
    if executable is None:
        raise ValueError("本地版本不存在或未找到 Xray 可执行文件")
    active_dir = xray_root(root)
    active_dir.mkdir(parents=True, exist_ok=True)
    active = active_dir / ("xray.exe" if os.name == "nt" else "xray")
    shutil.copy2(executable, active)
    if os.name != "nt":
        active.chmod(active.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    version_output = xray_version(active)
    if not version_output:
        raise ValueError("切换后 Xray 无法执行 version 检查")
    return {"version": version_name, "active": str(active), "version_output": version_output}
