"""Download the OTG/SVF2 otg_model.json for a URN (geolocation source).

Mirrors how LMV locates OTG assets:
  1. Fetch the OTG manifest from the SVF2 streaming endpoint (/modeldata/manifest/:urn).
  2. Read ``otg_manifest.paths`` (version_root) to resolve the graphics view's path.
  3. Download otg_model.json via /modeldata/file/:path (gzip-decoding on the fly).

Tokens come from a caller-supplied access token (e.g. the APS sample token endpoint).
Network calls use HTTPS only.
"""

from __future__ import annotations

import gzip
import urllib.parse
from dataclasses import dataclass, field

import requests

# The OTG/SVF2 assets live on Autodesk's derivative CDN...
CDN_BASE = "https://cdn.derivative.autodesk.com"

# API_BASE is the sample app's own token/model-list API.
APS_SAMPLE_HOST = "https://aps-extensions.autodesk.io"
DEFAULT_ORIGIN = APS_SAMPLE_HOST
API_BASE = f"{APS_SAMPLE_HOST}/api"

_TIMEOUT = 60


@dataclass
class OtgView:
    guid: str
    role: str
    name: str
    rel_path: str  # relative to version_root


@dataclass
class OtgLocation:
    urn: str
    version_root: str
    graphics_views: list = field(default_factory=list)


def _decode_maybe_gzip(content: bytes) -> bytes:
    if content[:2] == b"\x1f\x8b":
        return gzip.decompress(content)
    return content


def fetch_otg_manifest(urn: str, token: str, *, origin: str = DEFAULT_ORIGIN) -> dict:
    url = f"{CDN_BASE}/modeldata/manifest/{urn}"
    resp = requests.get(
        url,
        params={"acmsession": urn},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Origin": origin,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def parse_otg_location(manifest: dict, urn: str) -> OtgLocation:
    """Pull version_root and graphics views from the manifest."""
    folder = None
    for child in manifest.get("children", []):
        if child.get("otg_manifest"):
            folder = child
            break
    if folder is None:
        raise ValueError("No otg_manifest found in manifest (model may not be SVF2/OTG translated).")

    otg = folder["otg_manifest"]
    paths = otg.get("paths") or {}
    views = []
    for guid, view in (otg.get("views") or {}).items():
        if view.get("role") == "graphics" and view.get("mime") == "application/autodesk-otg":
            views.append(
                OtgView(guid=guid, role=view.get("role", ""), name=view.get("name", ""), rel_path=view.get("urn", ""))
            )

    return OtgLocation(
        urn=urn,
        version_root=paths.get("version_root", ""),
        graphics_views=views,
    )


def _download_fluent_path(fluent_path: str, urn: str, token: str, *, origin: str) -> bytes:
    encoded = urllib.parse.quote(fluent_path, safe="")
    url = f"{CDN_BASE}/modeldata/file/{encoded}"
    resp = requests.get(
        url,
        params={"acmsession": urn},
        headers={"Authorization": f"Bearer {token}", "Accept": "*/*", "Origin": origin},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return _decode_maybe_gzip(resp.content)


def download_otg_model(
    location: OtgLocation, view: OtgView, token: str, *, origin: str = DEFAULT_ORIGIN
) -> bytes:
    """Download (and gzip-decode) the otg_model.json bytes for a graphics view."""
    fluent_path = location.version_root + view.rel_path
    return _download_fluent_path(fluent_path, location.urn, token, origin=origin)


# --- APS sample app endpoints (token + model list) -------------------------------
def get_token(api_base: str = API_BASE) -> str:
    resp = requests.get(f"{api_base}/auth/token", timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["access_token"]


def list_models(bucket: str = "samplemodels", api_base: str = API_BASE) -> list:
    """Return [{name, urn}] for a bucket: maps {text -> name, id -> urn}."""
    resp = requests.get(f"{api_base}/models/buckets", params={"id": bucket}, timeout=_TIMEOUT)
    resp.raise_for_status()
    return [{"name": m.get("text"), "urn": m.get("id")} for m in resp.json()]
