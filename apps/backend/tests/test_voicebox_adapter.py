import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import voicebox
from app.core.auth import get_current_admin_user, get_current_user_id
from app.core.config import settings
from app.core.voice import wake_service


def _override_operator(app: FastAPI):
    app.dependency_overrides[get_current_user_id] = lambda: "admin_richard"


def test_voicebox_endpoints_require_authentication(client: TestClient):
    response = client.get("/api/voicebox/status")
    assert response.status_code == 401


def test_voicebox_disabled_status_is_explicit(client: TestClient, monkeypatch):
    _override_operator(client.app)
    monkeypatch.setattr(settings, "VOICEBOX_BASE_URL", None)
    monkeypatch.setattr(settings, "VOICEBOX_PROFILE_ID", None)

    response = client.get("/api/voicebox/status")

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "connected": False,
        "profile_configured": False,
        "wake_word": "JARV, talk to me.",
    }


def test_voicebox_transcription_and_speech_use_authenticated_adapter(
    client: TestClient, monkeypatch,
):
    _override_operator(client.app)
    monkeypatch.setattr(settings, "VOICEBOX_BASE_URL", "http://voicebox.test")
    monkeypatch.setattr(settings, "VOICEBOX_PROFILE_ID", "profile-id")
    real_client = httpx.AsyncClient
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/transcribe":
            assert b"name=\"file\"" in await request.aread()
            return httpx.Response(200, json={"text": "Check the system status", "duration": 1.2})
        assert request.url.path == "/generate"
        assert request.headers["content-type"].startswith("application/json")
        assert b'"profile_id": "profile-id"' in await request.aread()
        return httpx.Response(200, json={"id": "generation-id", "status": "generating"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        voicebox.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    transcript = client.post(
        "/api/voicebox/transcribe",
        files={"file": ("command.wav", b"wave-data", "audio/wav")},
        data={"language": "en"},
    )
    speech = client.post(
        "/api/voicebox/speak",
        json={"text": "System status is healthy.", "language": "en"},
    )

    assert transcript.status_code == 200
    assert transcript.json()["text"] == "Check the system status"
    assert speech.status_code == 200
    assert speech.json() == {"id": "generation-id", "status": "generating"}
    assert len(requests) == 2


def test_voicebox_profile_required_before_speech(client: TestClient, monkeypatch):
    _override_operator(client.app)
    monkeypatch.setattr(settings, "VOICEBOX_BASE_URL", "http://voicebox.test")
    monkeypatch.setattr(settings, "VOICEBOX_PROFILE_ID", None)

    response = client.post("/api/voicebox/speak", json={"text": "Hello"})

    assert response.status_code == 503
    assert "speech profile" in response.json()["detail"]


def test_wake_ticket_requires_an_installed_local_model(client: TestClient, monkeypatch):
    _override_operator(client.app)
    monkeypatch.setattr(wake_service, "model_is_ready", lambda: False)

    response = client.post("/api/voicebox/wake/ticket", headers={"Origin": "http://localhost:3002"})

    assert response.status_code == 503
    assert "model" in response.json()["detail"]


def test_admin_updates_installed_wake_phrase_and_validates_runtime(client: TestClient, monkeypatch, tmp_path):
    client.app.dependency_overrides[get_current_admin_user] = lambda: "admin_richard"
    _override_operator(client.app)
    keyword_file = tmp_path / wake_service.MODEL_FILES["keywords"]
    keyword_file.write_text("old keyword\n", encoding="utf-8")
    monkeypatch.setattr(wake_service, "model_is_ready", lambda: True)
    monkeypatch.setattr(wake_service, "model_directory", lambda: tmp_path)
    monkeypatch.setattr(wake_service, "_active_streams", 0)
    monkeypatch.setattr(wake_service, "_spotter", object())
    monkeypatch.setattr(
        wake_service,
        "_write_keyword_file",
        lambda directory: (directory / wake_service.MODEL_FILES["keywords"]).write_text("JARV TALK TO ME\n", encoding="utf-8"),
    )
    monkeypatch.setattr(wake_service, "_keyword_spotter", lambda: object())

    response = client.post("/api/voicebox/wake/model/install")

    assert response.status_code == 200, response.text
    assert response.json()["phrase"] == "JARV, talk to me."
    assert keyword_file.read_text(encoding="utf-8") == "JARV TALK TO ME\n"


def test_wake_status_reports_whether_installed_phrase_is_current(monkeypatch, tmp_path):
    import sentencepiece

    class FakeTokenizer:
        def __init__(self, model_file: str):
            assert model_file.endswith(wake_service.MODEL_FILES["bpe"])

        def encode(self, phrase: str, out_type: type):
            assert phrase == wake_service.WAKE_PHRASE
            assert out_type is str
            return ["JARV", "TALK", "TO", "ME"]

    monkeypatch.setattr(sentencepiece, "SentencePieceProcessor", FakeTokenizer)
    monkeypatch.setattr(wake_service, "model_directory", lambda: tmp_path)
    monkeypatch.setattr(wake_service, "model_is_ready", lambda: True)
    for filename in wake_service.MODEL_FILES.values():
        (tmp_path / filename).touch()

    keyword_file = tmp_path / wake_service.MODEL_FILES["keywords"]
    keyword_file.write_text("JARV TALK TO ME @JARV_TALK_TO_ME\n", encoding="utf-8")
    assert wake_service.install_status()["phrase_current"] is True

    keyword_file.write_text("OLD KEYWORD\n", encoding="utf-8")
    assert wake_service.install_status()["phrase_current"] is False


def test_admin_cannot_update_wake_phrase_while_hands_free_stream_active(client: TestClient, monkeypatch, tmp_path):
    client.app.dependency_overrides[get_current_admin_user] = lambda: "admin_richard"
    _override_operator(client.app)
    keyword_file = tmp_path / wake_service.MODEL_FILES["keywords"]
    keyword_file.write_text("existing keyword\n", encoding="utf-8")
    monkeypatch.setattr(wake_service, "model_is_ready", lambda: True)
    monkeypatch.setattr(wake_service, "model_directory", lambda: tmp_path)
    monkeypatch.setattr(wake_service, "_active_streams", 1)

    response = client.post("/api/voicebox/wake/model/install")

    assert response.status_code == 409
    assert keyword_file.read_text(encoding="utf-8") == "existing keyword\n"


def test_wake_websocket_uses_single_use_origin_bound_ticket(client: TestClient, monkeypatch):
    _override_operator(client.app)
    monkeypatch.setattr(wake_service, "model_is_ready", lambda: True)
    monkeypatch.setattr(wake_service, "create_stream", lambda: object())
    monkeypatch.setattr(wake_service, "process_audio_frame", lambda _stream, _frame: "JARV_TALK_TO_ME")
    monkeypatch.setattr(wake_service, "free_stream", lambda _stream: None)
    origin = "http://localhost:3002"

    ticket_response = client.post("/api/voicebox/wake/ticket", headers={"Origin": origin})
    assert ticket_response.status_code == 200, ticket_response.text
    ticket = ticket_response.json()["ticket"]

    with client.websocket_connect(
        "/api/voicebox/wake",
        subprotocols=["jarv-wake", f"ticket.{ticket}"],
        headers={"Origin": origin},
    ) as websocket:
        assert websocket.receive_json()["type"] == "ready"
        websocket.send_bytes(b"\0\0\0\0")
        assert websocket.receive_json() == {"type": "wake", "keyword": "JARV_TALK_TO_ME"}


def test_admin_provisions_persistent_voicebox_profile_for_speech(client: TestClient, monkeypatch):
    client.app.dependency_overrides[get_current_admin_user] = lambda: "admin_richard"
    _override_operator(client.app)
    monkeypatch.setattr(settings, "VOICEBOX_BASE_URL", "http://voicebox.test")
    monkeypatch.setattr(settings, "VOICEBOX_PROFILE_ID", None)
    real_client = httpx.AsyncClient
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/profiles" and request.method == "GET":
            return httpx.Response(200, json=[])
        if request.url.path == "/profiles":
            profile = await request.aread()
            assert b"bm_george" in profile
            assert b"kokoro" in profile
            return httpx.Response(200, json={"id": "profile-jarv"})
        assert request.url.path == "/generate"
        assert b"profile-jarv" in await request.aread()
        return httpx.Response(200, json={"id": "generation-id", "status": "generating"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        voicebox.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    provisioned = client.post("/api/voicebox/profile/provision")
    spoken = client.post("/api/voicebox/speak", json={"text": "Hello from JARV"})

    assert provisioned.status_code == 200, provisioned.text
    assert provisioned.json()["profile_id"] == "profile-jarv"
    assert provisioned.json()["voice"] == "Kokoro British male preset (George)"
    assert spoken.status_code == 200, spoken.text
    assert spoken.json()["id"] == "generation-id"
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/profiles"),
        ("POST", "/profiles"),
        ("POST", "/generate"),
    ]
