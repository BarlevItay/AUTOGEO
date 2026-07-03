"""LLM client offline behavior: key resolution, image encoding, disabled mode.
Live model calls are exercised by the OCR-yield spike, not the unit suite."""

import base64

import pytest
from PIL import Image

from autogeo.config.schema import LlmConfig
from autogeo.ocr.llm_client import LlmClient, LlmDisabledError, _encode_image, load_api_key


def test_disabled_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")
    client = LlmClient(LlmConfig(enabled=True), api_key=None)
    client._key = load_api_key(empty_env)  # force the no-key path
    assert client.available is False
    with pytest.raises(LlmDisabledError):
        client.parse_image(Image.new("L", (10, 10)), LlmConfig, "x")


def test_disabled_when_config_off(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    client = LlmClient(LlmConfig(enabled=False))
    assert client.available is False


def test_load_api_key_from_env_var(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    assert load_api_key() == "sk-ant-from-env"


def test_load_api_key_rejects_non_anthropic(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("sk-proj-openaikey", encoding="utf-8")
    assert load_api_key(env) is None  # wrong provider format ignored


def test_encode_downscales_and_handles_bilevel():
    img = Image.new("1", (8000, 4000), color=1)  # bilevel, oversized
    media, b64 = _encode_image(img, max_px=2048)
    assert media in ("image/jpeg", "image/png")
    raw = base64.standard_b64decode(b64)
    from io import BytesIO

    decoded = Image.open(BytesIO(raw))
    assert max(decoded.size) <= 2048  # longest side downscaled to the cap
