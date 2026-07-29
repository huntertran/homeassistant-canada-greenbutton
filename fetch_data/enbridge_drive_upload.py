"""Upload parsed Enbridge Gas billing data to Google Drive appDataFolder.

Uses the same OAuth credentials as the Alectra uploader — same per-user
appDataFolder, different file (default: enbridge-data.json).

Merge semantics: billing periods keyed by start timestamp; new wins.

Env vars:
    GDRIVE_CLIENT_ID
    GDRIVE_CLIENT_SECRET
    GDRIVE_REFRESH_TOKEN
    ENBRIDGE_GDRIVE_FILE_NAME   optional, defaults to ``enbridge-data.json``
"""
from __future__ import annotations

import json
import os

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
DEFAULT_FILE_NAME = "enbridge-data.json"


def _access_token() -> str:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": os.environ["GDRIVE_CLIENT_ID"],
            "client_secret": os.environ["GDRIVE_CLIENT_SECRET"],
            "refresh_token": os.environ["GDRIVE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _find_file_id(token: str, name: str) -> str | None:
    resp = requests.get(
        DRIVE_FILES,
        params={
            "spaces": "appDataFolder",
            "q": f"name='{name}' and trashed=false",
            "fields": "files(id)",
            "pageSize": 1,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    files = resp.json().get("files", [])
    return files[0]["id"] if files else None


def _download(token: str, file_id: str) -> dict:
    resp = requests.get(
        f"{DRIVE_FILES}/{file_id}",
        params={"alt": "media"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def _update(token: str, file_id: str, body: bytes) -> dict:
    resp = requests.patch(
        f"{DRIVE_UPLOAD}/{file_id}",
        params={"uploadType": "media", "fields": "id,name,modifiedTime"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data=body,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def _create(token: str, name: str, body: bytes) -> dict:
    metadata = json.dumps({"name": name, "parents": ["appDataFolder"]}).encode()
    boundary = "egb_boundary_xY9"
    multipart = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
    ).encode() + metadata + (
        f"\r\n--{boundary}\r\n"
        "Content-Type: application/json\r\n\r\n"
    ).encode() + body + f"\r\n--{boundary}--".encode()
    resp = requests.post(
        DRIVE_UPLOAD,
        params={"uploadType": "multipart", "fields": "id,name,modifiedTime"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        data=multipart,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def _merge_payload(existing: dict | None, fresh: dict) -> dict:
    if not existing:
        return fresh
    by_start: dict[str, dict] = {
        p["start"]: p for p in (existing.get("billingPeriods") or [])
    }
    for p in fresh.get("billingPeriods", []):
        by_start[p["start"]] = p
    merged = dict(fresh)
    merged["billingPeriods"] = sorted(by_start.values(), key=lambda p: p["start"])
    return merged


def upload_json(payload: dict, *, file_name: str | None = None) -> dict:
    """Merge-or-create the rolling JSON file in appDataFolder."""
    name = file_name or os.environ.get("ENBRIDGE_GDRIVE_FILE_NAME", DEFAULT_FILE_NAME)
    token = _access_token()
    existing_id = _find_file_id(token, name)
    if existing_id:
        try:
            existing = _download(token, existing_id)
        except Exception:
            existing = None
        merged = _merge_payload(existing, payload)
        body = json.dumps(merged, separators=(",", ":")).encode("utf-8")
        return _update(token, existing_id, body)
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _create(token, name, body)
