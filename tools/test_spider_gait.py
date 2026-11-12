"""Replay the SP-6 unit script with a deterministic Lua 5.1 scheduler.

These tests inspect real controller goals, not a Python reimplementation of the
walk cycle. Native interpolation and foot contact need the engine smoke test.
"""

import argparse
import json
import math
import pathlib
import random
import sys
import unittest
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--lua-path", type=pathlib.Path)
args, remaining = parser.parse_known_args()
if args.lua_path:
    sys.path.insert(0, str(args.lua_path.resolve()))
from lupa.lua51 import LuaRuntime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_spider as builder

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "Scripts"

HARNESS = r'''
world = {x=0,y=0,z=0,fx=0,fy=0,fz=1,frame=0}
Game = {gameSpeed=30}
UnitDefs = {[1]={}}
COB = {INBUILDSTANCE=5}
unitID, unitDefID = 7, 1
script = {}
local unitValues = {}
local rotations, translations, threads = {}, {}, {}
local running
metrics = {turns=0,moves=0}
function piece(name)
    assert(validPiece(name), "Unknown model piece: " .. name)
    return name
end
local function vector(store, name)
    if not store[name] then store[name]={0,0,0} end
    return store[name]
end
local function resume(thread)
    local parent = running
    running = thread
    local ok, frames = coroutine.resume(thread.co)
    running = parent
    assert(ok, frames)
    thread.wake = world.frame + (frames or 1)
end
local us = {}
Spring = {
    UnitScript=us,
    GetUnitPosition=function() return world.x,world.y,world.z end,
    GetUnitDirection=function() return world.fx,world.fy,world.fz end,
    GetGameFrame=function() return world.frame end,
}
us.StartThread=function(fn, ...)
    local arguments={...}
    local thread={co=coroutine.create(function() fn(unpack(arguments)) end),
                  mask=running and running.mask or 0}
    threads[#threads+1]=thread
    resume(thread)
end
us.Sleep=function(ms)
    return coroutine.yield(math.max(1,math.ceil(ms*Game.gameSpeed/1000-0.000001)))
end
us.SetSignalMask=function(mask) running.mask=mask end
us.GetUnitValue=function(key) return unitValues[key] or 0 end
us.SetUnitValue=function(key,value)
    assert(key~=nil)
    unitValues[key]=value
end
us.Signal=function(mask)
    -- SP-6 uses a single signal bit, SIG_BUILD.
    for _, thread in ipairs(threads) do
        if thread.mask == mask and mask ~= 0 then thread.dead=true end
    end
end
us.Turn=function(name,axis,goal,speed)
    assert(axis==1 or axis==2 or axis==3, "Turn(): Bad axis")
    assert(goal==goal and math.abs(goal)<100)
    assert(speed==nil or (speed>=0 and speed<100000))
    vector(rotations,name)[axis]=goal
    metrics.turns=metrics.turns+1
end
us.Move=function(name,axis,goal,speed)
    assert(axis==1 or axis==2 or axis==3, "Move(): Bad axis")
    assert(goal==goal and math.abs(goal)<10000)
    assert(speed==nil or (speed>=0 and speed<100000))
    vector(translations,name)[axis]=goal
    metrics.moves=metrics.moves+1
end
function include(name)
    local chunk,err=loadstring(unitHeader .. readScript(name),name)
    assert(chunk,err)
    return chunk()
end
function callin(name, ...) us.StartThread(script[name], ...) end
function step(frame,x,y,z,fx,fy,fz)
    world={frame=frame,x=x,y=y,z=z,fx=fx,fy=fy,fz=fz}
    for i=1,#threads do
        local thread=threads[i]
        if not thread.dead and coroutine.status(thread.co)~="dead" and thread.wake<=frame then
            resume(thread)
        end
    end
end
function angles(name) return unpack(vector(rotations,piece(name))) end
function translation(name) return unpack(vector(translations,piece(name))) end
'''


