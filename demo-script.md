# ShopSim demo script

[0:00–0:31] Landing page

Hi, I'm Garvit. This is ShopSim — shopper simulation for advertising. Instead of asking a persona what it thinks of your ad, we run shoppers who remember: every ad they've seen, what they believe, what they need, who they trust. A recent paper by Light Society simulated a billion agents, and the hard part wasn't the agents — it was their state. That's what we built on HydraDB: each shopper's memory is a living graph of relationships [— preferences, beliefs, needs, history, friendships —] and every choice is a retrieval from that graph.

[0:31–0:55] Studio

This is the Studio — Nisolo's five real ad creatives. A vision model reads each image once — that "40% off" badge was read straight off the creative, nobody typed it in — and what it reads is stored in HydraDB as the claims each ad makes. I want to know which angle, which hook, which positioning wins the clicks, the carts, the purchases. Run the market.

[0:55–1:31] Market

A hundred shoppers, twenty-eight days, one market — the ads compete for the same people. Every day a shopper is shown an ad, and HydraDB retrieves their memory first: do they like what this ad is about? do they need this product? how often have they seen this message? do they trust this brand? has a friend bought it? That retrieval walks relationships two and three hops deep, and decides whether they ignore, click, browse, cart, or buy. [Watch the river — budget flows toward the ads earning clicks.] And every click and purchase is written straight back into HydraDB, so tomorrow's shopper is not the same as today's. [Nothing is ever overwritten — you can read any shopper's memory as it was on any day.]

[1:31–2:12] Mind

This is one shopper's mind — Ruth, style-conscious, ninety-six dollars left, and a need for casual shoes. Every node here is a real relationship in HydraDB. The ad enters at the eye; HydraDB retrieval lights up the paths that drove her decision: she prefers eco-friendly, which this ad claims; she needs casual shoes, which this ad sells; she's already seen the sale ad make the same claim — fatigue; and a friend she trusts bought this exact product. Those paths become her appraisal, and the appraisal becomes the funnel: forty-five percent she clicks, twenty-six browses, eight carts — and zero buys, because it costs a hundred and sixty dollars and she has ninety-six. [Switch the ad, and the same memory gives a different answer.]

[2:12–2:45] Graph

And minds aren't islands. HydraDB doesn't just hold the web inside one shopper — it holds the relationships between shoppers. Here are three who trust each other — Owen, Duaa, Jack. When Jack buys something and it arrives well, that experience travels along the trust edge into Owen's mind and changes how credible the brand looks to him — one person's memory reshaping another's. [Solid lines are relationships HydraDB actually stores; drag the timeline and you're reading the store as it was that day.] Across thousands of shoppers, every preference, belief and friendship is maintained, retrieved and traversed in HydraDB. A trusted friend's purchase lifted buying here by about thirty percent.

[2:45–3:00] Full report

And the full report: the funnel by segment and stage, and recommendations where every card cites its numbers — which ad deserves the budget, when to run it. Real ads, shoppers who remember, one graph. That's ShopSim, on HydraDB.
