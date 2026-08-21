"""The dashboard's accelerated profile must be the one Phase 7 solved.

Studio's "accelerated market" toggle used a hand-picked `stage_bases.CLICK =
2.0` that Phase 7 explicitly retired. A 300x60 Nisolo run on it measured 35%
CTR — roughly 28x the researched 0.5-2% band — and a blended ROAS of 104x
against a real-world 1.5-4x. The committed `eval/profiles/demo.json` carries
the value solved for a stated 5% target, and this test is what keeps the two
from drifting apart again: the number lives in TypeScript, so nothing else in
the Python suite can notice when it changes.
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STUDIO = REPO / "web" / "app" / "studio" / "page.tsx"
DEMO_PROFILE = REPO / "eval" / "profiles" / "demo.json"
CALIBRATION = REPO / "eval" / "results" / "calibration.json"
WEB_CALIBRATION = REPO / "web" / "lib" / "calibration.ts"


def _studio_click_base() -> float:
    m = re.search(r"const DEMO_CLICK_BASE = ([0-9.]+);", STUDIO.read_text())
    assert m, "Studio no longer declares DEMO_CLICK_BASE"
    return float(m.group(1))


def test_studio_accelerated_click_base_matches_the_committed_demo_profile():
    committed = json.loads(DEMO_PROFILE.read_text())["calibration"]["stage_bases"]["CLICK"]
    assert _studio_click_base() == committed, (
        f"Studio ships CLICK={_studio_click_base()} but eval/profiles/demo.json "
        f"solved {committed}. Re-solve with `shopsim.eval calibrate` and update "
        f"both, or the dashboard demo runs off an uncertified profile.")


def test_the_retired_hand_picked_base_is_gone():
    """2.0 is the specific value that produced 104x ROAS. It must not come back."""
    src = STUDIO.read_text()
    assert "stage_bases: { CLICK: 2.0 }" not in src
    assert _studio_click_base() > 2.0, \
        "a CLICK base at or below the retired 2.0 puts CTR ~28x over band"


def test_the_demo_profile_only_accelerates_the_click_gate():
    """The claim that makes acceleration honest: everything below the click is
    still the certified funnel. If a future edit moves BROWSE/CART/BUY, the
    published 1.0x multiples stop being true."""
    from shopsim.minds.calibration import DEFAULT_STAGE_BASES

    demo = json.loads(DEMO_PROFILE.read_text())["calibration"]["stage_bases"]
    calibrated = dict(DEFAULT_STAGE_BASES)
    for stage in ("BROWSE", "CART", "BUY"):
        assert demo[stage] == calibrated[stage], (
            f"demo profile moved {stage} ({demo[stage]} vs the calibrated "
            f"{calibrated[stage]}) — only CLICK may differ")
    assert demo["CLICK"] < calibrated["CLICK"], "acceleration means an easier click gate"


def test_calibration_publishes_an_acceleration_for_every_base_the_dashboard_ships():
    """The market page shows CTR and ROAS at the calibrated gate by dividing
    by the published multiple for the run's own CLICK base (v3.13-draft). Both
    bases Studio can launch must be tabulated, the calibrated one at exactly
    1.0 — otherwise a calibrated run would be "de-accelerated" too — and the
    retired 2.0 stays tabulated while runs on it exist."""
    from shopsim.minds.calibration import DEFAULT_STAGE_BASES

    table = json.loads(CALIBRATION.read_text())["demo_profile"]["click_gate_acceleration"]
    calibrated = dict(DEFAULT_STAGE_BASES)["CLICK"]
    rows = {e["click_base"]: e for e in table["by_click_base"].values()}
    assert table["calibrated_click_base"] == calibrated
    assert rows[calibrated]["multiple"] == 1.0
    assert rows[_studio_click_base()]["multiple"] > 1.0, (
        "re-run `make eval-calibrate` so the committed demo base has a published multiple")
    assert rows[2.0]["multiple"] > rows[_studio_click_base()]["multiple"]
    for e in rows.values():
        assert 0.0 < e["p_click"] < 1.0


def test_web_click_gate_table_matches_calibration_json():
    """The Market page mirrors the published click-gate table so it can read an
    accelerated run at a human-scale rate even when the engine serving it
    predates v3.13. A mirror is only honest while it is identical: same bases,
    same multiples, same calibrated base."""
    from shopsim.minds.calibration import DEFAULT_STAGE_BASES

    src = WEB_CALIBRATION.read_text()
    m = re.search(r"CLICK_GATE_ACCELERATION: Record<string, number> = \{([^}]*)\}", src)
    assert m, "web/lib/calibration.ts no longer declares CLICK_GATE_ACCELERATION"
    web = {k: float(v) for k, v in re.findall(r'"([^"]+)":\s*([0-9.]+)', m.group(1))}
    table = json.loads(CALIBRATION.read_text())["demo_profile"]["click_gate_acceleration"]
    published = {k: float(row["multiple"]) for k, row in table["by_click_base"].items()}
    assert web == published, (
        f"web mirror {web} != calibration.json {published}; re-run `make eval-calibrate` "
        f"and copy the table into web/lib/calibration.ts")
    cb = re.search(r"const CALIBRATED_CLICK_BASE = ([0-9.]+);", src)
    assert cb and float(cb.group(1)) == dict(DEFAULT_STAGE_BASES)["CLICK"] == table["calibrated_click_base"]
