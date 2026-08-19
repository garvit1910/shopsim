# fixtures/nisolo — the real brand in the demo

Nisolo is a real, independent footwear and leather-goods company: **Certified B
Corp since 2017** (top-rated among leather-goods companies), **Leather Working
Group certified** leather, **Climate Neutral Certified**, and a **100% living
wage** for the workers in its Tier-1 factories in Peru and Mexico. Prices and
product facts here are the brand's real ones — see `eval/market-research.md` §6
for every citation.

The five creatives are the brand's own campaign images, supplied for this
simulation. They are one brand testing **five angles**: sustainability, product
features, a flat sale, a tiered sale, and brand/lifestyle. `headline` and `body`
transcribe what each image says, extended with verified brand facts.

## What is real, what is modelled, what is assumed

- **Real:** the images, the prices, the certifications, the product features.
- **Modelled:** shopper reactions. Claims are *perceived* from the images by a
  multimodal model once, then frozen in `perception-cache/` — the "Up to 40%
  Off" figure is read off the creative, never typed into the fixture.
- **Assumed:** ad spend (impressions × a researched CPM, in the dashboard, never
  engine truth), and shopper budgets (scaled ×2.2 from the value-tier demo
  personas, anchored on real footwear spend data).
- **NOT modelled:** the tiered creative's *cart-threshold* offer (25% over $125,
  40% over $250). The engine discounts per product with no cart-total condition,
  so that mechanic exists only as a perceived claim. The ad card says so.

Generated copy is written for this simulation and should not be presented as
Nisolo's own published marketing.

## Regenerating the perception cache

```
python -m shopsim.experiments perceive-catalog \
    --catalog fixtures/nisolo --cache fixtures/nisolo/perception-cache
```

Cache keys include `sha256` of the image bytes, so **never re-encode an image**
and never hand-edit an entry — a hand-written claim would make "perceived, not
authored" a lie, and `tests/test_nisolo_fixture.py` fails if the discount stops
coming from the image. Re-running with the cache present makes **zero** calls.
