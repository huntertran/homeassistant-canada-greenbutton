"""Upload parsed Alectra data to the visualizer's Drive appDataFolder.

The visualizer's GoogleDriveService stores its JSON in the per-user,
per-OAuth-client ``appDataFolder`` special space. Because that space is
scoped to the same client_id, this uploader **must** use the same
OAuth client the visualizer uses (see green-button-visualizer/
src/app/google-drive.config.ts).

Service accounts cannot access the user's appDataFolder — only user
credentials work. We use the OAuth refresh-token flow:
    1. ``setup_drive_oauth.py`` (run locally once) walks the consent
       flow and prints a refresh_token.
    2. CI stores client_id + client_secret + refresh_token as secrets.
    3. Each run trades the refresh_token for a short-lived access_token
       and uploads.

Merge semantics:
    Each Alectra fetch only covers ``ALECTRA_LOOKBACK_DAYS`` of data, so
    we cannot simply overwrite the Drive file or the visualizer would
    lose everything older than the window. Instead we download the
    existing JSON, union ``hourlyReadings`` (keyed by ``ts``, new wins
    on conflict) and ``billingPeriods`` (keyed by ``start``, new wins),
    re-aggregate from the merged hourly list, then upload the result.

Env vars:
    GDRIVE_CLIENT_ID
    GDRIVE_CLIENT_SECRET
    GDRIVE_REFRESH_TOKEN
    GDRIVE_FILE_NAME      optional, defaults to ``alectra-data.json``
"""
from __future__ import annotations

import json
import os

import requests

import alectra_parser

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
DEFAULT_FILE_NAME = "alectra-data.json"


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
    params = {
        "spaces": "appDataFolder",
        "q": f"name='{name}' and trashed=false",
        "fields": "files(id)",
        "pageSize": 1,
    }
    resp = requests.get(
        DRIVE_FILES,
        params=params,
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
    boundary = "gbb_boundary_xY9"
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
    """Union existing Drive payload with fresh parse; new wins on conflict.

    ``hourlyReadings`` is the source of truth — monthlyTou / dailySummaries
    / heatmapGrid are recomputed from the merged list so they stay
    consistent. If the existing file predates the hourly-readings shape,
    we cannot recover its hourly granularity and the merged aggregates
    will only reflect the fresh window for that subset.
    """
    if not existing:
        return fresh

    # Merge hourly by epoch second. Fresh wins (Alectra revises old data).
    hourly_by_ts: dict[int, dict] = {
        r["ts"]: r for r in (existing.get("hourlyReadings") or [])
    }
    for r in fresh.get("hourlyReadings", []):
        hourly_by_ts[r["ts"]] = r
    merged_hourly = sorted(hourly_by_ts.values(), key=lambda r: r["ts"])

    # Merge billing by start timestamp.
    billing_by_start: dict[str, dict] = {
        bp["start"]: bp for bp in (existing.get("billingPeriods") or [])
    }
    for bp in fresh.get("billingPeriods", []):
        billing_by_start[bp["start"]] = bp
    merged_billing = sorted(billing_by_start.values(), key=lambda b: b["start"])

    monthly_tou, daily, heatmap = alectra_parser.aggregate_hourly(merged_hourly)

    merged = {
        "billingPeriods": merged_billing,
        "monthlyTou": monthly_tou,
        "dailySummaries": daily,
        "heatmapGrid": heatmap,
        "hourlyReadings": merged_hourly,
    }
    if "savedAt" in fresh:
        merged["savedAt"] = fresh["savedAt"]
    return merged


def upload_json(payload: dict, *, file_name: str | None = None) -> dict:
    """Merge-or-create the rolling JSON file in appDataFolder.

    Returns the Drive file resource (id, name, modifiedTime).
    """
    name = file_name or os.environ.get("GDRIVE_FILE_NAME", DEFAULT_FILE_NAME)
    token = _access_token()
    existing_id = _find_file_id(token, name)

    if existing_id:
        try:
            existing_payload = _download(token, existing_id)
        except Exception:
            existing_payload = None
        merged = _merge_payload(existing_payload, payload)
        body = json.dumps(merged, separators=(",", ":")).encode("utf-8")
        return _update(token, existing_id, body)

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _create(token, name, body)
