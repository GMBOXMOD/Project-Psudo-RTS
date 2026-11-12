"""Native Vehicle Factory checks in a new, local-only Recoil client.

The installed game and other clients are never changed. Runtime assets are
snapshotted into a dependent game before launch. Default runs load the installed
Factory definition byte-for-byte; only explicit historical --asset-snapshot runs
use the candidate wrapper. No product is spawned, teleported, MoveCtrl'd, or
given fabricated progress. Full mode uses normal orders, resource starvation
and a temporary WAIT order to exercise recovery without changing build rates.

Examples (from any directory):
    python -I -B D:/Recoil/games/MyGame.sdd/tools/smoke_vehicle_factory.py --mode quick

report.json is machine-checked evidence, not a visual/style approval. Screenshots
must also be opened by the reviewer. This flat fixture says nothing about slopes
or M1A1's unrestricted turret/elevation envelope.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import time

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from smoke_mbt import run_client

PREFIX = "[VF_SMOKE] "
CATALOGUE = ("spider", "stumpy", "flare", "duron", "scout", "m1a1")
BUILD_TIMES = dict(zip(CATALOGUE, (110, 100, 145, 185, 260, 600)))
NATIVE_NAMES = {"stumpy": "Stumpy", "flare": "Flare", "duron": "Duron"}
PRODUCT_CHECKS = ("native_product", "real_progress", "finished", "door_clear", "yard_clear", "rally", "geometry_clear")
FACTORY_CHECKS = ("interface", "collision_size", "closed_initial", "door_wait", "gate_release",
                  "work_progress", "stop", "queue_exact")
QUICK_CHECKS = {"fixture_flat", "unchanged_economy"} | {
    f"f0_factory_00_{suffix}" for suffix in FACTORY_CHECKS
} | {f"f0_spider_01_{suffix}" for suffix in PRODUCT_CHECKS}
QUICK_SHOTS = ("f0_factory_00_idle", "f0_spider_01_production", "f0_spider_01_rally")
FULL_PRODUCTS = [(f"f{facing}", name, index) for facing in range(4)
                 for index, name in enumerate(CATALOGUE, 1)] + [
    ("f0", "spider", 7), ("f0", "spider", 8), ("b0", "spider", 1)]
FULL_CHECKS = {"fixture_flat", "unchanged_economy", "collision_reference", "neighbor_placement",
               "resource_stall", "resource_recovery", "exit_obstruction", "exit_recovery",
               "spider_build_factory", "rally_directions"} | {
    f"{label}_factory_00_{suffix}" for label in ("f0", "f1", "f2", "f3", "b0") for suffix in FACTORY_CHECKS
} | {f"{label}_{name}_{index:02d}_{suffix}" for label, name, index in FULL_PRODUCTS for suffix in PRODUCT_CHECKS}
FULL_SHOTS = ("f0_factory_00_idle", "f0_spider_01_production", "factory_under_construction",
              "f1_scout_05_stalled", "f0_m1a1_06_production", "f1_m1a1_06_production",
              "f2_m1a1_06_production", "f3_m1a1_06_production", "f0_spider_08_blocked",
              "b0_spider_01_production", "base_final")

# Test-only rounds establish the actual collision-volume reference point. They
# do not change any gameplay weapon, and are fired before production starts.
PROBE_WEAPON = '''return {vf_collision_probe={
    name="Factory test boundary probe", weaponType="LaserCannon", range=1000,
    weaponVelocity=360, duration=0.1, thickness=0.05, coreThickness=0.05, areaOfEffect=0,
    collideFriendly=true, collideNeutral=true, avoidFriendly=false,
    noSelfDamage=true, impulseFactor=0, craterMult=0, craterBoost=0,
    explosionGenerator="", damage={default=1},
}}
'''

FACTORY_WRAPPER = '''-- Test-only wrapper; the original definition is an immutable snapshot.
local defs = VFS.Include("vehicle_factory_test_original.lua")
local def = assert(defs.factory)
local data = VFS.Include("scripts/vehicle_factory_data.lua")
local function set(name, value)
    local remove = {}
    for key in pairs(def) do
        if type(key) == "string" and key:lower() == name then remove[#remove+1] = key end
    end
    for _, key in ipairs(remove) do def[key] = nil end
    def[name] = value
end
set("objectname", "vehicle_factory.s3o")
set("script", "vehicle_factoryscript.lua")
set("buildpic", "vehicle_factory.png")
set("yardmap", table.concat(data.yardMapCandidate.rows, " "))
set("collisionvolumescales", "192 83.5 156")
set("collisionvolumeoffsets", "0 0 0")
set("collisionvolumetype", "box")
return defs
'''


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lua(value) -> str:
    """Encode only the JSON-shaped fixture data; never execute source Lua."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("Non-finite fixture value")
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "{" + ",".join(lua(item) for item in value) + "}"
    if isinstance(value, dict):
        return "{" + ",".join("[" + lua(key) + "]=" + lua(item) for key, item in value.items()) + "}"
    raise TypeError(type(value))


