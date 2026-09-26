from httpx import AsyncClient


async def test_liveness(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readiness_reports_dependencies(client: AsyncClient) -> None:
    resp = await client.get("/api/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"db": "ok", "redis": "ok"}
