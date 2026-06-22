"""Geometry/math: turn an otg_model.json into a GeoJSON building-footprint outline.

Transform chain: Autodesk.Geolocation extension uses (WGS84 ellipsoid + ENU + refPointTransform), so
model-space AABB corners convert to the same lon/lat the Viewer would produce.

The AABB itself needs no math (it is `world bounding box`); only the lon/lat
conversion does. The `globalOffset` is NOT needed here -- raw model-space corners
map directly to lon/lat.
"""

from __future__ import annotations

import math

import numpy as np

# --- WGS84 ellipsoid (LMV Ellipsoid.js) -----------------------------------
_A = 6378137.0
_F_INV = 1.0 / 298.257223563
_B = _A * (1.0 - _F_INV)
_E2 = (2.0 - _F_INV) * _F_INV

_UNIT_TO_METER = {
    "meter": 1.0, "meters": 1.0, "m": 1.0,
    "feet and inches": 0.3048, "foot": 0.3048, "feet": 0.3048, "ft": 0.3048,
    "inch": 0.0254, "inches": 0.0254, "in": 0.0254,
    "centimeter": 0.01, "centimeters": 0.01, "cm": 0.01,
    "millimeter": 0.001, "millimeters": 0.001, "mm": 0.001,
}


def _ll_to_ecef(lon, lat, h):
    lam, phi = math.radians(lon), math.radians(lat)
    sp, cp = math.sin(phi), math.cos(phi)
    sl, cl = math.sin(lam), math.cos(lam)
    v = _A / math.sqrt(1.0 - _E2 * sp * sp)
    tmp = (v + h) * cp
    return np.array([tmp * cl, tmp * sl, ((1.0 - _E2) * v + h) * sp])


def _ecef_to_ll(x, y, z):
    ep = _E2 / (1.0 - _E2)
    p = math.hypot(x, y)
    q = math.atan2(z * _A, p * _B)
    s3, c3 = math.sin(q) ** 3, math.cos(q) ** 3
    phi = math.atan2(z + ep * _B * s3, p - _E2 * _A * c3)
    lam = math.atan2(y, x)
    v = _A / math.sqrt(1.0 - _E2 * math.sin(phi) ** 2)
    h = p / math.cos(phi) - v
    return math.degrees(lam), math.degrees(phi), h


def _model_to_ecef_matrix(position_ll84, ref_point_transform, unit_to_meter):
    """Compose model-space -> ECEF (4x4), matching LMV LocalCS (minus the LMV offset)."""
    lon, lat = position_ll84[0], position_ll84[1]
    h = position_ll84[2] if len(position_ll84) > 2 else 0.0
    world_origin = _ll_to_ecef(lon, lat, h)

    lam, phi = math.radians(lon), math.radians(lat)
    sl, cl = math.sin(lam), math.cos(lam)
    sp, cp = math.sin(phi), math.cos(phi)
    enu = np.eye(4)
    enu[:3, :3] = np.array([
        [-sl, -sp * cl, cp * cl],
        [cl, -sp * sl, cp * sl],
        [0.0, cp, sp],
    ])

    translation = np.eye(4)
    translation[:3, 3] = world_origin

    scale = np.eye(4)
    scale[0, 0] = scale[1, 1] = scale[2, 2] = unit_to_meter or 1.0

    geo_ref = np.eye(4)
    if ref_point_transform and len(ref_point_transform) == 12:
        s = ref_point_transform  # column-major 4x3: cols 0..3
        geo_ref[:3, 0] = s[0:3]
        geo_ref[:3, 1] = s[3:6]
        geo_ref[:3, 2] = s[6:9]
        geo_ref[:3, 3] = s[9:12]

    return translation @ enu @ scale @ geo_ref


def model_point_to_lonlat(matrix, x, y, z):
    ecef = matrix @ np.array([x, y, z, 1.0])
    lon, lat, _h = _ecef_to_ll(ecef[0], ecef[1], ecef[2])
    return [lon, lat]


def build_footprint_geojson(otg: dict, urn: str, name: str = ""):
    """GeoJSON FeatureCollection: AABB footprint outline + WGS84 reference point.

    Returns None when the model is not georeferenced (no positionLL84 / bbox).
    """
    geo = otg.get("georeference") or {}
    cv = otg.get("custom values") or {}
    bbox = otg.get("world bounding box") or {}
    position = geo.get("positionLL84")
    mn, mx = bbox.get("minXYZ"), bbox.get("maxXYZ")

    if not (isinstance(position, list) and len(position) >= 2 and mn and mx):
        return None

    unit = (otg.get("distance unit") or {}).get("value")
    matrix = _model_to_ecef_matrix(
        position, cv.get("refPointTransform"), _UNIT_TO_METER.get(str(unit).lower(), 1.0)
    )

    z = mn[2]  # ground level (min Z) for the footprint
    corners_model = [(mn[0], mn[1]), (mx[0], mn[1]), (mx[0], mx[1]), (mn[0], mx[1])]
    outline = [model_point_to_lonlat(matrix, cx, cy, z) for cx, cy in corners_model]
    outline.append(outline[0])  # close the loop -> polyline outline

    # Map marker at the footprint center (where the building actually is).
    # positionLL84 can be a project datum far from the geometry (e.g. Snowdon samples);
    # using it for zoom makes fitBounds span hundreds of km.
    center_lon = sum(c[0] for c in outline[:-1]) / 4
    center_lat = sum(c[1] for c in outline[:-1]) / 4

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": outline},
                "properties": {
                    "name": name or "building bounds",
                    "urn": urn,
                    "kind": "aabb_footprint_outline",
                    "distance_unit": unit,
                    "angle_to_true_north": cv.get("angleToTrueNorth"),
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [center_lon, center_lat]},
                "properties": {
                    "name": "footprint center",
                    "positionLL84": position,
                },
            },
        ],
    }
