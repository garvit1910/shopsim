"use client";

/** The landing hero's constellation field.
 *
 * Ported from Halgo's particle pen (codepen.io/Halgo/pen/gOywLyJ). The
 * algorithm is the pen's and stays that way: points drift, wrap at the edges,
 * and every pair closer than MAX_LINK in 3D gets a line whose alpha falls off
 * with distance. Every deviation is deliberate and noted where it happens —
 * three the brief asked for (density, speed, colour) and four the pen never
 * had to care about (retina, frame rate, resize, reduced motion).
 *
 * This is the first <canvas> in the app. It follows MemoryGraph.tsx's
 * discipline: the mutable engine lives in the effect closure, never in state,
 * and teardown stops the loop and drops every listener it added. */

import { useEffect, useRef } from "react";

/** pen: 2. +35%, inside the 30–50% the brief asked for. */
const DENSITY = 2.7;
/** The pen derives this as `lineLengthFactor / densityFact`, which means
 * raising DENSITY would have pulled the link radius in from 175 to 130.
 * Neighbours within reach scale as n·r², so that is 1.35 × (130/175)² = 0.74:
 * the web would have come out 26% THINNER than the pen's, the opposite of the
 * ask. Pinned at the pen's original 175 so more dots reads as more web. */
const MAX_LINK = 175;
/** = the pen's lineLengthFactor. The band z is seeded into; see update(). */
const DEPTH = 350;
/** Half-range of the per-axis drift. pen: 0.5 — so this is exactly 2x, which
 * is what makes links visibly form and dissolve twice as often. */
const SPEED = 1;
const RADIUS = 3;
/** The pen has no ceiling — its count is pure area × density, which on a large
 * desktop display lands near 1100 points and 600k pair tests a frame. Raised
 * from 420 when the field grew to span two full screens — at the old cap the
 * doubled area read visibly sparser per screen. */
const MAX_POINTS = 520;
/** Displacement is normalised to this, so a 120Hz panel does not run the field
 * at double speed and a restored tab does not teleport every point. */
const FRAME_MS = 1000 / 60;

/** The pen is one flat cyan. ShopSim's accent is green, and 04 Graph already
 * encodes "cyan world / green people", so the field is a ramp between the two
 * rather than a single hue. Built once at module scope: picking colours from a
 * template literal per line would allocate ~1700 strings a frame. */
function buildRamp(from: number[], to: number[], steps: number): string[] {
  const out: string[] = [];
  for (let i = 0; i < steps; i++) {
    const t = i / (steps - 1);
    const ch = (k: number) => Math.round(from[k] + (to[k] - from[k]) * t);
    out.push(`rgb(${ch(0)},${ch(1)},${ch(2)})`);
  }
  return out;
}
/** #8ffff8 (the pen's cyan) → #4fd99a (--accent-ink). */
const RAMP = buildRamp([0x8f, 0xff, 0xf8], [0x4f, 0xd9, 0x9a], 12);

class Point {
  x: number;
  y: number;
  z: number;
  xSpeed: number;
  ySpeed: number;
  zSpeed: number;
  /** Fixed index into RAMP. The 1.8 exponent biases the draw toward 0, so ~68%
   * of points land on the cyan half and green reads as an accent, not a wash. */
  ci: number;

  constructor(w: number, h: number) {
    this.x = Math.random() * w;
    this.y = Math.random() * h;
    this.z = Math.random() * (DEPTH - 1) + DEPTH;
    this.xSpeed = (Math.random() - 0.5) * 2 * SPEED;
    this.ySpeed = (Math.random() - 0.5) * 2 * SPEED;
    this.zSpeed = (Math.random() - 0.5) * 2 * SPEED;
    this.ci = Math.round(Math.random() ** 1.8 * (RAMP.length - 1));
  }

