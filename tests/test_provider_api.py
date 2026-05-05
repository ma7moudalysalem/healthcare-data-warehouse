"""Tests for src.generators.provider_api."""
from src.generators import provider_api as P


def setup_module():
    """One bootstrap, many tests."""
    P.PROVIDER_REGISTRY.clear()
    P._bootstrap_registry(n=50)


def test_health_endpoint():
    client = P.app.test_client()
    rv = client.get("/health")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["status"] == "ok"
    assert body["providers"] == 50


def test_get_provider_known_npi():
    client = P.app.test_client()
    npi = next(iter(P.PROVIDER_REGISTRY))
    rv = client.get(f"/api/providers/{npi}")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["npi"] == npi
    assert "specialty" in body


def test_get_provider_unknown_npi_404():
    client = P.app.test_client()
    rv = client.get("/api/providers/0000000000")
    assert rv.status_code == 404


def test_list_providers_pagination():
    client = P.app.test_client()
    rv = client.get("/api/providers?page=1&page_size=10")
    body = rv.get_json()
    assert rv.status_code == 200
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert len(body["items"]) == 10
    assert body["total"] == 50
