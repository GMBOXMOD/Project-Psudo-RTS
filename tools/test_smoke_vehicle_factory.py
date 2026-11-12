"""Report-integrity tests; these do not launch Recoil or certify native behaviour."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_vehicle_factory as smoke


def valid_events():
    key = "f0_spider_01"
    envelope = {"min": [-30, 0, 82], "max": [30, 24, 150], "matrixError": 0, "corners": 288}
    events = [
        {"event": "ready", "frame": 30, "factory": 1000, "gameSpeed": 30},
        {"event": "fixture_unit", "frame": 30, "id": 1000, "role": "direct_created_completed_factory", "label": "f0", "facing": 0},
        {"event": "screenshot", "frame": 60, "stage": smoke.QUICK_SHOTS[0], "seq": 1, "unit": -1, "progress": -1},
        {"event": "build_order", "frame": 70, "key": key, "factory": 1000, "name": "spider", "sequence": 1, "options": "none"},
        {"event": "product_created", "frame": 120, "key": key, "id": 2001, "factory": 1000, "progress": 0.001, "role": "native_factory_product"},
        {"event": "product_sample", "frame": 150, "key": key, "id": 2001, "progress": 0.09},
        {"event": "screenshot", "frame": 210, "stage": smoke.QUICK_SHOTS[1], "seq": 2, "unit": 2001, "progress": 0.3},
        {"event": "unit_finished_callin", "frame": 450, "key": key, "id": 2001, "progress": 1},
        {"event": "unit_from_factory", "frame": 450, "key": key, "id": 2001, "factory": 1000, "progress": 1},
        {"event": "product_finished", "frame": 450, "key": key, "id": 2001, "progress": 1, "elapsedFrames": 330, "advances": 300},
        {"event": "door_clear", "frame": 510, "key": key, "id": 2001, "progress": 1, "envelope": envelope},
        {"event": "yard_clear", "frame": 520, "key": key, "id": 2001, "progress": 1, "envelope": envelope, "yardFront": 80},
        {"event": "rally_arrival", "frame": 590, "key": key, "id": 2001, "progress": 1, "distance": 20, "envelope": envelope},
        {"event": "screenshot", "frame": 600, "stage": smoke.QUICK_SHOTS[2], "seq": 3, "unit": 2001, "progress": 1},
    ]
    events += [{"event": "check", "frame": 700, "name": name, "passed": True} for name in sorted(smoke.QUICK_CHECKS)]
    events += [{"event": "scenario_end", "frame": 700, "reason": "finished"}, {"event": "client_end", "frame": 710}]
    for event in events:
        event["mode"] = "quick"
    return events


def report(events, count=3, extra=""):
    text = "\n".join(smoke.PREFIX + json.dumps(e) for e in events) + "\n" + extra
    return smoke.parse_report(text, "quick", 0, [object()] * count)


class ReportIntegrity(unittest.TestCase):
    def test_complete_quick_transcript(self):
        self.assertTrue(report(valid_events())["passed"])

    def test_duplicate_check_does_not_overwrite(self):
        events = valid_events()
        events.insert(-2, copy.deepcopy(next(e for e in events if e["event"] == "check")))
        self.assertFalse(report(events)["passed"])

    def test_missing_check(self):
        events = valid_events()
        events.remove(next(e for e in events if e["event"] == "check"))
        self.assertFalse(report(events)["passed"])

    def test_early_complete(self):
        events = valid_events()
        end = events.pop(-2)
        events.insert(5, end)
        self.assertFalse(report(events)["passed"])

    def test_missing_phase_even_with_three_files(self):
        events = [e for e in valid_events() if e.get("stage") != smoke.QUICK_SHOTS[1]]
        self.assertFalse(report(events)["passed"])

    def test_duplicate_phase_is_not_three_stages(self):
        events = valid_events()
        next(e for e in events if e.get("stage") == smoke.QUICK_SHOTS[1])["stage"] = smoke.QUICK_SHOTS[0]
        self.assertFalse(report(events)["passed"])

    def test_missing_screenshot_file(self):
        self.assertFalse(report(valid_events(), count=2)["passed"])

    def test_duplicate_product_identity(self):
        events = valid_events()
        events.insert(6, copy.deepcopy(next(e for e in events if e["event"] == "product_created")))
        self.assertFalse(report(events)["passed"])

    def test_claims_without_actual_product_evidence(self):
        events = [e for e in valid_events() if "key" not in e]
        self.assertFalse(report(events)["passed"])

    def test_unfinished_product_cannot_pass_rally(self):
        events = valid_events()
        next(e for e in events if e["event"] == "rally_arrival")["progress"] = 0.99
        self.assertFalse(report(events)["passed"])

    def test_centre_outside_but_envelope_inside(self):
        events = valid_events()
        next(e for e in events if e["event"] == "yard_clear")["envelope"]["min"][2] = 40
        self.assertFalse(report(events)["passed"])

    def test_production_screenshot_after_completion(self):
        events = valid_events()
        next(e for e in events if e.get("stage") == smoke.QUICK_SHOTS[1])["progress"] = 1
        self.assertFalse(report(events)["passed"])

    def test_new_factory_error_fails_next_to_legacy_error(self):
        extra = "Error: vehicle_factory.s3o failed to load\nError: Couldn't find WeaponDef NOWEAPON and explodeAs for commander is missing!"
        self.assertFalse(report(valid_events(), extra=extra)["passed"])

    def test_existing_template_error_is_separate(self):
        extra = "Error: Couldn't find WeaponDef NOWEAPON and explodeAs for factory is missing!"
        result = report(valid_events(), extra=extra)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["legacy_template_ui_errors"]), 1)

    def test_graphics_error_always_fails(self):
        self.assertFalse(report(valid_events(), extra="Warning: graphics card driver hang detected")["passed"])

    def test_unknown_script_error_fails(self):
        self.assertFalse(report(valid_events(), extra="Error: LuaRules::RunCallIn GameFrame\nvehicle_factoryscript.lua:99: bad arithmetic")["passed"])

    def test_shift_multiplier_rejected(self):
        events = valid_events()
        next(e for e in events if e["event"] == "build_order")["options"] = "shift"
        self.assertFalse(report(events)["passed"])

    def test_quick_cannot_be_full(self):
        with self.assertRaises(ValueError):
            smoke.expected("full")


if __name__ == "__main__":
    unittest.main(verbosity=2)