  update(k: number, w: number, h: number) {
    this.x += this.xSpeed * k;
    this.y += this.ySpeed * k;
    this.z += this.zSpeed * k;
    if (this.x < 0) this.x += w;
    if (this.x > w) this.x -= w;
    if (this.y < 0) this.y += h;
    if (this.y > h) this.y -= h;
    /** The pen's bounce test, kept exactly — quirk included. z is seeded into
     * [DEPTH, 2·DEPTH) but the ceiling tested here is DEPTH, so every point is
     * already past it on frame 1 and flips zSpeed every frame after. z
     * therefore jitters in place rather than drifting: it is a fixed per-point
     * depth deciding which pairs may EVER link (they need |Δz| < MAX_LINK),
     * and all visible motion is x/y. That gate is why the field reads as a
     * sparse constellation instead of a flat mesh — "fixing" it would open
     * every pair to every other and change the look entirely. */
    if (this.z < 0 || this.z > DEPTH) this.zSpeed = -this.zSpeed;
  }
}

export default function ParticleField() {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    const canvas = canvasRef.current;
    if (!host || !canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    const points: Point[] = [];
    let w = 0;
    let h = 0;
    let raf = 0;
    let last = 0;

    const still = window.matchMedia("(prefers-reduced-motion: reduce)");

    /** The pen sizes its backing store in CSS pixels, so on a retina display
     * every dot is upscaled 2x and reads as chunky under the blur. Render at
     * device resolution and scale the context, which keeps all the point maths
     * below in CSS pixels — no other formula has to change. */
    const measure = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = host.clientWidth;
      h = host.clientHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Hold density constant across viewports rather than seeding once.
      const target = Math.min(MAX_POINTS, Math.round((DENSITY * w * h) / 20000));
      while (points.length < target) points.push(new Point(w, h));
      if (points.length > target) points.length = target;
    };

    const draw = () => {
      ctx.clearRect(0, 0, w, h);

      /** The pen loops i × j in full, so it strokes every line TWICE. Two
       * passes at alpha a composite to 1-(1-a)² = a(2-a), so walking only
       * j > i and using that closed form paints an identical picture for half
       * the work — ~1700 strokes a frame at 1080p instead of ~3400. Comparing
       * squared distances first keeps the sqrt off the pairs that fail, which
       * is nearly all of them. */
      const reach = MAX_LINK * MAX_LINK;
      for (let i = 0; i < points.length; i++) {
        const p = points[i];
        for (let j = i + 1; j < points.length; j++) {
          const q = points[j];
          const dx = p.x - q.x;
          const dy = p.y - q.y;
          const dz = p.z - q.z;
          const d2 = dx * dx + dy * dy + dz * dz;
          if (d2 >= reach || d2 <= 4) continue;
          const a = (MAX_LINK - Math.sqrt(d2)) / MAX_LINK;
          ctx.globalAlpha = a * (2 - a);
          ctx.strokeStyle = RAMP[(p.ci + q.ci) >> 1];
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(q.x, q.y);
          ctx.stroke();
        }
      }

      // Dots last, so they stay crisp on top of the web rather than under it.
      ctx.globalAlpha = 1;
      for (const p of points) {
        ctx.fillStyle = RAMP[p.ci];
        ctx.beginPath();
        ctx.arc(p.x, p.y, RADIUS, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const frame = (now: number) => {
      const k = last ? Math.min(2, (now - last) / FRAME_MS) : 1;
      last = now;
      draw();
      for (const p of points) p.update(k, w, h);
      raf = requestAnimationFrame(frame);
    };

    const stop = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    };

    /** globals.css only zeroes CSS animation and transition durations, which
     * cannot touch a rAF loop — reduced motion has to be honoured here, and it
     * means one static frame and no loop at all. */
    const start = () => {
      if (raf || still.matches || document.hidden) return;
      last = 0;
      raf = requestAnimationFrame(frame);
    };

    measure();
    draw();
    start();

    const ro = new ResizeObserver(() => {
      measure();
      if (!raf) draw();
    });
    ro.observe(host);

    const onVisibility = () => (document.hidden ? stop() : start());
    const onStillness = () => {
      stop();
      draw();
      start();
    };
    document.addEventListener("visibilitychange", onVisibility);
    still.addEventListener("change", onStillness);

    return () => {
      stop();
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      still.removeEventListener("change", onStillness);
    };
  }, []);

  return (
    <div ref={hostRef} className="lfield" aria-hidden="true">
      <canvas ref={canvasRef} />
    </div>
  );
}
