"""Access-control flow: request code -> owner's email -> verify -> session.

The emailer is monkeypatched; everything else (challenge storage, hashing,
attempt limits, session tokens, gating) runs for real against DiskStore.
"""

import re

import pytest
from fastapi.testclient import TestClient

from copcat.webapp import app, _session_ok

client = TestClient(app)


@pytest.fixture()
def code_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("COPCAT_RESULTS_DIR", str(tmp_path))
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("COPCAT_NOTIFY_EMAIL", "owner@example.com")
    monkeypatch.setenv("COPCAT_AUTH_SECRET", "unit-test-secret")
    monkeypatch.delenv("COPCAT_ACCESS_TOKEN", raising=False)
    sent = []
    monkeypatch.setattr("copcat.webapp._send_access_code",
                        lambda to, code, note: sent.append((to, code, note)))
    return sent


def test_mode_endpoints(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("COPCAT_NOTIFY_EMAIL", raising=False)
    monkeypatch.delenv("COPCAT_ACCESS_TOKEN", raising=False)
    assert client.get("/api/auth/mode").json() == {"mode": "open"}
    monkeypatch.setenv("COPCAT_ACCESS_TOKEN", "k1")
    assert client.get("/api/auth/mode").json() == {"mode": "key"}
    monkeypatch.setenv("RESEND_API_KEY", "r")
    monkeypatch.setenv("COPCAT_NOTIFY_EMAIL", "o@x.com")
    assert client.get("/api/auth/mode").json() == {"mode": "code"}


def test_request_verify_session_flow(code_mode):
    sent = code_mode
    assert client.get("/api/auth/mode").json() == {"mode": "code"}

    # gated endpoint refuses before auth
    assert client.get("/api/jobs").status_code == 401

    # request a code: it is emailed, never returned in the response
    r = client.post("/api/auth/request", data={"note": "TA, section B"})
    assert r.status_code == 200 and r.json() == {"sent": True}
    assert len(sent) == 1
    to, code, note = sent[0]
    assert to == "owner@example.com" and re.fullmatch(r"\d{6}", code)
    assert note == "TA, section B"

    # immediate re-request must NOT spam a second email
    r = client.post("/api/auth/request", data={})
    assert r.status_code == 200 and len(sent) == 1

    # wrong code -> 401, counts an attempt
    r = client.post("/api/auth/verify", data={"code": "000000"})
    assert r.status_code == 401

    # right code -> session that unlocks the API
    r = client.post("/api/auth/verify", data={"code": code})
    assert r.status_code == 200
    session = r.json()["session"]
    assert _session_ok(session)

    assert client.get("/api/jobs").status_code == 401
    r = client.get("/api/jobs", headers={"x-copcat-session": session})
    assert r.status_code == 200

    # the code is burned after use
    r = client.post("/api/auth/verify", data={"code": code})
    assert r.status_code == 401


def test_too_many_wrong_attempts_burns_code(code_mode):
    client.post("/api/auth/request", data={})
    code = code_mode[0][1]
    for _ in range(5):
        r = client.post("/api/auth/verify", data={"code": "999999"})
    assert r.status_code == 401
    # even the correct code no longer works
    assert client.post("/api/auth/verify",
                       data={"code": code}).status_code == 401


def test_master_key_works_in_code_mode(code_mode, monkeypatch):
    # a master key set on top of code mode must still unlock the API
    monkeypatch.setenv("COPCAT_ACCESS_TOKEN", "master123")
    assert client.get("/api/auth/mode").json() == {"mode": "code"}
    r = client.get("/api/jobs", headers={"x-copcat-key": "master123"})
    assert r.status_code == 200
