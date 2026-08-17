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

import json
import os
from pathlib import Path

from .cache import default_cache_dir, load, stimulus_hash, store
from .schema import CONCEPT_NAMES, OUTPUT_JSON_SCHEMA, PerceivedCreative, parse_output

DEFAULT_MODEL = "gpt-4o-mini"
PROMPT_VERSION = "p1"

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


def descriptor_for(creative: dict) -> dict:
    """What a shopper (and therefore the LLM) sees — never the authored
    ground-truth claims or claimed_pct."""
    return {
        "creative_id": creative["creative_id"],
        "brand_id": creative["brand_id"],
        "name": creative.get("name", ""),
        "headline": creative["headline"],
        "body": creative["body"],
        "offer_product_ids": sorted(o["product_id"] for o in creative["offers"]),
    }


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


def _call_openai(descriptor: dict, model: str) -> dict:
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
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_schema", "json_schema": OUTPUT_JSON_SCHEMA},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user, sort_keys=True)},
        ],
    )
    return json.loads(resp.choices[0].message.content)


def perceive_creative(
    creative: dict,
    cache_dir: Path | None = None,
    model: str = DEFAULT_MODEL,
    call=None,
) -> tuple[PerceivedCreative, bool]:
    """Returns (perceived, was_llm_called). `call` overrides the LLM invoker
    (tests inject a counting stub); cache hits never invoke anything."""
    cache_dir = cache_dir or default_cache_dir()
    descriptor = descriptor_for(creative)
    key = stimulus_hash(descriptor, PROMPT_VERSION, model)
    entry = load(cache_dir, descriptor["creative_id"], key)
    called = False
    if entry is None:
        output = (call or _call_openai)(descriptor, model)
        called = True
        store(cache_dir, descriptor["creative_id"], key, descriptor,
              PROMPT_VERSION, model, output)
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
    number of LLM calls made) — calls == unique uncached stimuli."""
    creatives = json.loads(
        (Path(demo_brand_dir) / "creatives.json").read_text())["creatives"]
    out: dict[int, PerceivedCreative] = {}
    calls = 0
    for cr in creatives:
        perceived, called = perceive_creative(cr, cache_dir, model, call)
        out[perceived.creative_id] = perceived
        calls += int(called)
    return out, calls
