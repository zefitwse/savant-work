# task6/geometry.py

def bbox_to_foot_point(event: dict) -> tuple[float, float]:
    """
    支持你们仓库可能出现的两种bbox格式：
    1. bbox: {"left": 1, "top": 2, "width": 3, "height": 4}
    2. bbox: [x, y, w, h]
    """
    bbox = event.get("bbox")

    if isinstance(bbox, dict):
        x = float(bbox.get("left", bbox.get("x", 0)))
        y = float(bbox.get("top", bbox.get("y", 0)))
        w = float(bbox.get("width", bbox.get("w", 0)))
        h = float(bbox.get("height", bbox.get("h", 0)))
    elif isinstance(bbox, list) and len(bbox) >= 4:
        x, y, w, h = map(float, bbox[:4])
    else:
        x = y = w = h = 0.0

    return x + w / 2, y + h


def point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    x, y = point
    inside = False
    n = len(polygon)

    if n < 3:
        return False

    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        intersect = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        )
        if intersect:
            inside = not inside

        j = i

    return inside


def find_rois(camera_id: str, point: tuple[float, float], roi_config: dict) -> list[dict]:
    matched = []
    for roi in roi_config.get(camera_id, []):
        if point_in_polygon(point, roi.get("points", [])):
            matched.append(roi)
    return matched