from fastapi.testclient import TestClient

from ScrumpokerAPI.main import app


def test_public_rooms_endpoint_is_gone():
    """Regression test: GET /rooms used to list every room id, voter name
    and unrevealed vote to anyone. It's replaced by /api/admin/rooms."""
    with TestClient(app) as client:
        assert client.get("/rooms").status_code == 404