def native_piece_bounds(path: Path, include_vertices=False) -> dict:
    """Read local S3O vertices. Eight corners contain every vertex of a piece.

    The gadget transforms these boxes using LIVE piece matrices, including legs,
    tracks and the gun. A whole-product extent is conservative, not a centre-only
    test or an assertion about unsampled poses. Empty legacy locators are allowed.
    """
    data = path.read_bytes()
    if len(data) < 52:
        raise ValueError(f"Truncated S3O: {path}")
    header = struct.unpack_from("<12si5f4i", data)
    if header[:2] != (b"Spring unit\0", 0):
        raise ValueError(f"Invalid S3O: {path}")
    pieces, visited, names = [], set(), set()

    def region(offset, count, size):
        if offset < 0 or count < 0 or offset + count * size > len(data) or (count and offset < 52):
            raise ValueError(f"S3O range outside file: {path}")

    def text(offset):
        region(offset, 1, 1)
        end = data.find(b"\0", offset)
        if end < 0:
            raise ValueError(f"Unterminated S3O string: {path}")
        return data[offset:end].decode("utf-8")

    def visit(offset):
        region(offset, 1, 52)
        if offset in visited:
            raise ValueError(f"Cyclic S3O piece: {path}")
        visited.add(offset)
        p = struct.unpack_from("<10i3f", data, offset)
        name, children, child_table, count, vertices = p[:5]
        name = text(name)
        if name in names or not name:
            raise ValueError(f"Duplicate S3O piece name: {path}")
        names.add(name)
        region(vertices, count, 32)
        region(child_table, children, 4)
        points = [struct.unpack_from("<3f", data, vertices + i * 32) for i in range(count)]
        if not all(math.isfinite(n) for point in points for n in point):
            raise ValueError(f"Non-finite S3O vertex: {path}")
        if points:
            lo = [min(point[i] for point in points) for i in range(3)]
            hi = [max(point[i] for point in points) for i in range(3)]
            piece = {"name": name, "corners": list(itertools.product(*zip(lo, hi)))}
            if include_vertices:
                piece["vertices"] = points
            pieces.append(piece)
        for i in range(children):
            visit(struct.unpack_from("<i", data, child_table + i * 4)[0])

    visit(header[-4])
    return {"sha256": hashlib.sha256(data).hexdigest(), "midpoint": list(header[4:7]),
            "radius": header[2], "height": header[3], "pieceCount": len(names), "pieces": pieces}


def expected(mode: str):
    if mode == "quick":
        return set(QUICK_CHECKS), tuple(QUICK_SHOTS)
    if mode == "full":
        return set(FULL_CHECKS), tuple(FULL_SHOTS)
    raise ValueError("Unknown native scenario: " + mode)


