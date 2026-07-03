"""Thin Anthropic wrapper shared by title-block parsing and Tier-3 tie-points.

One job: send an image (+ optional context images) to a vision model and get
back a validated pydantic object via forced tool-use. Prompts specific to a
tier live in their own modules; this file knows nothing about title blocks or
tie-points. Degrades to a clear disabled state when no key / cfg.enabled False,
so the rest of the pipeline can run without an API key.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import TypeVar

from PIL import Image
from pydantic import BaseModel

from autogeo.config.schema import LlmConfig
from autogeo.logging import get_logger

log = get_logger("ocr.llm")
T = TypeVar("T", bound=BaseModel)

_DEFAULT_ENV = Path("D:/Repo/AUTOGEO/.env")


class LlmDisabledError(RuntimeError):
    """Raised when an LLM call is attempted but no provider is configured."""


def load_api_key(env_path: Path | None = None) -> str | None:
    """Resolve the Anthropic key: ANTHROPIC_API_KEY env var, else the .env file
    (accepts a bare key or `NAME=value` on the first line)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    path = env_path or _DEFAULT_ENV
    if path.exists():
        first = path.read_text(encoding="utf-8").strip().splitlines()
        if first:
            line = first[0].strip()
            key = line.split("=", 1)[1].strip() if "=" in line else line
            if key.startswith("sk-ant-"):
                return key
    return None


def _encode_image(image: Image.Image | bytes | Path, max_px: int) -> tuple[str, str]:
    """Return (media_type, base64). Downscale longest side to max_px; PNG for
    bilevel/line art (lossless), JPEG otherwise to keep payloads small."""
    if isinstance(image, (bytes, bytearray)):
        img = Image.open(io.BytesIO(image))
    elif isinstance(image, Path):
        img = Image.open(image)
    else:
        img = image
    if img.mode == "1":
        img = img.convert("L")
    longest = max(img.size)
    if longest > max_px:
        scale = max_px / longest
        img = img.resize((round(img.width * scale), round(img.height * scale)))
    buf = io.BytesIO()
    if img.mode in ("L", "RGB"):
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        media = "image/jpeg"
    else:
        img.save(buf, format="PNG")
        media = "image/png"
    return media, base64.standard_b64encode(buf.getvalue()).decode()


class LlmClient:
    """Vision structured-output client. Construct once per run; reused by tiers."""

    def __init__(self, cfg: LlmConfig, api_key: str | None = None):
        self.cfg = cfg
        self._key = api_key if api_key is not None else load_api_key()
        self._client = None
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    @property
    def available(self) -> bool:
        return bool(self.cfg.enabled and self._key)

    def _ensure_client(self):
        if self._client is None:
            if not self.available:
                raise LlmDisabledError(
                    "LLM disabled: set ANTHROPIC_API_KEY / .env sk-ant- key, or llm.enabled=true"
                )
            import anthropic

            self._client = anthropic.Anthropic(api_key=self._key)
        return self._client

    def parse_image(
        self,
        images: Image.Image | bytes | Path | list,
        schema: type[T],
        prompt: str,
        *,
        max_tokens: int = 2048,
    ) -> T:
        """Send image(s) + prompt, force the model to return `schema` via tool-use."""
        client = self._ensure_client()
        if not isinstance(images, list):
            images = [images]
        content: list[dict] = []
        for im in images:
            media, b64 = _encode_image(im, self.cfg.max_image_px)
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": media, "data": b64}})
        content.append({"type": "text", "text": prompt})

        tool = {
            "name": "emit",
            "description": f"Return the extracted data as {schema.__name__}.",
            "input_schema": schema.model_json_schema(),
        }
        resp = client.messages.create(
            model=self.cfg.model,
            max_tokens=max_tokens,
            tools=[tool],
            tool_choice={"type": "tool", "name": "emit"},
            messages=[{"role": "user", "content": content}],
        )
        self.calls += 1
        self.input_tokens += resp.usage.input_tokens
        self.output_tokens += resp.usage.output_tokens
        log.info("llm parse_image model=%s in=%d out=%d",
                 self.cfg.model, resp.usage.input_tokens, resp.usage.output_tokens)
        for block in resp.content:
            if block.type == "tool_use":
                return schema.model_validate(block.input)
        raise RuntimeError("model did not return a tool_use block")
