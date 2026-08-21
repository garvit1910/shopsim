/** The published click-gate calibration, mirrored for the dashboard.
 *
 * Source of truth: `eval/results/calibration.json` ->
 * `demo_profile.click_gate_acceleration.by_click_base` (CONTRACT v3.13-draft),
 * the reference-trace replay that also publishes the demo profile's ~5.6x.
 * The engine serves the same numbers per run as `effective.click_gate`; this
 * mirror exists so the Market page can still read an accelerated run at the
 * calibrated gate when the engine serving it predates v3.13 (or is simply a
 * process that has not been restarted since the table was published).
 *
 * Pinned to the JSON by `engine/tests/test_studio_profile.py` — the same
 * precedent as Studio's DEMO_CLICK_BASE: the numbers live in TypeScript, so a
 * Python test is the only thing that can notice when they drift. */

/** minds/calibration.py DEFAULT_STAGE_BASES["CLICK"]. */
export const CALIBRATED_CLICK_BASE = 6.0;

/** CLICK base -> CTR multiple vs the calibrated gate. Keys are the base
 * formatted with %g, exactly as calibration.json keys them. */
export const CLICK_GATE_ACCELERATION: Record<string, number> = {
  "2": 31.038,
  "4.07": 5.655,
  "6": 1,
};

/** The researched real-world paid-social CTR band (market-research.md §1)
 * and its mid-point — the last-resort normalisation target when the engine
 * cannot state a multiple for a run at all. */
export const REAL_CTR_BAND: [number, number] = [0.005, 0.02];
export const REAL_CTR_REFERENCE = 0.0125;