def factory_solids(bounds: dict, asset_manifest: dict) -> list[dict]:
    """Recompute each fixed component box from the actual loaded S3O vertices."""
    base = next(piece for piece in bounds["pieces"] if piece["name"] == "Base")
    solids = []
    for component in asset_manifest["static_components"]:
        start, count = component["vertex_start"], component["vertex_count"]
        points = base["vertices"][start:start + count]
        if not points or len(points) != count:
            raise ValueError("Component ranges do not match the loaded factory")
        lo = [min(p[i] for p in points) for i in range(3)]
        hi = [max(p[i] for p in points) for i in range(3)]
        if any(abs(a - b) > 0.0001 for actual, declared in ((lo, component["min"]), (hi, component["max"]))
               for a, b in zip(actual, declared)):
            raise ValueError("Stale factory component manifest: " + component["name"])
        # Ground contact may intersect the 0.12-high painted drive surface;
        # every raised pad, wall, door and machine remains in the check.
        if component["role"] != "drive_floor":
            solids.append({"name": component["name"], "piece": "Base", "min": lo, "max": hi})
    for piece in bounds["pieces"]:
        if piece["name"] != "Base":
            solids.append({"name": piece["name"], "piece": piece["name"],
                           "min": [min(p[i] for p in piece["corners"]) for i in range(3)],
                           "max": [max(p[i] for p in piece["corners"]) for i in range(3)]})
        del piece["vertices"]
    return solids


