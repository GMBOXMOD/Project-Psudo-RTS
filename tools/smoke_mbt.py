"""Run the real Recoil client in a fresh, local-only test directory.

No installed game settings or existing engine processes are changed. The temporary
widget selects the tank, issues movement/attack orders, and requests screenshots.
The exit status checks the original widget loading errors as well as model loading.
"""

import argparse
import json
import pathlib
import re
import subprocess
import tempfile


PROBE = r'''
function widget:GetInfo()
    return {name="MyGame smoke probe", desc="Temporary engine smoke test",
            author="MyGame", layer=9999, enabled=true}
end
local started, selected, moved, attacked, finished = false, false, false, false, false
local unit, enemy, x0, z0
local timer = Spring.GetTimer()
local shots = {}
function widget:Initialize()
    Spring.Echo("[MBT_SMOKE] probe_loaded")
end
function widget:Update()
    if not started and Spring.DiffTimers(Spring.GetTimer(), timer) > 2 then
        started = true
        Spring.SendCommands("forcestart")
    end
end
local function camera()
    if not unit then return end
    local x, y, z = Spring.GetUnitPosition(unit)
    if x then
        Spring.SetCameraTarget(x, y + 12, z, 0)
    end
end
function widget:GameFrame(frame)
    if frame > 5 and not selected then
        local units = Spring.GetTeamUnits(Spring.GetMyTeamID())
        unit = units and units[1]
        if not unit then return end
        selected = true
        x0, _, z0 = Spring.GetUnitPosition(unit)
        Spring.SelectUnitArray({unit})
        local pieces = Spring.GetUnitPieceMap(unit) or {}
        local count = 0
        for _ in pairs(pieces) do count = count + 1 end
        Spring.Echo("[MBT_SMOKE] selected pieces=" .. count)
        Spring.Echo("[MBT_SMOKE] expected_unit=" .. tostring(
            Spring.GetUnitDefID(unit) == UnitDefNames[__EXPECTED_UNIT__].id))
        for _, name in ipairs({__PIECE_LIST__}) do
            Spring.Echo("[MBT_SMOKE] piece " .. name .. "=" .. tostring(pieces[name]))
        end
        Spring.SendCommands({"cheat", "globallos", "hideinterface 1", "viewta"})
        Spring.SetCameraState({mode=1, height=200, angle=1.0, flipped=1}, 0)
        camera()
    end
    if selected and frame % 5 == 0 then camera() end
    if selected and frame % 120 == 0 then
        local x,y,z = Spring.GetUnitPosition(unit)
        Spring.Echo("[MBT_SMOKE] position=" .. tostring(x) .. "," .. tostring(y) .. "," .. tostring(z))
        if Spring.GetUnitWeaponState then
            Spring.Echo("[MBT_SMOKE] reload=" .. tostring(Spring.GetUnitWeaponState(unit, 1, "reloadState")))
            local angleGood = Spring.GetUnitWeaponState(unit, 1)
            local target = enemy or (Spring.GetTeamUnits(1) or {})[1]
            Spring.Echo("[MBT_SMOKE] weapon angle=" .. tostring(angleGood)
                .. " canfire=" .. tostring(Spring.GetUnitWeaponCanFire(unit, 1))
                .. " ignoreangle=" .. tostring(Spring.GetUnitWeaponCanFire(unit, 1, true))
                .. " ignoredir=" .. tostring(Spring.GetUnitWeaponCanFire(unit, 1, false, false, true)))
            if target then
                Spring.Echo("[MBT_SMOKE] target=" .. tostring(target)
                    .. " valid=" .. tostring(Spring.GetUnitWeaponTestTarget(unit, 1, target))
                    .. " range=" .. tostring(Spring.GetUnitWeaponTestRange(unit, 1, target))
                    .. " line=" .. tostring(Spring.GetUnitWeaponHaveFreeLineOfFire(unit, 1, target)))
                local tx,ty,tz,mx,my,mz,ax,ay,az = Spring.GetUnitPosition(target, true, true)
                local pm = Spring.GetUnitPieceMap(unit)
                local sx,sy,sz = Spring.GetUnitPiecePosDir(unit, pm.Gun)
                Spring.Echo("[MBT_SMOKE] enemy base=" .. tx .. "," .. ty .. "," .. tz
                    .. " mid=" .. mx .. "," .. my .. "," .. mz .. " aim=" .. ax .. "," .. ay .. "," .. az)
                Spring.Echo("[MBT_SMOKE] origin=" .. sx .. "," .. sy .. "," .. sz
                    .. " source_up=" .. tostring(Spring.GetUnitWeaponHaveFreeLineOfFire(unit, 1, sx, sy+64, sz, target))
                    .. " target_up=" .. tostring(Spring.GetUnitWeaponHaveFreeLineOfFire(unit, 1, sx, sy, sz, ax, ay+64, az))
                    .. " ignoreall=" .. tostring(Spring.GetUnitWeaponCanFire(unit, 1, true, true, true)))
            end
        end
        local pieces = Spring.GetUnitPieceMap(unit)
        if pieces and pieces.Flare then
            local px,py,pz,dx,dy,dz = Spring.GetUnitPiecePosDir(unit, pieces.Flare)
            Spring.Echo("[MBT_SMOKE] muzzle=" .. tostring(px) .. "," .. tostring(py) .. "," .. tostring(pz)
                .. " direction=" .. tostring(dx) .. "," .. tostring(dy) .. "," .. tostring(dz))
        end
    end
    if selected and frame >= 60 and not shots[1] then
        shots[1] = true
        camera()
        Spring.SendCommands("screenshot png")
        Spring.Echo("[MBT_SMOKE] screenshot stationary")
    end
    if selected and frame >= 90 and not moved then
        moved = true
        Spring.GiveOrderToUnit(unit, CMD.MOVE, {x0 + 120, Spring.GetGroundHeight(x0 + 120, z0 + 40), z0 + 40}, {})
        Spring.Echo("[MBT_SMOKE] move_order")
    end
    if selected and frame >= 180 and not shots[2] then
        shots[2] = true
        local x, _, z = Spring.GetUnitPosition(unit)
        Spring.Echo("[MBT_SMOKE] moved_distance=" .. math.sqrt((x-x0)^2 + (z-z0)^2))
        camera()
        Spring.SendCommands("screenshot png")
    end
    if selected and frame >= 240 and not attacked then
        attacked = true
        local enemies = Spring.GetTeamUnits(1)
        enemy = enemies and enemies[1]
        if enemy then
            Spring.GiveOrderToUnit(unit, CMD.ATTACK, {enemy}, {})
            Spring.Echo("[MBT_SMOKE] attack_order")
        end
    end
    if selected and frame >= 420 and not shots[3] then
        shots[3] = true
        camera()
        Spring.SendCommands("screenshot png")
    end
    if frame >= 540 and not finished then
        finished = true
        Spring.Echo("[MBT_SMOKE] complete")
        Spring.SendCommands("quitforce")
    end
end
function widget:UnitDamaged(id, defID, teamID, damage)
    if id == unit or id == enemy then
        Spring.Echo("[MBT_SMOKE] damage=" .. tostring(damage))
    end
end
'''


