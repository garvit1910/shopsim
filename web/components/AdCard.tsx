"use client";

/** The ad, as an ad.
 *
 * Before this, a creative was a name and a colour chip — you could watch five
 * bands compete without ever seeing what any of them said. A card shows the
 * image, the copy, and the claims.
 *
 * The distinction it insists on: `headline`/`body` have ZERO runtime effect.
 * They are perception input (and cache-key material). What the simulation
 * reacts to is what the multimodal eye PERCEIVED — those claims become CLAIMS
 * edges, and the claimed discount becomes offer_attractiveness. Showing both,
 * labelled, is the honest version.
 */

import { proxied } from "@/lib/api";
import type { CreativeCard } from "@/lib/types";
import { fmtMoney } from "@/lib/economics";

const pct = (n: number) => `${Math.round(n * 100)}%`;

export function AdThumb({ card, size = 26 }: { card?: CreativeCard | null; size?: number }) {
  if (!card?.image_url) return null;
  return (
    <img className="adthumb" src={proxied(card.image_url)} alt=""
      style={{ width: size, height: size }} />
  );
}

/** A text-only ad still deserves to look like an ad, not like a grey box
 * with the words "TEXT AD" in it. */
function TextAdArt({ card }: { card: CreativeCard }) {
  return (
    <div className="adart">
      <span className="adart-brand">{card.brand_name}</span>
      <span className="adart-head">{card.headline || card.name}</span>
    </div>
  );
}

export default function AdCard({
  card, selected, onClick, compact = false, stat,
}: {
  card: CreativeCard;
  selected?: boolean;
  onClick?: () => void;
  compact?: boolean;
  stat?: React.ReactNode;
}) {
  const claims = card.perceived?.claims ?? card.authored_claims;
  const perceivedDiscount = Math.max(
    0, ...(card.perceived?.claimed_discounts ?? []).map((d) => d.claimed_pct));
  const offer = card.offers[0];
  const Tag = onClick ? "button" : "div";

  return (
    <Tag className={`adcard ${selected ? "sel" : ""} ${compact ? "compact" : ""}`}
      onClick={onClick} {...(onClick ? { "aria-pressed": !!selected } : {})}>
      {card.image_url
        ? <img src={proxied(card.image_url)} alt={card.headline || card.name} />
        : <TextAdArt card={card} />}

      <div className="adbody">
        <div className="adbrand">
          {card.brand_name}
          <span className="adid">{card.creative_id}</span>
        </div>
        <div className="adhead">{card.headline || card.name}</div>
        {!compact && card.body && <p className="adcopy">{card.body}</p>}

        {claims.length > 0 && (
          <div className="adclaims">
            {claims.slice(0, compact ? 3 : 6).map((c) => (
              <span className="claimchip" key={c.concept} title={`strength ${c.strength}`}>
                {c.concept.toLowerCase().replace(/_/g, " ")}
                <i style={{ width: `${Math.round(c.strength * 100)}%` }} />
              </span>
            ))}
          </div>
        )}

        {offer && (
          <div className="adoffer">
            {offer.name || `product ${offer.product_id}`}
            {offer.list_price > 0 && <b> · {fmtMoney(offer.list_price)}</b>}
            {perceivedDiscount > 0 && (
              <span className="adsale" title="read off the creative by the multimodal model, not typed into the fixture">
                reads {pct(perceivedDiscount)} off
              </span>
            )}
          </div>
        )}

        {stat && <div className="adstat">{stat}</div>}

        {!compact && card.perceived && (
          <div className="adprov">
            claims perceived {card.perceived.from_image ? "from the image" : "from the copy"}
            {" · "}{card.perceived.model}
          </div>
        )}
        {!compact && card.note && <div className="adnote">{card.note}</div>}
      </div>
    </Tag>
  );
}

/** The market page's "who is competing" strip. */
export function AdRoster({ cards, stats }: {
  cards: CreativeCard[];
  stats?: Record<number, React.ReactNode>;
}) {
  if (!cards.length) return null;
  return (
    <div className="panel hero">
      <div className="ph">
        ADS IN THIS MARKET · {cards.length}
        <span className="phnote">
          copy is what a human reads · claims are what the shoppers react to
        </span>
      </div>
      <div className="adgrid pc">
        {cards.map((c) => (
          <AdCard key={c.creative_id} card={c} compact stat={stats?.[c.creative_id]} />
        ))}
      </div>
    </div>
  );
}
