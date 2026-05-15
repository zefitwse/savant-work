from fastapi import FastAPI

from region_guard.config import DB_PATH
from region_guard.store import AlertStore

app = FastAPI(title="RegionGuard Alerts API")
store = AlertStore(DB_PATH)


@app.get("/api/v1/alerts")
def list_alerts(camera_id: str | None = None, limit: int = 50):
    items = store.list_alerts(camera_id=camera_id, limit=limit)
    for item in items:
        item["msg_version"] = "1.0"
        item["stream_id"] = item.get("camera_id", "unknown")
        item["event_type"] = "region_alert"
    return {"items": items}
