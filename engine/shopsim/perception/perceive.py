"""Perception as LLM reader (Phase 2.2): one strict structured-output call
per unique creative, cached forever, never deciding actions.

    raw creative (name/headline/body/brand/offered product ids)
        ↓ OpenAI structured outputs (strict JSON schema, temperature 0)
        ↓ Concept-enum validation (unknown → OTHER; Law 11)
        ↓ disk cache keyed by stimulus hash (Law 13)
    PerceivedCreative → ObjectiveView / graph writes (writer.py)

Pages carry no prose (their descriptors are already concept lists), so page
perception is a validated pass-through in writer.py — no LLM.

The `openai` package is an optional dependency (`perception` extra) imported
lazily: the cached path — tests, CI, replays — never needs it. The API key
comes from the environment or <repo>/.env.local (gitignored).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from .cache import default_cache_dir, load, stimulus_hash, store
from .schema import CONCEPT_NAMES, OUTPUT_JSON_SCHEMA, PerceivedCreative, parse_output

DEFAULT_MODEL = "gpt-4o-mini"
PROMPT_VERSION = "p1"
# Image ads (Phase 4, CONTRACT v3.4-draft): a separate prompt version so
# future addendum edits invalidate only image cache entries — text-creative
# descriptors, prompt, and therefore committed cache hashes stay untouched.
IMAGE_PROMPT_VERSION = "p1-img1"

IMAGE_PROMPT_ADDENDUM = (
    "This advertisement is an IMAGE. Read the claims from what the image "
    "shows and says: headline text, overlaid copy, badges (e.g. sale/discount "
    "flashes), and unambiguous visual assertions (a shoe mid-race asserts "
    "performance; leaves/earth imagery asserts eco-friendliness). Do not "
    "infer product facts the image does not itself assert, and do not "
    "describe the image — only record its claims on the concept vocabulary."
)

_CONCEPT_GLOSSES = {
    "PERFORMANCE": "athletic/race performance",
    "COMFORT": "comfort to wear",
    "DURABILITY": "lasts long, tough",
    "ECO_FRIENDLY": "good for the planet / environmentally friendly",
    "RECYCLED_MATERIALS": "made from recycled materials",
    "LIGHTWEIGHT": "the product itself is light in weight",
    "CUSHIONING": "cushioned / plush underfoot",
    "BREATHABLE": "breathable / ventilated",
    "WATERPROOF": "waterproof / weatherproof",
    "VEGAN": "vegan / no animal products",
    "PREMIUM": "premium / high-end",
    "DISCOUNT": "a price cut or sale is claimed",
    "VALUE_PRICED": "affordable / honest pricing",
    "FREE_SHIPPING": "free shipping",
    "FAST_SHIPPING": "fast shipping",
    "FREE_RETURNS": "free returns",
    "WARRANTY": "warranty / guarantee",
    "STYLE": "style / looks / fashion",
    "INNOVATIVE": "innovative technology",
    "SUSTAINABLE_PACKAGING": "sustainable packaging",
    "LOCALLY_MADE": "locally made",
    "HANDCRAFTED": "handcrafted",
    "LIMITED_EDITION": "limited edition / exclusive drop",
    "AWARD_WINNING": "award-winning",
    "EXPERT_ENDORSED": "endorsed by experts, pros or champions",
    "WIDE_SIZES": "wide sizes available",
    "ARCH_SUPPORT": "arch support",
    "GRIP": "grip / traction",
    "MACHINE_WASHABLE": "machine washable",
    "OTHER": "an explicit claim that fits no other concept",
}

SYSTEM_PROMPT = (
    "You are the perception layer of a marketing simulator. Read ONE advertisement "
    "and record only what the ad itself asserts to a shopper.\n\n"
    "Rules:\n"
    "- Map every asserted claim onto the closed concept vocabulary below; if an "
    "explicit claim fits no concept, use OTHER. Never invent claims the ad does not "
    "make, and never add product facts you happen to know.\n"
    "- strength (0..1) = how strongly and centrally the ad asserts that concept "
    "(headline claims are stronger than passing mentions).\n"
    "- Metaphors count as what they assert: 'lighter on the planet' asserts "
    "environmental friendliness, not product weight; 'featherlight' asserts weight.\n"
    "- If the ad claims a percentage discount, record claimed_pct per offered "
    "product id as a fraction (15% off -> 0.15). If no discount is claimed for a "
    "product, do not list it (or use 0.0).\n"
    "- You only read. You never predict or decide any shopper action.\n\n"
    "Concept vocabulary:\n"
    + "\n".join(f"- {name}: {_CONCEPT_GLOSSES[name]}" for name in CONCEPT_NAMES)
)


def descriptor_for(creative: dict, *, image_sha256: str | None = None) -> dict:
    """What a shopper (and therefore the LLM) sees — never the authored
    ground-truth claims or claimed_pct. The image hash is added ONLY for
    image creatives, so text-creative descriptors (and their committed cache
    hashes) are byte-identical to Phase 2 (v3.4-draft)."""
    d = {
        "creative_id": creative["creative_id"],
        "brand_id": creative["brand_id"],
        "name": creative.get("name", ""),
        "headline": creative.get("headline", ""),
        "body": creative.get("body", ""),
        "offer_product_ids": sorted(o["product_id"] for o in creative["offers"]),
    }
    if image_sha256 is not None:
        d["image_sha256"] = image_sha256
    return d


def _load_env_key() -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    for parent in Path(__file__).resolve().parents:
        env = parent / ".env.local"
        if env.exists():
            for line in env.read_text().splitlines():
                line = line.strip()
                if line.startswith("OPENAI_API_KEY="):
                    os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
                    return


def resolve_api_key() -> str | None:
    """The key as the CLI sees it: env first, then <repo>/.env.local. Public
    so callers outside this module (the runner API's ingest endpoint) check
    the same way the ingest path does — an env-only check reports "no key"
    on a repo whose .env.local works fine."""
    _load_env_key()
    return os.environ.get("OPENAI_API_KEY")


def _image_mime(image_bytes: bytes) -> str:
    """Sniff from magic bytes — the cache never stores a filename."""
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    raise ValueError("unsupported image format (need png/jpeg/webp/gif)")


def _call_openai(descriptor: dict, model: str, *, image_bytes: bytes | None = None) -> dict:
    _load_env_key()
    from openai import OpenAI  # optional dependency (perception extra)

    client = OpenAI()
    user = {
        "advertisement": {
            "name": descriptor["name"],
            "headline": descriptor["headline"],
            "body": descriptor["body"],
        },
        "offer_product_ids": descriptor["offer_product_ids"],
    }
    if image_bytes is None:
        system = SYSTEM_PROMPT
        content = json.dumps(user, sort_keys=True)
    else:
        system = SYSTEM_PROMPT + "\n\n" + IMAGE_PROMPT_ADDENDUM
        mime = _image_mime(image_bytes)
        b64 = base64.b64encode(image_bytes).decode()
        content = [
            {"type": "text", "text": json.dumps(user, sort_keys=True)},
            {"type": "image_url",
             "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_schema", "json_schema": OUTPUT_JSON_SCHEMA},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    )
    return json.loads(resp.choices[0].message.content)


def perceive_creative(
    creative: dict,
    cache_dir: Path | None = None,
    model: str = DEFAULT_MODEL,
    call=None,
    *,
    image_bytes: bytes | None = None,
) -> tuple[PerceivedCreative, bool]:
    """Returns (perceived, was_llm_called). `call` overrides the LLM invoker
    (tests inject a counting stub); cache hits never invoke anything. Image
    creatives (image_bytes) key on the image sha256 + IMAGE_PROMPT_VERSION;
    the text path is byte-identical to Phase 2 — including how `call` is
    invoked, so existing (descriptor, model) stubs keep working."""
    cache_dir = cache_dir or default_cache_dir()
    if image_bytes is None:
        descriptor = descriptor_for(creative)
        prompt_version = PROMPT_VERSION
    else:
        descriptor = descriptor_for(
            creative, image_sha256=hashlib.sha256(image_bytes).hexdigest())
        prompt_version = IMAGE_PROMPT_VERSION
    key = stimulus_hash(descriptor, prompt_version, model)
    entry = load(cache_dir, descriptor["creative_id"], key)
    called = False
    if entry is None:
        if image_bytes is None:
            output = (call or _call_openai)(descriptor, model)
        else:
            output = (call or _call_openai)(descriptor, model,
                                            image_bytes=image_bytes)
        called = True
        store(cache_dir, descriptor["creative_id"], key, descriptor,
              prompt_version, model, output)
    else:
        output = entry["output"]
    perceived = parse_output(
        descriptor["creative_id"], descriptor["brand_id"],
        descriptor["offer_product_ids"], output)
    return perceived, called


def perceive_catalog(
    demo_brand_dir: Path | str,
    cache_dir: Path | None = None,
    model: str = DEFAULT_MODEL,
    call=None,
) -> tuple[dict[int, PerceivedCreative], int]:
    """Perceive every creative in the demo catalog. Returns (by creative id,
    number of LLM calls made) — calls == unique uncached stimuli. Creative
    rows carrying "image" (a path relative to the catalog dir, v3.4-draft)
    are read and perceived through the multimodal path."""
    demo_brand_dir = Path(demo_brand_dir)
    creatives = json.loads(
        (demo_brand_dir / "creatives.json").read_text())["creatives"]
    out: dict[int, PerceivedCreative] = {}
    calls = 0
    for cr in creatives:
        image_bytes = None
        if cr.get("image"):
            image_bytes = (demo_brand_dir / cr["image"]).read_bytes()
        perceived, called = perceive_creative(cr, cache_dir, model, call,
                                              image_bytes=image_bytes)
        out[perceived.creative_id] = perceived
        calls += int(called)
    return out, calls
