"""Shared local configuration for Alibaba Cloud lifecycle tools."""

from __future__ import annotations

import json
import os
from pathlib import Path


ALIYUN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ALIYUN_DIR.parent


def load_config() -> dict:
    path = ALIYUN_DIR / "config.json"
    if not path.is_file():
        raise RuntimeError(
            f"Missing {path}. Copy config.example.json and fill resource IDs first."
        )
    config = json.loads(path.read_text(encoding="utf-8"))
    access_key_id = os.environ.get(
        "ALIBABA_CLOUD_ACCESS_KEY_ID", config.get("access_key_id", "")
    )
    access_key_secret = os.environ.get(
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET", config.get("access_key_secret", "")
    )
    placeholders = {"", "YOUR_ACCESS_KEY_ID", "YOUR_ACCESS_KEY_SECRET"}
    if access_key_id in placeholders or access_key_secret in placeholders:
        raise RuntimeError(
            "Set ALIBABA_CLOUD_ACCESS_KEY_ID and ALIBABA_CLOUD_ACCESS_KEY_SECRET "
            "in this shell, or place them in ignored aliyun/config.json."
        )
    config["access_key_id"] = access_key_id
    config["access_key_secret"] = access_key_secret
    return config


def ssh_key(config: dict | None = None) -> Path:
    # A reviewer coordinator receives only an SSH key, not cloud API
    # credentials. Resolve the explicit key override before loading config so
    # developer-side SSH-only workflows remain usable.
    raw = os.environ.get("RAFTEL_SSH_KEY")
    if raw is None:
        config = config or load_config()
        raw = config.get("ssh_private_key", "TShard")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def read_inventory() -> list[dict]:
    path = ALIYUN_DIR / "hosts.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Invalid host inventory: {path}")
    return data


def ssh_address(private_ip: str) -> str:
    if os.environ.get("RAFTEL_USE_PRIVATE_SSH") == "1":
        return private_ip
    for host in read_inventory():
        if host.get("private_ip") == private_ip:
            return host.get("public_ip") or private_ip
    return private_ip
