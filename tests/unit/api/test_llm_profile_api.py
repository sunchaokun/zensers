import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_settings():
    from src.config.settings import Settings
    Settings._reset_instance()
    yield
    Settings._reset_instance()


@pytest.fixture
def client():
    from src.api.main import app
    return TestClient(app)


class TestListProfiles:
    def test_list_profiles_returns_profiles(self, client):
        resp = client.get("/api/v1/llm/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        assert "default_profile" in data
        assert "migrated" in data["profiles"]


class TestGetProfile:
    def test_get_existing_profile(self, client):
        resp = client.get("/api/v1/llm/profiles/migrated")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "migrated"

    def test_get_nonexistent_profile_404(self, client):
        resp = client.get("/api/v1/llm/profiles/ghost")
        assert resp.status_code == 404


class TestCreateProfile:
    def test_create_profile(self, client):
        resp = client.post("/api/v1/llm/profiles", json={
            "name": "strong", "model": "gpt-4o", "api_key": "sk-s", "base_url": "https://s.api/v1"
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_create_duplicate_409(self, client):
        client.post("/api/v1/llm/profiles", json={"name": "dup"})
        resp = client.post("/api/v1/llm/profiles", json={"name": "dup"})
        assert resp.status_code == 409

    def test_create_no_name_400(self, client):
        resp = client.post("/api/v1/llm/profiles", json={"model": "x"})
        assert resp.status_code == 400


class TestUpdateProfile:
    def test_update_profile(self, client):
        client.post("/api/v1/llm/profiles", json={"name": "fast", "model": "gpt-4o-mini"})
        resp = client.put("/api/v1/llm/profiles/fast", json={"model": "gpt-4o"})
        assert resp.status_code == 200
        get_resp = client.get("/api/v1/llm/profiles/fast")
        assert get_resp.json()["model"] == "gpt-4o"

    def test_update_nonexistent_404(self, client):
        resp = client.put("/api/v1/llm/profiles/ghost", json={"model": "x"})
        assert resp.status_code == 404


class TestDeleteProfile:
    def test_delete_profile(self, client):
        client.post("/api/v1/llm/profiles", json={"name": "temp"})
        resp = client.delete("/api/v1/llm/profiles/temp")
        assert resp.status_code == 200

    def test_delete_default_400(self, client):
        resp = client.delete("/api/v1/llm/profiles/migrated")
        assert resp.status_code == 400

    def test_delete_nonexistent_404(self, client):
        resp = client.delete("/api/v1/llm/profiles/ghost")
        assert resp.status_code == 404


class TestSetDefaultProfile:
    def test_set_default(self, client):
        client.post("/api/v1/llm/profiles", json={"name": "fast"})
        resp = client.post("/api/v1/llm/profiles/fast/default")
        assert resp.status_code == 200
        list_resp = client.get("/api/v1/llm/profiles")
        assert list_resp.json()["default_profile"] == "fast"

    def test_set_default_nonexistent_404(self, client):
        resp = client.post("/api/v1/llm/profiles/ghost/default")
        assert resp.status_code == 404


class TestRouting:
    def test_get_routing(self, client):
        resp = client.get("/api/v1/llm/routing")
        assert resp.status_code == 200
        data = resp.json()
        assert "fixed_agent_routing" in data
        assert "action_routing" in data
        assert "fallback_chain" in data

    def test_update_routing(self, client):
        resp = client.put("/api/v1/llm/routing", json={
            "fixed_agent_routing": {"quality_check": "strong"},
            "action_routing": {"analyze": "strong"},
        })
        assert resp.status_code == 200
        get_resp = client.get("/api/v1/llm/routing")
        assert get_resp.json()["fixed_agent_routing"]["quality_check"] == "strong"
