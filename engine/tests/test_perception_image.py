"""Phase 4: image-ad perception (CONTRACT v3.4-draft).

The load-bearing invariant: the TEXT path is byte-identical to Phase 2 —
descriptors, prompt version, cache keys, and how `call` stubs are invoked —
so the five committed cache entries stay valid forever. Image creatives key
on the image sha256 under IMAGE_PROMPT_VERSION.
"""

import json
from pathlib import Path

import pytest

from shopsim.perception.cache import stimulus_hash
from shopsim.perception.perceive import (
    DEFAULT_MODEL,
    IMAGE_PROMPT_VERSION,
    PROMPT_VERSION,
    _image_mime,
    descriptor_for,
    perceive_creative,
)

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "fixtures" / "perception-cache"

PNG = b"\x89PNG\r\n\x1a\n" + b"not-a-real-png-but-magic-is-what-matters"
JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-payload"

OUTPUT = {"claims": [{"concept": "ECO_FRIENDLY", "strength": 0.9}],
          "claimed_discounts": []}


def image_creative(cid=2000006):
    return {"creative_id": cid, "brand_id": 6001, "name": "Spring Hero",
            "headline": "Spring drop", "body": "",
            "offers": [{"product_id": 3000001, "claimed_pct": 0.0}]}


def test_committed_text_cache_keys_unchanged():
    """Recompute every committed creative's cache key from today's code —
    each must still point at its committed file (Law 13)."""
    creatives = json.loads(
        (REPO / "fixtures/demo-brand/creatives.json").read_text())["creatives"]
    assert len(creatives) == 5
    for cr in creatives:
        descriptor = descriptor_for(cr)
        assert "image_sha256" not in descriptor
        key = stimulus_hash(descriptor, PROMPT_VERSION, DEFAULT_MODEL)
        assert (CACHE / f"{cr['creative_id']}-{key[:16]}.json").exists()


def test_text_stub_call_shape_unchanged(tmp_path):
    """Existing (descriptor, model) stubs — no **kwargs — must keep working."""
    def strict_stub(descriptor, model):
        return OUTPUT

    cr = {**image_creative(), "body": "text ad body"}
    perceived, called = perceive_creative(cr, cache_dir=tmp_path, call=strict_stub)
    assert called
    assert perceived.claims_dict  # ECO_FRIENDLY landed


def test_image_creative_keys_on_sha_and_image_prompt_version(tmp_path):
    seen = []

    def stub(descriptor, model, *, image_bytes):
        seen.append((descriptor, image_bytes))
        return OUTPUT

    perceived, called = perceive_creative(
        image_creative(), cache_dir=tmp_path, call=stub, image_bytes=PNG)
    assert called and len(seen) == 1
    assert seen[0][1] == PNG
    assert "image_sha256" in seen[0][0]

    entries = list(tmp_path.glob("2000006-*.json"))
    assert len(entries) == 1
    entry = json.loads(entries[0].read_text())
    assert entry["prompt_version"] == IMAGE_PROMPT_VERSION
    assert entry["descriptor"]["image_sha256"] == seen[0][0]["image_sha256"]

    # frozen: the second perceive is a cache hit, zero calls
    _, called = perceive_creative(
        image_creative(), cache_dir=tmp_path, call=stub, image_bytes=PNG)
    assert not called and len(seen) == 1


def test_different_image_bytes_different_key(tmp_path):
    def stub(descriptor, model, *, image_bytes):
        return OUTPUT

    perceive_creative(image_creative(), cache_dir=tmp_path, call=stub,
                      image_bytes=PNG)
    perceive_creative(image_creative(), cache_dir=tmp_path, call=stub,
                      image_bytes=PNG + b"v2")
    assert len(list(tmp_path.glob("2000006-*.json"))) == 2


def test_image_key_differs_from_text_key():
    cr = image_creative()
    text_key = stimulus_hash(descriptor_for(cr), PROMPT_VERSION, DEFAULT_MODEL)
    img_key = stimulus_hash(descriptor_for(cr, image_sha256="ab" * 32),
                            IMAGE_PROMPT_VERSION, DEFAULT_MODEL)
    assert text_key != img_key


def test_image_mime_sniffing():
    assert _image_mime(PNG) == "image/png"
    assert _image_mime(JPEG) == "image/jpeg"
    assert _image_mime(b"RIFF\x00\x00\x00\x00WEBPrest") == "image/webp"
    assert _image_mime(b"GIF89a...") == "image/gif"
    with pytest.raises(ValueError, match="unsupported image"):
        _image_mime(b"plain text")
