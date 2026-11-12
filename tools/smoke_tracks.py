"""Verify real track transforms in an isolated Recoil test game.

The temporary game depends on My Game v0.1 and adds a test gadget; the actual game
files and its driving physics are never modified. Two sparse screenshots are
captured, while assertions inspect actual piece positions and matrices.
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
    parser.add_argument("--timeout", type=int, default=140)
    parser.add_argument("--model", choices=("ztz99a", "m1a1"), default="ztz99a")
    parser.add_argument("--safe-mode", action="store_true", help="Use isolated conservative rendering settings")
    args = parser.parse_args()
    output = pathlib.Path(tempfile.mkdtemp(prefix="mygame-track-smoke-"))
    game = output / "games" / "MyGameTrackSmoke.sdd"
    gadgets = game / "LuaRules" / "Gadgets"
    gadgets.mkdir(parents=True)
    (game/"ModInfo.lua").write_text('return {name="MyGame Track Smoke", shortname="MGTrack", '
        'game="MyGame Track Smoke", shortgame="MGTrack", version="v1", modtype=1, '
        'depend={"My Game v0.1"}}\n', encoding="utf-8")
    unit_name = "mbt" if args.model == "ztz99a" else "m1a1"
    (game/"track_smoke_config.lua").write_text(
        f'return {{trackData="scripts/{args.model}_track_data.lua", unitName="{unit_name}"}}\n',
        encoding="utf-8")
    shutil.copy2(ROOT/"tools"/"track_test_gadget.lua", gadgets/"test_track_animation.lua")
    widgets = output / "LuaUI" / "Widgets"
    widgets.mkdir(parents=True)
    shutil.copy2(ROOT/"tools"/"track_test_widget.lua", widgets/"zz_track_smoke.lua")
    script_name = "mbt_test.txt" if args.model == "ztz99a" else "m1a1_test.txt"
    script = (ROOT/"tools"/script_name).read_text(encoding="utf-8")
    script = script.replace("GameType=My Game v0.1;", "GameType=MyGame Track Smoke v1;")
    script = script.replace("StartPosX=2224;", "StartPosX=3000;")
    script = script.replace("StartPosZ=1536;", "StartPosZ=2048;")
    startscript = output / "track_test.txt"
    startscript.write_text(script, encoding="utf-8")
    code = run_client(ROOT.parents[1], output, startscript, args.timeout, safe_mode=args.safe_mode)
    log_path = output / "infolog.txt"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    checks = {name: value == "true" for name,value in re.findall(r"\[TRACK_SMOKE\] CHECK (\w+)=(true|false)", log)}
    required = {"forward", "stopped", "reverse", "pivot", "closed_path", "shoe_orientation", "stable_chassis"}
    errors = [line for line in log.splitlines() if re.search(r"\b(?:error|failed|traceback)\b",line,re.I)
              and re.search(r"track|ztz99|m1a1|mbtscript|MyGame Track Smoke",line,re.I)]
    errors.extend(line for line in log.splitlines()
                  if re.search(r"graphics card driver|hang detected|out of (?:video )?memory",line,re.I))
    shots = sorted((output/"screenshots").glob("*.png"))
    passed = (code == 0 and "[TRACK_SMOKE] complete" in log and set(checks) == required
              and all(checks.values()) and not errors and len(shots) >= 2)
    report = {"exit_code":code, "output":str(output), "model":args.model, "safe_mode":args.safe_mode, "checks":checks, "errors":errors,
              "signals":[line for line in log.splitlines() if "[TRACK_SMOKE]" in line],
              "screenshots":[str(p) for p in shots], "passed":passed}
    (output/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2),flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