class GaitHarness:
    def __init__(self, yaw=0.0):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.globals()
        with zipfile.ZipFile(ROOT.parents[1]/"base"/"springcontent.sdz") as archive:
            name = next(n for n in archive.namelist() if n.lower() == "gamedata/unit_script_header.lua")
            self.g.unitHeader = archive.read(name).decode("utf-8")
        self.g.readScript = lambda name: (SCRIPTS/name).read_text(encoding="utf-8")
        manifest = json.loads((ROOT/"tools"/"previews"/"spider_manifest.json").read_text(encoding="utf-8"))
        self.g.validPiece = lambda name: name in manifest["pieces"]
        self.lua.execute(HARNESS)
        self.data = self.g.include("spider_rig_data.lua")
        self.legs = [self.data.legs[i] for i in range(1, len(self.data.legs)+1)]
        self.g.include("spiderscript.lua")
        self.frame = 0
        self.x = self.y = self.z = 0.0
        self.yaw = yaw
        self.g.world.fx, self.g.world.fz = math.sin(yaw), math.cos(yaw)
        self.g.callin("Create")

    def step(self, forward=0, yaw=0, dy=0, frames=1):
        mid_heading = self.yaw + yaw*0.5
        self.x += math.sin(mid_heading)*forward
        self.z += math.cos(mid_heading)*forward
        self.y += dy
        self.yaw += yaw
        self.frame += frames
        self.g.step(self.frame, self.x, self.y, self.z,
                    math.sin(self.yaw), 0, math.cos(self.yaw))

    def advance(self, frames, forward=0, yaw=0):
        for _ in range(frames):
            self.step(forward=forward, yaw=yaw)

    def lifted(self):
        return {leg.knee for leg in self.legs if abs(self.g.angles(leg.knee)[2]) > 1e-6}

    def foot(self, leg, world=False):
        # The actual export is a yawing hip and a knee-local Z hinge. Use the
        # generator's contact point rather than inferring lift from phase names.
        hip = self.g.angles(leg.hip)[1]
        knee = self.g.angles(leg.knee)[2]
        fx, fy = builder.FOOT
        radius = builder.KNEE[0] + math.cos(knee)*fx - math.sin(knee)*fy
        x = leg.x + math.cos(hip)*radius
        y = builder.HIP_Y + builder.KNEE[1] + math.sin(knee)*fx + math.cos(knee)*fy
        z = builder.HIP_Z[int(leg.hip[-1])-1] - math.sin(hip)*radius
        if world:
            x, z = (self.x + math.cos(self.yaw)*x + math.sin(self.yaw)*z,
                    self.z - math.sin(self.yaw)*x + math.cos(self.yaw)*z)
            y += self.y
        return x, y, z


