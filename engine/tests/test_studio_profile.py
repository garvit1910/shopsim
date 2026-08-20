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
