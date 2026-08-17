# /fixtures/demo-brand — the fictional marketplace

All brands, products, and people are fictional. Ids follow Appendix A
(`engine/shopsim/contracts/ids.py`); every concept/category id is a member of
the closed enums (`enums.py`) — parse-time enforced.

| File | What it seeds |
|---|---|
| `catalog.csv` | 7 products across ShoeCo (6001), TrailForge (6002), UrbanStride (6003); `attr_concept_ids` (pipe-separated) become HAS_ATTR edges, `category_id` becomes IN_CATEGORY — always from this CSV, never from the LLM |
| `latent_quality.csv` | **hidden layer (Law 15)**: reaches minds only through generated EXPERIENCED events (`sat = clamp01(latent_quality + noise)`); flagged unretrievable at ingest; 3000006 (0.35) is the bad-arm exhibit for F11 |
| `creatives.json` | 5 ads: two same-story ShoeCo eco ads (fatigue driver, F12), one ShoeCo comfort rotation arm, one TrailForge, one UrbanStride (the abstention stimulus); 2000003 is the Appendix-B stimulus |
| `page_variants.json` | page A/B: 4000002 hides the claimed DISCOUNT → expectation_violation (F5) |
| `promo_schedule.json` | 3 discount cycles on 3000001 → promo addiction (F4) + reference-price drift |
| `goal_config.json` | per-segment×category arrival rates, marathon-season wave, Maya's scripted need (beat 4) |
| `social_config.json` | P1 small-world trust graph parameters, disabled |

Canned DecisionContexts served by MockHydraMem live in `/fixtures/contexts/`.