def prepare(output: Path, mode: str, speed: float, max_frames: int, asset_snapshot: Path | None = None):
    game = output / "games" / "MyGameVehicleFactorySmoke.sdd"
    game.mkdir(parents=True)
    source_hashes, source_locations = {}, {}
    installed_unitdefs = {path.relative_to(ROOT).as_posix(): sha256(path)
                         for path in sorted((ROOT / "Units").rglob("*")) if path.is_file()}
    # All runtime assets/UnitDefs are copied byte-for-byte, not just the factory.
    # Parent-side later edits therefore cannot change this client's loaded input.
    for directory in ("Units", "Scripts", "Objects3d", "UnitTextures", "UnitPics", "Weapons", "GameData"):
        for source in sorted((ROOT / directory).rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(ROOT)
            if asset_snapshot and (asset_snapshot / relative).is_file():
                source = asset_snapshot / relative
            destination = game / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            before = source.stat()
            content = source.read_bytes()
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError(f"Input changed during snapshot: {source}")
            destination.write_bytes(content)
            source_hashes[relative.as_posix()] = hashlib.sha256(content).hexdigest()
            source_locations[relative.as_posix()] = str(source)
    original = game / "Units" / "Factory.lua"
    shutil.copy2(original, game / "vehicle_factory_test_original.lua")
    if asset_snapshot:
        if mode != "quick":
            raise ValueError("Historical candidate overrides cannot certify installed/full integration")
        original.write_text(FACTORY_WRAPPER, encoding="utf-8")
    if mode == "full":
        weapons = game / "Weapons"
        weapons.mkdir(parents=True, exist_ok=True)
        (weapons / "vf_collision_probe.lua").write_text(PROBE_WEAPON, encoding="utf-8")
    (game / "ModInfo.lua").write_text(
        'return {name="MyGame Vehicle Factory Smoke", shortname="MGVF", '
        'game="MyGame Vehicle Factory Smoke", shortgame="MGVF", version="v1", '
        'modtype=1, depend={"My Game v0.1"}}\n', encoding="utf-8")
    gadgets = game / "LuaRules" / "Gadgets"
    gadgets.mkdir(parents=True)
    # Isolated fixture only: no starter units, periodic free income or game-end.
    # In particular periodic template income must not invalidate the stall test.
    for name in ("game_spawn.lua", "my_first_gadget.lua", "game_end.lua"):
        (gadgets / name).write_text("-- Disabled ONLY in the native test fixture.\nreturn false\n", encoding="utf-8")
    shutil.copy2(TOOLS / "vehicle_factory_test_gadget.lua", gadgets / "test_vehicle_factory.lua")
    widgets = output / "LuaUI" / "Widgets"
    widgets.mkdir(parents=True)
    shutil.copy2(TOOLS / "vehicle_factory_test_widget.lua", widgets / "zz_vehicle_factory_smoke.lua")
    bounds = {name: native_piece_bounds(game / "Objects3d" / (NATIVE_NAMES.get(name, name) + ".s3o"))
              for name in CATALOGUE}
    bounds["factory"] = native_piece_bounds(game / "Objects3d" / "vehicle_factory.s3o", include_vertices=True)
    manifest_relative = Path("tools/previews/vehicle_factory/manifest.json")
    manifest_source = ((asset_snapshot / manifest_relative) if asset_snapshot and (asset_snapshot / manifest_relative).is_file()
                       else ROOT / manifest_relative)
    manifest_content = manifest_source.read_bytes()
    source_hashes[manifest_relative.as_posix()] = hashlib.sha256(manifest_content).hexdigest()
    source_locations[manifest_relative.as_posix()] = str(manifest_source)
    (game / "vehicle_factory_asset_manifest.json").write_bytes(manifest_content)
    solids = factory_solids(bounds["factory"], json.loads(manifest_content))
    required, shots = expected(mode)
    config = {"mode": mode, "speed": speed, "maxFrames": max_frames,
              "requiredChecks": sorted(required), "requiredShots": shots,
              "catalogue": CATALOGUE, "buildTimes": BUILD_TIMES, "bounds": bounds,
              "solids": solids, "installedDefinition": not bool(asset_snapshot)}
    (game / "vehicle_factory_test_config.lua").write_text("return " + lua(config) + "\n", encoding="utf-8")
    script = f'''[GAME]
{{
    GameType=MyGame Vehicle Factory Smoke v1;
    MapName=Low Poly Plains v2;
    IsHost=1;
    MyPlayerName=FactoryTester;
    StartPosType=3;
    NumPlayers=1;
    NumUsers=2;
    NumTeams=2;
    NumAllyTeams=1;
    NumSkirmishAIs=1;
    [PLAYER0] {{ Name=FactoryTester; Team=0; Spectator=0; }}
    [AI0] {{ Name=FixtureAlly; ShortName=NullAI; Version=0.1; Host=0; Team=1; }}
    [TEAM0] {{ TeamLeader=0; AllyTeam=0; Side=Abrams; RGBColor=0.20 0.65 0.95; StartPosX=1536; StartPosZ=1536; }}
    [TEAM1] {{ TeamLeader=0; AllyTeam=0; Side=Beefys; RGBColor=0.90 0.25 0.15; StartPosX=2224; StartPosZ=1536; }}
    [ALLYTEAM0] {{ NumAllies=0; }}
    [MODOPTIONS] {{ TeamDeathMode=none; }}
}}
'''
    startscript = output / "vehicle_factory_test.txt"
    startscript.write_text(script, encoding="utf-8")
    loaded_hashes = {path.relative_to(game).as_posix(): sha256(path)
                     for path in sorted(game.rglob("*")) if path.is_file()}
    manifest = {"mode": mode, "created_unix": time.time(), "source_game": str(ROOT),
                "dependent_game": str(game), "engine": str(ROOT.parents[1] / "spring.exe"),
                "engine_sha256": sha256(ROOT.parents[1] / "spring.exe"),
                "source_sha256": source_hashes, "source_locations": source_locations,
                "installed_unitdefs_at_start": installed_unitdefs,
                "loaded_sha256": loaded_hashes,
                "widget_sha256": sha256(widgets / "zz_vehicle_factory_smoke.lua"),
                "factory_definition_byte_identical": sha256(original) == source_hashes["Units/Factory.lua"],
                "fixture_overrides": (["historical Factory candidate wrapper"] if asset_snapshot else []) + [
                    "flat test patch", "disabled starter/income/game-end gadgets", "allied two-team fixture"] +
                    (["boundary probe weapon", "temporary resource starvation", "temporary product WAIT order"] if mode == "full" else []),
                "collision_offsets": {"configured": [0, 0, 0], "reference_basis": "full-mode native projectile boundary probes"},
                "requested_speed": speed, "max_frames": max_frames, "safe_mode": True,
                "scope": "normal production/exit poses; flat ground only; unrestricted M1A1 gun poses excluded and separately diagnosed"}
    (output / "asset_snapshot.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return startscript, manifest


# Only precisely identified, existing template/map/UI diagnostics are tolerated.
# Unknown errors and every new factory/script/graphics error fail the run.
LEGACY_ERRORS = (
    r"Couldn't find WeaponDef NOWEAPON and (?:explodeAs|selfDestructAs) for (?:commander|constructor|duron|energyreactor|extractor|factory|flare|llt|mbt|stumpy) is missing!",
    r'\[GetFeatureDef\] could not find FeatureDef "allpinesb_[^"]+"',
    r"gui_center_n_select\.lua", r"map_startbox\.lua",
    r"Failed to load: BlockUserWidgets\.lua",
    r"unit_healthbars\.lua.*attempt to perform arithmetic on local 'empHP'",
    r"Removed widget: <TutorialGame \| HealthBars>",
)
GRAPHICS_ERROR = re.compile(r"graphics card driver|hang detected|out of (?:video )?memory|GL_INVALID|GL_OUT_OF_MEMORY|(?:shader|framebuffer).*(?:error|failed|incomplete)", re.I)


def validate_product_evidence(events: list[dict], required: set[str]) -> list[str]:
    """Cross-check claims against IDs, progress, native callbacks and extents."""
    violations = []
    keys = {name.removesuffix("_native_product") for name in required if name.endswith("_native_product")}
    identities = set()
    terminal_types = ("product_created", "product_finished", "unit_finished_callin", "unit_from_factory",
                      "door_clear", "yard_clear", "rally_arrival")
    all_created = [e for e in events if e["event"] == "product_created"]
    if Counter(e.get("key") for e in all_created) != Counter({key: 1 for key in keys}):
        violations.append("Missing, duplicate or unexpected native product identities")
    for key in sorted(keys):
        group = [e for e in events if e.get("key") == key]
        by_type = {kind: [e for e in group if e["event"] == kind] for kind in ("build_order",) + terminal_types}
        if any(len(records) != 1 for records in by_type.values()):
            violations.append(f"Incomplete or repeated lifecycle for {key}")
            continue
        one = {kind: records[0] for kind, records in by_type.items()}
        order, created, finished = one["build_order"], one["product_created"], one["product_finished"]
        unit = created.get("id")
        if not isinstance(unit, (int, float)) or isinstance(unit, bool) or unit < 0 or unit % 1 or unit in identities:
            violations.append(f"Invalid/shared actual ID for {key}")
        identities.add(unit)
        if any(one[kind].get("id") != unit for kind in terminal_types):
            violations.append(f"Product ID changed in {key}")
        if order.get("options") != "none" or created.get("factory") != order.get("factory"):
            violations.append(f"Non-native queue/builder linkage for {key}")
        if created.get("role") != "native_factory_product" or not 0 <= created.get("progress", 2) < 0.2:
            violations.append(f"Product was not observed from real creation: {key}")
        entry = created.get("entryState", {})
        if entry.get("open") is not True or entry.get("stance") != 1 or entry.get("yard") != 1:
            violations.append(f"Native creation happened before the doors/stance/yard were ready: {key}")
        if one["unit_from_factory"].get("factory") != created.get("factory"):
            violations.append(f"UnitFromFactory linkage mismatch: {key}")
        if any(one[kind].get("progress") != 1 for kind in terminal_types if kind != "product_created"):
            violations.append(f"Incomplete product certified as finished/exited: {key}")
        if not (order["frame"] <= created["frame"] < finished["frame"] <= one["door_clear"]["frame"]
                <= one["yard_clear"]["frame"] <= one["rally_arrival"]["frame"]):
            violations.append(f"Impossible/premature lifecycle order: {key}")
        name = order.get("name")
        minimum = BUILD_TIMES.get(name, math.inf) / 10 * 30 - 30
        if finished["frame"] - created["frame"] < minimum:
            violations.append(f"Product finished faster than original build rate: {key}")
        if not any(e["event"] == "product_sample" and e.get("id") == unit and 0 < e.get("progress", 2) < 1 for e in group):
            violations.append(f"No intermediate real progress sample: {key}")
        for kind, limit in (("door_clear", 54.5), ("yard_clear", 81)):
            envelope = one[kind].get("envelope", {})
            low = envelope.get("min", [])
            if (len(low) != 3 or low[2] <= limit or envelope.get("corners", 0) <= 0
                    or envelope.get("matrixError", 1) >= 0.01):
                violations.append(f"Whole native product envelope not clear at {kind}: {key}")
        if one["rally_arrival"].get("distance", math.inf) > 32:
            violations.append(f"Rally not reached: {key}")
        for shot in (e for e in events if e["event"] == "screenshot" and e.get("stage", "").startswith(key+"_")):
            if shot.get("unit") != unit:
                violations.append(f"Screenshot refers to another product: {shot.get('stage')}")
            if shot.get("stage", "").endswith("_production") and not 0 < shot.get("progress", 2) < 1:
                violations.append(f"Production screenshot missed construction: {shot.get('stage')}")
            if shot.get("stage", "").endswith("_rally") and (shot.get("progress") != 1 or shot["frame"] < one["rally_arrival"]["frame"]):
                violations.append(f"Premature rally screenshot: {shot.get('stage')}")
    return violations


def validate_scenario_evidence(events: list[dict], mode: str) -> list[str]:
    violations = []
    if any(e["event"] == "geometry_hit" for e in events):
        violations.append("A live product-piece box overlapped delivered factory geometry")
    for record in (e for e in events if e["event"] == "check" and e.get("name", "").endswith("_geometry_clear")):
        detail = record.get("detail") or {}
        if detail.get("samples", 0) < 10 or detail.get("hits") != 0:
            violations.append("Insufficient/failed native clearance evidence: " + record["name"])
    if mode != "full":
        return violations
    ready = [e for e in events if e["event"] == "ready"]
    if len(ready) != 1 or ready[0].get("installedDefinition") is not True:
        violations.append("Full mode did not load the installed Factory definition")
    fixtures = [e for e in events if e["event"] == "fixture_unit" and e.get("label")]
    if Counter(e.get("label") for e in fixtures) != Counter({key: 1 for key in ("f0", "f1", "f2", "f3", "b0")}):
        violations.append("Missing or repeated factory/facing fixture")
    for record in fixtures:
        if record["label"].startswith("f") and record.get("facing") != int(record["label"][1:]):
            violations.append("Factory orientation differs from its checked label")
    probe_results = [e for e in events if e["event"] == "collision_probe_result"]
    probe_shots = [e for e in events if e["event"] == "collision_probe_shot"]
    probe_names = {"roof_inside", "roof_outside", "side_inside", "side_outside", "front_inside", "front_outside",
                   "rotated_side_inside", "rotated_side_outside", "reversed_front_inside", "reversed_front_outside",
                   "rotated_roof_inside", "rotated_roof_outside"}
    for records in (probe_shots, probe_results):
        if Counter(e.get("name") for e in records) != Counter({name: 1 for name in probe_names}):
            violations.append("Collision boundary probe lifecycle is incomplete/repeated")
    for record in probe_results:
        hits = [e for e in events if e["event"] == "collision_probe_hit" and e.get("projectile") == record.get("projectile")]
        observed = any(e.get("id") == record.get("factory") for e in hits)
        if record.get("actualHit") != observed or observed != record.get("expectedHit"):
            violations.append("Native collision boundary mismatch: " + str(record.get("name")))
    lifecycle = {kind: [e for e in events if e["event"] == kind] for kind in (
        "factory_construction_order", "factory_construction_created", "factory_construction_finished",
        "resource_stall_start", "resource_stall_release", "resource_stall_recovered",
        "exit_obstruction_start", "exit_obstruction_release")}
    for kind, records in lifecycle.items():
        if len(records) != 1:
            violations.append("Missing or repeated full-scenario event: " + kind)
    if all(len(v) == 1 for v in lifecycle.values()):
        one = {kind: records[0] for kind, records in lifecycle.items()}
        order, created, finished = (one["factory_construction_" + k] for k in ("order", "created", "finished"))
        if (created.get("builder") != order.get("builder") or finished.get("id") != created.get("id")
                or created.get("progress", 1) >= 0.01 or finished.get("progress") != 1
                or finished["frame"] - created["frame"] < 620 / 6 * 30 - 30
                or not any(e["event"] == "factory_construction_sample" and e.get("id") == created.get("id")
                           and 0 < e.get("progress", 2) < 1 for e in events)):
            violations.append("Engineer-built factory lacks real construction evidence")
        built = [e for e in fixtures if e["label"] == "b0"]
        if len(built) != 1 or built[0].get("id") != finished.get("id") or built[0].get("role") != "spider_built_completed_factory":
            violations.append("b0 was not the actual engineer-built factory")
        start, release, recovery = (one["resource_stall_" + k] for k in ("start", "release", "recovered"))
        if (not start.get("id") == release.get("id") == recovery.get("id")
                or release["frame"] - start["frame"] < 270 or recovery["frame"] <= release["frame"]
                or recovery.get("progress", 0) <= release.get("progress", 1) + 0.03):
            violations.append("Resource stall did not recover the same actual product")
        start, release = (one["exit_obstruction_" + k] for k in ("start", "release"))
        if (start.get("id") != release.get("id") or release["frame"] - start["frame"] < 300
                or start.get("command") != "WAIT" or release.get("command") != "MOVE"):
            violations.append("Exit obstruction/recovery lacks ordinary movement commands")
    return violations


def parse_report(log: str, mode: str, exit_code: int, screenshots=()):
    required, required_shots = expected(mode)
    events, violations, errors, legacy_errors, warnings = [], [], [], [], []
    lines = log.splitlines()
    for number, line in enumerate(lines, 1):
        if PREFIX in line:
            try:
                record = json.loads(line.split(PREFIX, 1)[1])
                if not isinstance(record, dict) or not isinstance(record.get("event"), str):
                    raise ValueError("event object required")
                record["log_line"] = number
                events.append(record)
            except (ValueError, TypeError) as error:
                violations.append(f"Malformed event at line {number}: {error}")
        if "Warning:" in line:
            warnings.append(line)
        if GRAPHICS_ERROR.search(line):
            errors.append(line)
        elif re.search(r"\b(?:error|failed|traceback)\b", line, re.I) and PREFIX not in line:
            context = "\n".join(lines[number - 1:number + 5])
            known_line = any(re.search(pattern, line, re.I) for pattern in LEGACY_ERRORS)
            # A generic Lua wrapper can refer to the following UI stack trace,
            # but proximity to an unrelated legacy error must never hide a new one.
            known_ui_wrapper = (bool(re.search(r"LuaUI.*(?:Error|Traceback)|Error.*LuaUI", line, re.I))
                                and bool(re.search(r"gui_center_n_select\.lua|map_startbox\.lua", context))
                                and not re.search(r"vehicle_factory|VF_SMOKE", context, re.I))
            if known_line or known_ui_wrapper:
                legacy_errors.append(line)
            else:
                errors.append(line)
    checks = [e for e in events if e["event"] == "check"]
    counts = Counter(e.get("name") for e in checks)
    if set(counts) != required:
        violations.append(f"Check names mismatch; missing={sorted(required-set(counts))}, unexpected={sorted(set(counts)-required)}")
    for name, count in counts.items():
        if count != 1:
            violations.append(f"Duplicate check {name}: {count}")
    check_values = {e.get("name"): e.get("passed") is True for e in checks}
    shots = [e for e in events if e["event"] == "screenshot"]
    shot_counts = Counter(e.get("stage") for e in shots)
    if set(shot_counts) != set(required_shots) or any(n != 1 for n in shot_counts.values()):
        violations.append(f"Screenshot phases mismatch: {dict(shot_counts)}")
    if len(screenshots) != len(shots):
        violations.append(f"Screenshot file/event mismatch: {len(screenshots)} files / {len(shots)} events")
    ends = [e for e in events if e["event"] == "scenario_end"]
    client_ends = [e for e in events if e["event"] == "client_end"]
    if len(ends) != 1 or ends[0].get("reason") != "finished":
        violations.append("Missing, duplicate or unfinished scenario_end")
    if len(client_ends) != 1:
        violations.append("Missing or duplicate client_end")
    if len(ends) == 1:
        if any(e["log_line"] > ends[0]["log_line"] for e in checks + shots):
            violations.append("Premature scenario_end before checks/screenshots")
        if len(client_ends) == 1 and client_ends[0]["log_line"] < ends[0]["log_line"]:
            violations.append("Premature client_end")
    errors.extend(e for e in events if e["event"] in ("error", "unexpected_product"))
    violations.extend(validate_product_evidence(events, required))
    violations.extend(validate_scenario_evidence(events, mode))
    passed = (exit_code == 0 and not violations and not errors and bool(check_values)
              and all(check_values.values()) and set(check_values) == required)
    return {"mode": mode, "exit_code": exit_code, "passed": passed,
            "checks": check_values, "violations": violations, "errors": errors,
            "legacy_template_ui_errors": legacy_errors, "warnings": warnings,
            "screenshots": shots, "events": events,
            "speed_samples": [e for e in events if e["event"] == "speed"],
            "scope": "Flat fixture; normal production/exit. Quick and full are separate. Not a G2/style approval."}


def collect(output: Path, mode: str, exit_code: int, manifest: dict):
    log_path = output / "infolog.txt"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    shots = sorted((output / "screenshots").glob("*.png"))
    report = parse_report(log, mode, exit_code, shots)
    report["output"] = str(output)
    report["asset_snapshot"] = str(output / "asset_snapshot.json")
    report["source_unitdefs_unchanged"] = all(
        sha256(ROOT / relative) == value
        for relative, value in manifest["installed_unitdefs_at_start"].items())
    snapshot = Path(manifest["dependent_game"])
    report["loaded_snapshot_unchanged"] = all(
        sha256(snapshot / relative) == value for relative, value in manifest["loaded_sha256"].items())
    if not report["source_unitdefs_unchanged"] or not report["loaded_snapshot_unchanged"]:
        report["passed"] = False
        report["violations"].append("Source UnitDefs or loaded snapshot changed during run")
    evidence = output / "evidence"
    evidence.mkdir(exist_ok=True)
    if len(shots) == len(report["screenshots"]):
        for raw, event in zip(shots, report["screenshots"]):
            stage = event.get("stage", "invalid")
            if not re.fullmatch(r"[a-z0-9_]+", stage):
                report["violations"].append("Invalid screenshot stage name")
                report["passed"] = False
                continue
            named = evidence / f"{mode}_{stage}.png"
            shutil.copy2(raw, named)
            event.update(raw_file=str(raw), file=str(named), sha256=sha256(raw), visual_review="NOT_RUN")
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mode", "passed", "exit_code", "output", "checks", "violations", "errors", "screenshots")}, indent=2), flush=True)
    print(f"Legacy template/UI errors (separate): {len(report['legacy_template_ui_errors'])}; full report: {output / 'report.json'}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("quick", "full"), default="quick")
    parser.add_argument("--timeout", type=int, default=360, help="Wall-clock limit; only our process is terminated")
    parser.add_argument("--speed", type=float, default=4, help="Playback factor cap, never a UnitDef build-speed change")
    parser.add_argument("--max-frames", type=int, help="Simulation-frame deadline (quick 3600; full 18000)")
    parser.add_argument("--safe-mode", action="store_true", default=True, help="Always enabled for this probe")
    parser.add_argument("--asset-snapshot", type=Path, help="Use frozen factory files where present; other game assets are copied from the installed game")
    args = parser.parse_args()
    if args.max_frames is None:
        args.max_frames = 3600 if args.mode == "quick" else 18000
    if not 1 <= args.speed <= 8 or args.max_frames < 900 or args.timeout < 30:
        parser.error("Use speed 1..8, at least 900 simulation frames, and timeout >=30")
    output = Path(tempfile.mkdtemp(prefix=f"mygame-vehicle-factory-{args.mode}-"))
    print("Preparing immutable native fixture:", output, flush=True)
    if args.asset_snapshot and not args.asset_snapshot.is_dir():
        parser.error("Asset snapshot directory does not exist")
    startscript, manifest = prepare(output, args.mode, args.speed, args.max_frames, args.asset_snapshot)
    code = run_client(ROOT.parents[1], output, startscript, args.timeout, safe_mode=True)
    report = collect(output, args.mode, code, manifest)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
