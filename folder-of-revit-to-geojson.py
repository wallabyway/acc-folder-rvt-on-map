"""Bucket of RVT models -> one combined GeoJSON of building footprints.

Lists every model in an APS sample bucket, and for each RVT it:
  1. fetches the OTG manifest + otg_model.json (download.py, REST),
  2. builds the AABB footprint outline + reference point in lon/lat (footprint.py, math),
  3. merges all features into a single GeoJSON FeatureCollection.

Endpoints (https://github.com/wallabyway/viewer-plus-maplibre):
  token  : GET https://aps-extensions.autodesk.io/api/auth/token
  models : GET https://aps-extensions.autodesk.io/api/models/buckets?id=<bucket>
           -> [{ text: <name>, id: <urn> }, ...]

Usage:
  python folder-of-revit-to-geojson.py
  python folder-of-revit-to-geojson.py --bucket samplemodels --out bucket_bounds.geojson
  python folder-of-revit-to-geojson.py --all          # include non-RVT models too
"""

import argparse
import json

import download as dl
import footprint as fp


def model_features(urn: str, name: str, token: str) -> list[dict]:
    """Return GeoJSON features (footprint outline + reference point) for one model.

    Returns [] when the model is not georeferenced or has no OTG graphics view.
    """
    manifest = dl.fetch_otg_manifest(urn, token, origin=dl.DEFAULT_ORIGIN)
    loc = dl.parse_otg_location(manifest, urn)
    if not loc.graphics_views:
        return []

    view = loc.graphics_views[0]
    otg = json.loads(dl.download_otg_model(loc, view, token, origin=dl.DEFAULT_ORIGIN))

    fc = fp.build_footprint_geojson(otg, urn, name)
    if fc is None:
        return []

    # Tag every feature with the model name so they're distinguishable on a map.
    for feature in fc["features"]:
        feature["properties"]["model"] = name
    return fc["features"]


def build_bucket_geojson(bucket: str, token: str, *, rvt_only: bool = True) -> tuple[dict, list]:
    models = dl.list_models(bucket)
    if rvt_only:
        models = [m for m in models if (m["name"] or "").lower().endswith(".rvt")]

    features: list[dict] = []
    summary: list[dict] = []
    for m in models:
        name, urn = m["name"], m["urn"]
        try:
            feats = model_features(urn, name, token)
        except Exception as exc:  # noqa: BLE001 - keep batch resilient, report per model
            print(f"  ! {name}: {type(exc).__name__}: {exc}")
            summary.append({"name": name, "geolocated": False, "error": str(exc)})
            continue

        geolocated = bool(feats)
        if geolocated:
            features.extend(feats)
            # The first feature is the outline; pull a representative coord for the log.
            ref = next((f for f in feats if f["geometry"]["type"] == "Point"), None)
            coord = ref["geometry"]["coordinates"] if ref else None
            print(f"  + {name}: {coord}")
        else:
            print(f"  - {name}: no geolocation")
        summary.append({"name": name, "geolocated": geolocated})

    return {"type": "FeatureCollection", "features": features}, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert a bucket of RVT models into one GeoJSON of footprints.")
    ap.add_argument("--bucket", default="samplemodels", help="APS sample bucket id (default: samplemodels).")
    ap.add_argument("--out", default="bucket_bounds.geojson", help="Output GeoJSON path.")
    ap.add_argument("--all", action="store_true", help="Include non-RVT models too.")
    ap.add_argument("--token", help="APS token (else fetched from the aps-extensions endpoint).")
    args = ap.parse_args()

    token = args.token or dl.get_token()
    print(f"Bucket '{args.bucket}':")
    fc, summary = build_bucket_geojson(args.bucket, token, rvt_only=not args.all)

    with open(args.out, "w") as fh:
        json.dump(fc, fh, indent=2)

    geolocated = sum(1 for s in summary if s.get("geolocated"))
    print(f"\n{geolocated}/{len(summary)} model(s) geolocated -> {len(fc['features'])} feature(s)")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
