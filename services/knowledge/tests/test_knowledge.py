"""
JAI's knowledge service: the real embedded FalkorDB Lite graph starts and builds Graphiti's indexes, searches work
(with the embedder replaced, since there is no network here), additions are queued in order and one failure never
stops the queue, and nothing answers without JAI's token.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

import server

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def configured(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "TOKEN", "test-token")
    # The gateway token the service is given when installed; nothing here reaches the gateway.
    monkeypatch.setattr(server, "GATEWAY_TOKEN", "test-gateway-token")
    monkeypatch.setattr(server, "GRAPH_FILE", str(tmp_path / "graph" / "jai.db"))
    monkeypatch.setattr(server, "HISTORY_FILE", str(tmp_path / "mem0" / "history.db"))
    monkeypatch.setattr(server, "STORE", server.Store())


def test_nothing_answers_without_jais_token():
    with TestClient(server.app) as client:
        assert client.post("/graph/search", json={"query": "Plexecute"}).status_code == 401
        assert client.post("/memories", headers={"Authorization": "Bearer wrong"},
                           json={"text": "I prefer British English"}).status_code == 401
        assert client.get("/health").json()["ok"] is True


def test_the_embedded_graph_starts_and_answers_a_search():
    class FlatEmbedder:
        async def create(self, input_data):
            return [0.01] * 1536

        async def create_batch(self, input_data_list):
            return [[0.01] * 1536 for _ in input_data_list]

    with TestClient(server.app) as client:
        started = client.post("/start", headers=AUTH).json()
        assert started["graph"] == "ready", started
        assert started["memory"] != "ready"  # no PostgreSQL in this test: it says why, the graph still works
        server.STORE.graph.embedder = FlatEmbedder()
        server.STORE.graph.clients.embedder = server.STORE.graph.embedder
        found = client.post("/graph/search", headers=AUTH,
                            json={"query": "What does Plexecute use for payments?", "groups": ["ws-plexecute"]})
        assert found.status_code == 200 and found.json() == {"facts": []}, found.text
        assert "ws-plexecute" in server.STORE.prepared  # its graph's search indexes were built on first use
        again = client.post("/graph/search", headers=AUTH, json={"query": "Stripe", "groups": ["ws-plexecute"]})
        assert again.json() == {"facts": []}


def test_additions_are_queued_in_order_and_a_failure_does_not_stop_the_queue():
    done = []

    async def run():
        store = server.STORE

        async def ok(n):
            done.append(n)

        async def bad():
            raise RuntimeError("the gateway said no")

        store.enqueue("first", lambda: ok(1))
        store.enqueue("broken", bad)
        store.enqueue("third", lambda: ok(3))
        await asyncio.wait_for(store.queue.join(), timeout=5)
        return store

    store = asyncio.run(run())
    assert done == [1, 3] and store.done == 2 and store.failed == 1 and "the gateway said no" in store.last_error


def test_mem0_is_set_up_on_jais_postgres_through_jais_gateway(monkeypatch):
    monkeypatch.setattr(server, "GATEWAY_TOKEN", "gateway-token")
    assert asyncio.run(_without_gateway(monkeypatch)) is True
    config = server.STORE.mem0_config()
    assert config["vector_store"]["provider"] == "pgvector"
    assert config["llm"]["config"]["openai_base_url"].endswith("/api/gateway/v1")
    assert config["llm"]["config"]["api_key"] == "gateway-token" and config["embedder"]["config"]["api_key"] == "gateway-token"
    assert server._group("ws 1/../x") == "ws_1____x"


async def _without_gateway(monkeypatch):
    monkeypatch.setattr(server, "GATEWAY_TOKEN", "")
    try:
        await server.Store().graphiti()
    except RuntimeError as exc:
        return "JAI_GATEWAY_TOKEN" in str(exc)
    finally:
        monkeypatch.setattr(server, "GATEWAY_TOKEN", "gateway-token")
    return False
