# Market research grounding for Phase-2 constants

Phase-2 rule (agreed 2026-08-17): every hand-picked behavioral number is either
(a) a contract constant (evidence.py — untouchable), or (b) grounded in the
real footwear/e-commerce market data below and cited next to its use in
`engine/shopsim/minds/calibration.py` and `fixtures/demo-brand/personas.json`.
Brands stay fictional; numbers stay real.

## 1. Ad click-through rates (CTR)

| Metric | Value | Source |
|---|---|---|
| Google Display Network average CTR | ~0.46% | [Store Growers, Google Ads benchmarks](https://www.storegrowers.com/google-ads-benchmarks/) |
| Global display CTR (all formats, often-cited floor) | ~0.06–0.1% | [AI Digital, display CTR benchmarks](https://www.aidigital.com/blog/ctr-for-display-ads) |
| Meta/Facebook retail CTR | ~1.59% | [TheeDigital, Facebook Ads benchmarks](https://www.theedigital.com/blog/facebook-ads-benchmarks) |
| Meta clothing & accessories CTR | ~1.71% | [Visible Factors, Facebook Ads benchmarks](https://visiblefactors.com/facebook-ads-benchmarks/) |
| "Good" social CTR band | 0.9–1.6% | [EvenDigit, 2025-26 CTR benchmarks](https://www.evendigit.com/2025-ctr-benchmarks-trends-ad-strategy/) |

**Calibration target adopted:** population-mean P(CLICK | exposure) in
**0.5–2%**, with segment/context spread inside the PLAN's 0.5–5% checkpoint
band. Cold (unaware, no-path) shoppers ≈ 0 per face-validity law F2.

## 2. E-commerce funnel rates (post-click / page phase)

| Metric | Value | Source |
|---|---|---|
| Sitewide conversion rate, apparel | 1–3% | [TrueFit, fashion conversion benchmarks](https://www.truefit.com/post/fashion-ecommerce-conversion-rate-benchmarks) |
| Overall e-commerce conversion rate | 2.5–3% | [Nector, conversion benchmarks](https://www.nector.io/blog/ecommerce-conversion-rate-benchmarks) |
| Add-to-cart rate (fashion) | 7.1–7.7% of sessions | [Mida, funnel benchmarks](https://mida-app.io/blog/ecommerce-conversion-funnel-benchmark/) |
| Cart abandonment | ~72–76% (Americas 72.6%) | [Store Growers, ecommerce metrics](https://www.storegrowers.com/ecommerce-metrics-benchmarks/) |

**Derived per-gate targets** (page phase; consistency check:
0.5 × 0.15 × 0.26 ≈ 2% visit→purchase, matching the 1–3% apparel band):

| Gate | Target P(advance) |
|---|---|
| BROWSE (= 1 − bounce) | ~0.45–0.55 |
| CART \| browse | ~0.10–0.20 (≈ 2× the ~7% session add-to-cart rate, conditioned on non-bounce) |
| BUY \| cart | ~0.24–0.28 (= 1 − abandonment) |

## 3. Running-shoe pricing & promo depth

| Metric | Value | Source |
|---|---|---|
| Budget tier | < $60 (≈35% unit share < $50) | [Market.us running-shoe statistics](https://www.news.market.us/running-shoes-statistics/) |
| Mid-range tier (sweet spot, ~41–45% share) | $60–120 | [Custom Market Insights, US running-shoe market](https://www.custommarketinsights.com/report/us-running-shoe-market/) |
| Premium / luxury tiers | $120–200 / $200+ | same |
| Average running-shoe MSRP | ~$133 | [Product.ai running-shoe pricing guide](https://product.ai/truth-graph/running-shoes/value-pricing/) |
| Lifecycle discount depth | 20–30% (deepest ≥ month 12) | same |

**Consequences adopted:**
- The demo catalog ($35–60) is a coherent **budget/value tier** — ~35% of the
  real market. No reprice needed; segment budgets and `budget_cap`s are set to
  value-tier spend levels rather than the $133 all-market mean.
- `OFFER_NORM = 0.30`: a claimed 30% discount saturates perceived deal
  attractiveness (the top of the observed 20–30% routine promo band); the
  fixtures' 15–20% promos land at 0.5–0.67 of saturation.

## 4. Shopper segmentation (basis for the 13 authored segments)

Recurring archetypes across the sportswear-segmentation literature:
**Serious/performance runners** (technical attributes: cushioning, stability,
durability), **casual/weekend runners** (comfort, flexibility), **lifestyle
buyers** (style + sustainability, non-athletic use), **fashion
leaders/conspicuous consumers**, **sensation seekers**, **sociable followers**,
plus price-driven **deal hunters** and comfort/fit-driven buyers (wide sizes,
arch support).

Sources: [ScienceDirect, global sportswear segmentation](https://www.sciencedirect.com/science/article/abs/pii/S0148296311000749) ·
[Segmentation Study Guide, sports-shoe example](https://www.segmentationstudyguide.com/market-segmentation-example-sports-shoes/) ·
[Start.io, Nike target-market analysis](https://www.start.io/blog/nike-target-market-analysis/) ·
[BusinessDojo, shoe-store customer segments](https://dojobusiness.com/blogs/news/shoe-store-customer-segments)

The 13 segments in `fixtures/demo-brand/personas.json` map onto these
archetypes; each segment's doc string names its source archetype.
