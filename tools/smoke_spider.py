"""Check SP-6 gait and construction in a fresh, local-only Recoil client.

Only the temporary dependent game levels a test patch and uses MoveCtrl. The
installed game, production lists, user settings and other clients stay untouched.
"""

import argparse
import json
import pathlib
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from smoke_mbt import run_client

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=160)
    parser.add_argument("--safe-mode", action="store_true")
    parser.add_argument("--gait-only", action="store_true", help="Skip the real construction cycle")
    args = parser.parse_args()
    output = pathlib.Path(tempfile.mkdtemp(prefix="mygame-spider-smoke-"))
    game = output/"games"/"MyGameSpiderSmoke.sdd"
    gadgets = game/"LuaRules"/"Gadgets"
    gadgets.mkdir(parents=True)
    (game/"ModInfo.lua").write_text(
        'return {name="MyGame Spider Smoke", shortname="MGSpider", '
        'game="MyGame Spider Smoke", shortgame="MGSpider", version="v1", '
        'modtype=1, depend={"My Game v0.1"}}\n', encoding="utf-8")
    (game/"spider_smoke_config.lua").write_text(
        'return {gaitOnly=' + str(args.gait_only).lower() + '}\n', encoding="utf-8")
    shutil.copy2(ROOT/"tools"/"spider_test_gadget.lua", gadgets/"test_spider_animation.lua")
    widgets = output/"LuaUI"/"Widgets"
    widgets.mkdir(parents=True)
    shutil.copy2(ROOT/"tools"/"spider_test_widget.lua", widgets/"zz_spider_smoke.lua")
    script = (ROOT/"tools"/"m1a1_test.txt").read_text(encoding="utf-8")
    script = script.replace("GameType=My Game v0.1;", "GameType=MyGame Spider Smoke v1;")
    script = script.replace("StartPosX=2224;", "StartPosX=3000;")
    startscript = output/"spider_test.txt"
    startscript.write_text(script, encoding="utf-8")
    code = run_client(ROOT.parents[1], output, startscript, args.timeout, safe_mode=args.safe_mode)
    log_path = output/"infolog.txt"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    checks = {name: value == "true" for name, value in
              re.findall(r"\[SPIDER_SMOKE\] CHECK (\w+)=(true|false)", log)}
    required = {"native_coordinates", "tripod_support", "restart_support", "feet_above_ground",
                "forward_contact", "reverse_contact", "pivot_direction", "stopped", "stable_chassis"}
    if not args.gait_only:
        required.update({"build_menu", "construction_progress", "construction_complete", "build_arms",
                         "nano_emitters", "move_after_build"})
    errors = [line for line in log.splitlines()
              if re.search(r"\b(?:error|failed|traceback)\b", line, re.I)
              and re.search(r"spider|SP-6|MyGame Spider Smoke", line, re.I)]
    errors.extend(line for line in log.splitlines()
                  if re.search(r"graphics card driver|hang detected|out of (?:video )?memory", line, re.I))
    unrelated_errors = [line for line in log.splitlines()
                        if re.search(r"\berror\b", line, re.I) and line not in errors]
    shots = sorted((output/"screenshots").glob("*.png"))
    passed = (code == 0 and "[SPIDER_SMOKE] complete" in log and set(checks) == required
              and all(checks.values()) and not errors and len(shots) >= (2 if args.gait_only else 3))
    report = {"exit_code": code, "output": str(output), "safe_mode": args.safe_mode,
              "gait_only": args.gait_only, "checks": checks, "errors": errors,
              "unrelated_errors": unrelated_errors,
              "signals": [line for line in log.splitlines() if "[SPIDER_SMOKE]" in line],
              "screenshots": [str(p) for p in shots], "passed": passed}
    (output/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
