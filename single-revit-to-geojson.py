"""Single RVT -> GeoJSON building footprint.

Fetches the OTG manifest + otg_model.json for one model (download.py, REST), prints
the geolocation fields, and writes a GeoJSON footprint outline (footprint.py, math).

Defaults to the basic RAC sample (`rac-basic-sampleproject.rvt`) from the APS sample
bucket. Override with --model-name / --urn for any other model.

Usage:
  python single-revit-to-geojson.py
  python single-revit-to-geojson.py --model-name rac-advanced-sampleproject.rvt
  python single-revit-to-geojson.py --urn <base64-urn> --out building_bounds.geojson
"""

import argparse
import json

import download as dl
import footprint as fp

# Default: rac-basic-sampleproject.rvt.
DEFAULT_URN = "dXJuOmFkc2sub2JqZWN0czpvcy5vYmplY3Q6c2FtcGxlbW9kZWxzL3JhYy1iYXNpYy1zYW1wbGVwcm9qZWN0LnJ2dA=="


def run(urn: str, name: str, token: str, out_path: str) -> None:
    manifest = dl.fetch_otg_manifest(urn, token, origin=dl.DEFAULT_ORIGIN)
    loc = dl.parse_otg_location(manifest, urn)
    if not loc.graphics_views:
        print("No OTG graphics views for this URN (model may be SVF1-only).")
        return

    view = loc.graphics_views[0]
    otg = json.loads(dl.download_otg_model(loc, view, token, origin=dl.DEFAULT_ORIGIN))

    geo = otg.get("georeference") or {}
    cv = otg.get("custom values") or {}
    bbox = otg.get("world bounding box") or {}
    unit = (otg.get("distance unit") or {}).get("value")
    mn, mx = bbox.get("minXYZ"), bbox.get("maxXYZ")
    center = [(a + b) / 2 for a, b in zip(mn, mx)] if mn and mx else None

    print(f"\nModel: {name or urn[:48] + '...'}")
    print(f"positionLL84      : {geo.get('positionLL84')}   (lon, lat, height)")
    print(f"refPointLMV       : {geo.get('refPointLMV')}")
    print(f"angleToTrueNorth  : {cv.get('angleToTrueNorth')}")
    print(f"distance unit     : {unit}")
    print(f"world AABB min    : {mn}")
    print(f"world AABB max    : {mx}")
    print(f"AABB center       : {center}   (== globalOffset, just (min+max)/2)")

    fc = fp.build_footprint_geojson(otg, urn, name)
    if fc is None:
        print("\nNo geolocation on this model -> skipping GeoJSON export.")
        return
    with open(out_path, "w") as fh:
        json.dump(fc, fh, indent=2)
    print(f"\nWrote footprint outline -> {out_path}")
    for lon, lat in fc["features"][0]["geometry"]["coordinates"]:
        print(f"    {lon:.7f}, {lat:.7f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert a single RVT model into a GeoJSON footprint.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--urn", help="Base64 URN (default: rac-advanced sample).")
    g.add_argument("--model-name", help="Resolve URN by name from the sample bucket.")
    ap.add_argument("--bucket", default="samplemodels", help="Bucket id for --model-name lookups.")
    ap.add_argument("--out", default="building_bounds.geojson", help="Output GeoJSON path.")
    ap.add_argument("--token", help="APS token (else fetched from the aps-extensions endpoint).")
    args = ap.parse_args()

    token = args.token or dl.get_token()

    urn = args.urn or DEFAULT_URN
    name = ""
    if args.model_name:
        match = next((m for m in dl.list_models(args.bucket) if m["name"] == args.model_name), None)
        if not match:
            ap.error(f"model '{args.model_name}' not found in bucket '{args.bucket}'")
        urn, name = match["urn"], match["name"]

    run(urn, name, token, args.out)


if __name__ == "__main__":
    main()
