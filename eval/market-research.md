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
- The **demo-brand** catalog ($35–60) is a coherent **budget/value tier** — ~35%
  of the real market. No reprice needed; its segment budgets and `budget_cap`s
  are set to value-tier spend levels rather than the $133 all-market mean.
  *(Amended 2026-08-19: this rationale now covers `fixtures/demo-brand/` only.
  The Nisolo catalog is a real premium-tier brand and ships its own personas
  and goal_config — see §6.)*
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

## 5. Ad CPM — the cost side of the dashboard's money tiles (Phase 5)

The simulation produces impressions (`SAW`) and real purchase amounts
(`BOUGHT.price`), but it has no cost model: nothing in the engine knows what
an impression is worth to buy. The dashboard's SPEND and ROAS tiles need one
number — a cost per thousand impressions — and it is an *assumption layered on
top of the simulation*, not a simulated quantity, so it is stated here and
labelled in the UI rather than buried in a component.

| Metric | Value | Source |
|---|---|---|
| Meta/Facebook median CPM, all industries (2025) | ~$13.48 | [Triple Whale, Facebook ad benchmarks](https://www.triplewhale.com/blog/facebook-ads-benchmarks) |
| Meta median CPM, e-commerce vertical (Jul 2025–Jul 2026) | ~$13.88 | [MHI Growth Engine, Meta ecommerce benchmarks](https://mhigrowthengine.com/blog/meta-ads-benchmarks-ecommerce-2026/) |
| Meta average CPM, e-commerce (2025) | ~$16.80 | [SuperAds, Facebook CPM for e-commerce](https://www.superads.ai/facebook-ads-costs/cpm-cost-per-mille/e-commerce) |
| Typical industry CPM band (region/objective dependent) | $5–18 | [Sovran, Meta CPM by industry](https://sovran.ai/benchmarks/meta-ads-cpm-by-industry) |
| Google Display Network average CPM (cheaper channel, for contrast) | ~$3.12 | [Digital Applied, display advertising benchmarks](https://www.digitalapplied.com/blog/display-advertising-benchmarks-2026-data-points) |

**Constant adopted: `CPM_USD = 13.88`** (`web/lib/economics.ts`), the Meta
e-commerce median. Paid social is the right channel to price against rather
than the ~$3 display network: §1 already calibrates population-mean
P(CLICK|exposure) to **0.5–2%**, which is the social/Meta retail CTR band
(1.59–1.71%), not the 0.46% Display Network one. Pricing social-grade clicks at
display-grade CPMs would flatter ROAS by roughly 4×.

**How the tiles read it:** `spend = impressions × 13.88 / 1000`, `revenue = Σ
BOUGHT.price` (simulated, real), `ROAS = revenue / spend`. At demo scale
(200 shoppers × 60 days) impressions land in the tens of thousands, so spend is
in the hundreds of dollars — the UI labels these **SIM-SCALE $** so nobody
reads them as a full campaign budget. Only the CPM is assumed; the revenue side
is entirely simulated behavior.

## 6. Nisolo — the real brand in the demo (Phase 5.8)

The demo brand is no longer invented. `fixtures/nisolo/` carries Nisolo's real
products, real prices, and five of the brand's own campaign creatives. Brands in
this repo were fictional up to Phase 5; from here the *advertiser* is real while
the *shoppers* remain simulated, so every number below is cited rather than
chosen.

### Prices adopted (the catalog)

| Product | Price | Source |
|---|---|---|
| Huarache Sandal 2.0, Women's | $109 (reg. $138) | [Nisolo, Huarache 2.0](https://nisolo.com/pages/huarache-2-0) |
| Huarache Sandal 2.0, Men's | $150 | [Nisolo, men's Huarache 2.0](https://nisolo.com/products/mens-huarache-sandal-2-0-brandy) |
| Huarache Lug Sandal | $148 | [Nisolo, huarache sandals](https://nisolo.com/collections/huarache-sandals) |
| Diego Everyday Sneaker | $160 | [Nisolo, men's shoes](https://nisolo.com/collections/mens-shoes) |
| Everyday Chukka Boot | $178 | [Nisolo, everyday chukka](https://nisolo.com/collections/everyday-chukka-boot) |
| Go-To Chelsea Boot 2.0 | $250 | [Nisolo, Go-To Chelsea 2.0](https://nisolo.com/products/go-to-chelsea-boot-2-0-black) |
| Camila Everyday Tote | $295 | [Nisolo, women's bags](https://nisolo.com/collections/womens-bags) |

Product attributes are the brand's own claims: the Everyday Chukka's **5-layer
memory-foam insole with built-in arch support, gripped rubber sole savers and
heel caps** map to CUSHIONING / ARCH_SUPPORT / GRIP / DURABILITY.

### Brand facts behind the ad copy

| Claim | Source |
|---|---|
| Certified B Corp since 2017; top-rated leather-goods company, top-3 footwear | [Nisolo, why we're a top-rated B Corp](https://uk.nisolo.com/blogs/stride-sustainability/why-nisolo-is-a-top-rated-certified-bcorporation) |
| 100% living wage for workers in Tier-1 factories (Peru, Mexico) | [The Wellness Feed, Nisolo living wages](https://thewellnessfeed.com/nisolo-artisan-made-sustainable-leather-chelsea-boots-1020/) |
| Leather Working Group certified leather, meat-industry byproduct | [EcoCult, Nisolo's approach to leather](https://ecocult.com/is-leather-sustainable-heres-nisolos-holistic-approach-to-using-it/) |
| Climate Neutral Certified | [The Honest Consumer, Nisolo](https://www.thehonestconsumer.com/blog/nisolo-sustainable-shoes) |

### Budgets adopted (why they had to move)

Two **absolute-dollar** gates decide whether a catalog is buyable at all:
`choice.py` hard-blocks BUY when `price > budget_left`, and damps it ×0.25 when
`price > active_need.budget_cap`. Against value-tier budgets ($90–180) a
$109–295 catalog is almost entirely unpurchasable, and the funnel reads as
broken rather than expensive.

| Anchor | Value | Source |
|---|---|---|
| Average annual US consumer-unit footwear spend | ~$461 | [Statista, average annual footwear expenditure](https://www.statista.com/statistics/937094/average-annual-consumer-expenditure-on-footwear-by-age-us/) |
| Pairs bought per household per year | ~3.4 | [RunRepeat, shoe consumption statistics](https://runrepeat.com/shoe-consumption-statistics) |
| ⇒ implied spend per pair | ~$136 | derived; agrees with the ~$133 MSRP in §3 |
| Premium sustainability willingness-to-pay | ~+9.7% | [PwC 2024 Voice of the Consumer](https://www.pwc.com/gx/en/news-room/press-releases/2024/pwc-2024-voice-of-consumer-survey.html) |
| US shoe buyers willing to pay more for sustainable shoes | 64% | [First Insight](https://www.firstinsight.com/press-coverage/64-of-us-shoe-consumers-say-ready-to-pay-more-for-sustainable-shoes) |

**Adopted: `fixtures/nisolo/personas.json` scales every segment's
`coeffs.budget` ×2.2** (deal_stacker [176, 35] … quality_investor [484, 97]),
which puts the median segment near 1.6× a median Nisolo item — consistent with
a considered premium purchase against a ~$136/pair market average plus a
sustainability premium. Ordering and spread are preserved, so **the deal-driven
segments remain priced out of the $250 boot and $295 tote**; that constraint is
what makes the discount ladder informative rather than decorative.
`budget_cap_by_category` is set from the observed bands (5502 sandals $130,
5500 casual shoes $175, 5506 accessories $320), and `arrival_rates_per_tick` is
re-keyed onto the categories Nisolo actually sells — a need in a category with
no products can never convert.

### Two honest caveats

1. **The tiered creative is not fully modelled.** "25% off $125+, 40% off $250+"
   is a *cart-threshold* offer; the engine discounts per product with no
   cart-total condition. The tier survives only as a **perceived claim** raising
   `offer_attractiveness`. Stated on the ad card and in the fixture.
2. **The demo runs an accelerated market.** At the calibration in §1
   (P(CLICK|exposure) 0.5–2%) a demo-scale population produces single-digit
   clicks and no purchases, so the money tiles read $0. Demo runs therefore
   loosen `calibration.stage_bases.CLICK`, which raises CTR far above the real
   band. **The dashboard states the multiple on screen** (measured CTR ÷ the
   1.25% mid-band reference) so an accelerated rate is never mistaken for a
   real-world one. Nothing else is rescaled: prices, budgets and purchase
   amounts stay as cited above.
