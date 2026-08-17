"""Route-Test fuer GET /api/instances."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_list_instances_returns_local_without_secrets():
    resp = client.get("/api/instances")
    assert resp.status_code == 200
    data = resp.json()
    names = {item["name"] for item in data}
    assert "local" in names
    local = next(item for item in data if item["name"] == "local")
    assert local["display_name"] == "Lager 1"
    # Keine Secrets/URLs leaken:
    for item in data:
        assert set(item.keys()) == {"name", "display_name"}