def run_client(engine, output, startscript, timeout, safe_mode=False):
    """Launch only our client process; all writable state stays in output."""
    config = output / "springsettings.cfg"
    config.write_text("Fullscreen = 0\nXResolutionWindowed = 1280\nYResolutionWindowed = 800\nWindowPosX = 40\nWindowPosY = 40\nVSync = 1\nShadows = 1\nShadowMapSize = 2048\n", encoding="utf-8")
    command = [str(engine / "spring.exe"), "--isolation", "--isolation-dir", str(engine),
               "--write-dir", str(output), "--config", str(config), "--window", "--only-local",
               str(startscript)]
    if safe_mode:
        command.insert(-1, "--safemode")
    print("Output directory:", output, flush=True)
    with (output / "console.txt").open("w", encoding="utf-8") as console:
        process = subprocess.Popen(command, cwd=engine, stdout=console, stderr=subprocess.STDOUT)
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return -1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=100)
    parser.add_argument("--model", choices=("ztz99a", "m1a1"), default="ztz99a")
    parser.add_argument("--expect-widget-errors", action="store_true")
    parser.add_argument("--safe-mode", action="store_true", help="Use isolated conservative rendering settings")
    args = parser.parse_args()
    game = pathlib.Path(__file__).resolve().parents[1]
    engine = game.parents[1]
    unit_name = "mbt" if args.model == "ztz99a" else "m1a1"
    manifest = json.loads((game / "tools" / "previews" / f"{args.model}_manifest.json").read_text(encoding="utf-8"))
    expected_pieces = len(manifest["pieces"])
    rig = manifest["track"]
    required_pieces = ["Base", "Turret", "Gun", "Flare", "WheelL1", f"WheelR{rig.get('wheelCount', 6)}",
                       "TrackL01", f"TrackR{rig['linkCount']:02d}", "IdlerLFront", "IdlerRRear"]
    probe = PROBE.replace("__PIECE_LIST__", ", ".join(json.dumps(name) for name in required_pieces))
    probe = probe.replace("__EXPECTED_UNIT__", json.dumps(unit_name))
    output = pathlib.Path(tempfile.mkdtemp(prefix=f"mygame-{args.model}-smoke-"))
    widgets = output / "LuaUI" / "Widgets"
    widgets.mkdir(parents=True)
    (widgets / "zz_mygame_smoke.lua").write_text(probe, encoding="utf-8")
    # Keep the shipped sandbox at a safe viewing distance. The smoke test uses
    # a closer target on the same patch, rather than shooting across a ridge.
    script_name = "mbt_test.txt" if args.model == "ztz99a" else "m1a1_test.txt"
    startscript = output / script_name
    startscript.write_text((game / "tools" / script_name).read_text(encoding="utf-8")
                           .replace("StartPosX=2224;", "StartPosX=1836;"), encoding="utf-8")
    code = run_client(engine, output, startscript, args.timeout, safe_mode=args.safe_mode)
    log_path = output / "infolog.txt"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    widget_errors = [line for line in log.splitlines()
                     if ("gui_center_n_select.lua" in line or "map_startbox.lua" in line)
                     and ("error" in line.lower() or "nil" in line)]
    failures = [line for line in log.splitlines()
                if re.search(r"error|failed|traceback", line, re.I)
                and re.search(r"ZTZ99|m1a1|mbtscript|track_animation|track_motion|MBT\.glb|MBT_SMOKE|NullAI", line, re.I)]
    signals = [line for line in log.splitlines() if "[MBT_SMOKE]" in line]
    moved = [float(value) for value in re.findall(r"\[MBT_SMOKE\] moved_distance=([0-9.eE+-]+)", log)]
    reloads = [float(value) for value in re.findall(r"\[MBT_SMOKE\] reload=([0-9.eE+-]+)", log)]
    damage = [float(value) for value in re.findall(r"\[MBT_SMOKE\] damage=([0-9.eE+-]+)", log)]
    checks = {"unit_type": "[MBT_SMOKE] expected_unit=true" in log,
              "moved": bool(moved and max(moved) > 10),
              "attack_order": "[MBT_SMOKE] attack_order" in log,
              "weapon_fired": bool(reloads and max(reloads) > 0),
              "damage_observed": bool(damage and max(damage) > 0),
              "piece_interface": f"[MBT_SMOKE] selected pieces={expected_pieces}" in log and "=nil" not in "\n".join(signals)}
    report = {"exit_code": code, "output": str(output), "model": args.model, "safe_mode": args.safe_mode, "widget_errors": widget_errors,
              "asset_errors": failures, "signals": signals, "checks": checks,
              "screenshots": [str(p) for p in output.glob("screenshots/*")],
              "complete": "[MBT_SMOKE] complete" in log}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    if args.expect_widget_errors:
        return 0 if len(widget_errors) >= 2 else 1
    return 0 if (code == 0 and report["complete"] and all(checks.values())
                 and len(report["screenshots"]) >= 3 and not widget_errors and not failures) else 1


if __name__ == "__main__":
    raise SystemExit(main())
