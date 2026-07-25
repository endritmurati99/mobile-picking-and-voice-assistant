"""Tests for Whisper hardening: domain prompt + hallucination filter."""

import pytest

import app.services.whisper_client as wc


class _FakeResp:
    status_code = 200
    text = "fake"

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    is_closed = False

    def __init__(self, payload):
        self._payload = payload
        self.last = None

    async def post(self, url, params=None, files=None):
        self.last = {"url": url, "params": params}
        return _FakeResp(self._payload)


@pytest.mark.asyncio
async def test_hallucination_dropped(monkeypatch):
    fake = _FakeClient(
        {
            "text": "Untertitelung des ZDF",
            "segments": [{"no_speech_prob": 0.95, "text": "Untertitelung des ZDF"}],
        }
    )
    monkeypatch.setattr(wc, "_get_client", lambda: fake)
    assert await wc.transcribe_audio(b"x", "audio/wav") == ""


@pytest.mark.asyncio
async def test_real_speech_kept_and_prompt_sent(monkeypatch):
    fake = _FakeClient(
        {
            "text": "auftrag fertig",
            "segments": [{"no_speech_prob": 0.05, "text": "auftrag fertig"}],
        }
    )
    monkeypatch.setattr(wc, "_get_client", lambda: fake)
    result = await wc.transcribe_audio(b"x", "audio/wav")
    assert result == "auftrag fertig"
    assert fake.last["params"].get("initial_prompt") == wc.DOMAIN_PROMPT


@pytest.mark.asyncio
async def test_no_segments_keeps_text(monkeypatch):
    # If the ASR service returns no segments, the filter is a graceful no-op.
    fake = _FakeClient({"text": "weiter"})
    monkeypatch.setattr(wc, "_get_client", lambda: fake)
    assert await wc.transcribe_audio(b"x", "audio/wav") == "weiter"