class SpiderGaitTests(unittest.TestCase):
    def test_uninterrupted_forward_keeps_alternating_tripods(self):
        rig = GaitHarness()
        for _ in range(72):
            rig.step(forward=1)
            self.assertLessEqual(len(rig.lifted()), 3)

    def test_one_stop_and_restart_keeps_tripod_support(self):
        rig = GaitHarness()
        rig.advance(6, forward=1)
        self.assertEqual(len(rig.lifted()), 3)
        rig.advance(20)
        self.assertEqual(rig.lifted(), set())
        for _ in range(6):
            rig.step(forward=1)
            self.assertLessEqual(len(rig.lifted()), 3,
                                 f"All six legs lifted after move-stop-move: {sorted(rig.lifted())}")

    def test_shortest_walk_pause_walk_repro(self):
        rig = GaitHarness()
        rig.advance(6, forward=1)
        rig.advance(2)
        rig.advance(4, forward=1)
        self.assertLessEqual(len(rig.lifted()), 3)

    def test_curved_walk_keeps_one_tripod_in_support(self):
        rig = GaitHarness()
        for _ in range(240):
            rig.step(forward=0.6, yaw=0.02)
            self.assertLessEqual(len(rig.lifted()), 3)

    def assert_stance_cancels_travel(self, forward):
        rig = GaitHarness()
        rig.advance(90, forward=forward)
        samples = 0
        for _ in range(90):
            before = {leg.knee: rig.foot(leg, world=True) for leg in rig.legs}
            lifted = rig.lifted()
            rig.step(forward=forward)
            for leg in rig.legs:
                if leg.knee not in lifted | rig.lifted():
                    samples += 1
                    delta = rig.foot(leg, world=True)[2] - before[leg.knee][2]
                    self.assertAlmostEqual(delta, 0, delta=0.05,
                                           msg=f"{leg.knee} slides along the direction of travel")
        self.assertGreater(samples, 100)

    def test_stance_feet_cancel_forward_travel(self):
        self.assert_stance_cancels_travel(0.5)

    def test_stance_feet_cancel_reverse_travel(self):
        self.assert_stance_cancels_travel(-0.5)

    def test_pivot_stance_counters_body_rotation(self):
        for yaw in (-0.015, 0.015):
            with self.subTest(yaw=yaw):
                rig = GaitHarness()
                rig.advance(90, yaw=yaw)
                samples = 0
                for _ in range(90):
                    before = {leg.knee: rig.foot(leg) for leg in rig.legs}
                    lifted = rig.lifted()
                    rig.step(yaw=yaw)
                    for leg in rig.legs:
                        if leg.knee not in lifted | rig.lifted():
                            samples += 1
                            dx = before[leg.knee][0]
                            dz = rig.foot(leg)[2] - before[leg.knee][2]
                            self.assertGreater(dz*yaw*dx, 0,
                                               f"{leg.knee} pushes with, not against, body rotation")
                self.assertGreater(samples, 100)

    def test_idle_does_not_submit_transforms(self):
        rig = GaitHarness()
        turns, moves = rig.g.metrics.turns, rig.g.metrics.moves
        rig.advance(300)
        self.assertEqual(rig.g.metrics.turns, turns)
        self.assertEqual(rig.g.metrics.moves, moves)

    def test_stop_lowers_swing_feet_without_moving_support_hips(self):
        rig = GaitHarness()
        rig.advance(6, forward=1)
        hips = {leg.hip: rig.g.angles(leg.hip) for leg in rig.legs}
        self.assertEqual(len(rig.lifted()), 3)
        rig.advance(20)
        self.assertEqual(rig.lifted(), set())
        for leg in rig.legs:
            self.assertEqual(rig.g.angles(leg.hip), hips[leg.hip])
            self.assertAlmostEqual(rig.foot(leg)[1], 0, places=7)
        turns = rig.g.metrics.turns
        rig.advance(90)
        self.assertEqual(rig.g.metrics.turns, turns)

    def test_seeded_direction_changes_preserve_groups_and_joint_limits(self):
        rig = GaitHarness()
        rng = random.Random(6)
        groups = ({"KneeL1", "KneeL3", "KneeR2"}, {"KneeL2", "KneeR1", "KneeR3"})
        for segment in range(80):
            forward = rng.choice((-0.8, -0.2, 0, 0.3, 1.3))
            yaw = rng.choice((-0.04, 0, 0, 0.04)) if forward else 0
            for _ in range(rng.randint(1, 35)):
                before = {leg.hip: rig.g.angles(leg.hip)[1] for leg in rig.legs}
                rig.step(forward=forward, yaw=yaw)
                lifted = rig.lifted()
                self.assertTrue(any(lifted <= group for group in groups),
                                f"Mixed support groups in segment {segment}: {lifted}")
                for leg in rig.legs:
                    angle = rig.g.angles(leg.hip)[1]
                    limit = abs((angle-leg.yaw+math.pi) % (2*math.pi)-math.pi)
                    delta = abs((angle-before[leg.hip]+math.pi) % (2*math.pi)-math.pi)
                    self.assertLessEqual(limit, rig.data.hipAmplitude+1e-7)
                    self.assertLessEqual(delta, 6/30+1e-7)
                    self.assertGreaterEqual(rig.foot(leg)[1], -1e-7)

    def test_heading_wrap_does_not_change_local_gait(self):
        straight, wrapped = GaitHarness(), GaitHarness(yaw=math.pi-0.03)
        for _ in range(120):
            for rig in (straight, wrapped):
                rig.step(forward=0.4, yaw=0.02)
            for leg in straight.legs:
                for name in (leg.hip, leg.knee):
                    for a, b in zip(straight.g.angles(name), wrapped.g.angles(name)):
                        self.assertAlmostEqual(a, b, places=7)

    def test_displacement_not_elapsed_time_controls_stride(self):
        slow, fast = GaitHarness(), GaitHarness()
        slow.advance(180, forward=0.2)
        fast.advance(90, forward=0.4)
        for leg in slow.legs:
            for name in (leg.hip, leg.knee):
                for a, b in zip(slow.g.angles(name), fast.g.angles(name)):
                    self.assertAlmostEqual(a, b, places=7)

    def test_skipped_samples_use_simulation_frame_delta(self):
        fine, coarse = GaitHarness(), GaitHarness()
        for rig in (fine, coarse):
            rig.advance(90, forward=0.5)
        fine.advance(6, forward=0.5)
        coarse.step(forward=3, frames=6)
        for leg in fine.legs:
            for name in (leg.hip, leg.knee):
                for a, b in zip(fine.g.angles(name), coarse.g.angles(name)):
                    self.assertAlmostEqual(a, b, places=7)

    def test_teleport_and_duplicate_frame_do_not_advance_pose(self):
        rig = GaitHarness()
        rig.advance(6, forward=1)
        before = {name: rig.g.angles(name) for leg in rig.legs for name in (leg.hip, leg.knee)}
        rig.step(forward=1000)
        for name, angles in before.items():
            self.assertEqual(rig.g.angles(name), angles)
        turns = rig.g.metrics.turns
        rig.g.step(rig.frame, rig.x, rig.y, rig.z, 0, 0, 1)
        self.assertEqual(rig.g.metrics.turns, turns)
        rig.advance(20)
        for _ in range(90):
            rig.step(forward=0.5)
            self.assertLessEqual(len(rig.lifted()), 3)

    def test_build_stance_is_reported_to_the_engine(self):
        rig = GaitHarness()
        stance = rig.g.COB.INBUILDSTANCE
        get_value = rig.g.Spring.UnitScript.GetUnitValue
        self.assertEqual(get_value(stance), 0)
        for _ in range(2):
            rig.g.callin("StartBuilding", 0, 0)
            self.assertEqual(get_value(stance), 1, "Arms animate, but the engine is still waiting to build")
            rig.advance(12)
            self.assertEqual(get_value(stance), 1)
            rig.g.callin("StopBuilding")
            self.assertEqual(get_value(stance), 0)

    def test_build_signals_do_not_kill_gait_or_leave_arm_threads(self):
        rig = GaitHarness()
        for _ in range(3):
            rig.g.callin("StartBuilding", 0, 0)
            rig.advance(12)
            self.assertNotEqual(rig.g.angles("ArmL")[0], 0)
            nano = (rig.g.script.QueryNanoPiece(), rig.g.script.QueryNanoPiece())
            self.assertEqual(set(nano), {"NanoL", "NanoR"})
            rig.g.callin("StopBuilding")
            rig.advance(20)
            for name in ("ArmL", "ArmR", "ForearmL", "ForearmR"):
                self.assertEqual(rig.g.angles(name), (0, 0, 0))
            moving = False
            for _ in range(18):
                rig.step(forward=0.5)
                moving |= bool(rig.lifted())
                self.assertLessEqual(len(rig.lifted()), 3)
            self.assertTrue(moving, "Build signal killed the walking thread")
            self.assertEqual(rig.g.translation("Base"), (0, 0, 0))
            self.assertEqual(rig.g.angles("Base"), (0, 0, 0))

    def test_restart_repro_needs_each_action_segment(self):
        for omitted in ("move", "stop", "restart"):
            with self.subTest(omitted=omitted):
                rig = GaitHarness()
                if omitted != "move":
                    rig.advance(6, forward=1)
                if omitted != "stop":
                    rig.advance(20)
                if omitted != "restart":
                    rig.advance(6, forward=1)
                self.assertLessEqual(len(rig.lifted()), 3)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + remaining)
