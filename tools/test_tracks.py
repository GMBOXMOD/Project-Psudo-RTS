"""Test closed-loop geometry, differential travel and the actual Lua controller.

The controller tests execute the real unit script with a deterministic Lua 5.1
scheduler. Engine transforms are recorded at their goals; visual interpolation is
checked separately by the real-engine track smoke test.
"""

import argparse
import json
import math
import pathlib
import sys
import unittest
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--lua-path", type=pathlib.Path)
parser.add_argument("--model", choices=("ztz99a", "m1a1"), default="ztz99a")
args, remaining = parser.parse_known_args()
if args.lua_path:
    sys.path.insert(0, str(args.lua_path.resolve()))
from lupa.lua51 import LuaRuntime

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "Scripts"
MODEL = args.model
UNIT_NAME = "mbt" if MODEL == "ztz99a" else "m1a1"
UNIT_SCRIPT = "mbtscript.lua" if MODEL == "ztz99a" else "m1a1script.lua"

HARNESS = r'''
world = {x=0,y=0,z=0,fx=0,fy=0,fz=1,frame=0}
Game = {gameSpeed=30}
UnitDefs = {[1]={}}
unitID, unitDefID = 7, 1
script = {}
local ids, nextID = {}, 0
local translations, rotations, spins, threads = {}, {}, {}, {}
metrics = {moveBatches=0,turnBatches=0,maxMoveArgs=0,spins=0,stops=0}
function piece(name)
    assert(validPiece(name), "Unknown model piece: " .. name)
    if not ids[name] then nextID=nextID+1; ids[name]=nextID end
    return ids[name]
end
local function noOp() end
local function position(id)
    if not translations[id] then translations[id]={0,0,0} end
    return translations[id]
end
local function rotation(id)
    if not rotations[id] then rotations[id]={0,0,0} end
    return rotations[id]
end
local function resume(thread)
    local ok, frames = coroutine.resume(thread.co)
    assert(ok, frames)
    thread.wake = world.frame + (frames or 1)
end
local us = {}
Spring = {
    UnitScript=us,
    GetUnitPosition=function() return world.x,world.y,world.z end,
    GetUnitDirection=function() return world.fx,world.fy,world.fz end,
    GetGameFrame=function() return world.frame end,
    GetGroundNormal=function() return 0,1,0 end,
}
us.StartThread=function(fn, ...)
    local arguments={...}
    local thread={co=coroutine.create(function() fn(unpack(arguments)) end)}
    threads[#threads+1]=thread
    resume(thread)
end
us.Sleep=function(ms) return coroutine.yield(math.max(1,math.ceil(ms*30/1000-0.000001))) end
us.Move=function(id,axis,goal,speed)
    assert(goal==goal and math.abs(goal)<10000)
    assert(speed>=0 and speed<100000)
    position(id)[axis]=goal
end
us.Turn=function(id,axis,goal,speed)
    assert(goal==goal and math.abs(goal)<=math.pi+0.000001)
    assert(speed>=0 and speed<100000)
    rotation(id)[axis]=goal
end
us.MultiMove=function(...)
    local list={...}
    assert(#list%4==0)
    metrics.moveBatches=metrics.moveBatches+1
    metrics.maxMoveArgs=math.max(metrics.maxMoveArgs,#list)
    for i=1,#list,4 do us.Move(list[i],list[i+1],list[i+2],list[i+3]) end
end
us.MultiTurn=function(...)
    local list={...}
    assert(#list%4==0)
    metrics.turnBatches=metrics.turnBatches+1
    for i=1,#list,4 do us.Turn(list[i],list[i+1],list[i+2],list[i+3]) end
end
us.Spin=function(id,axis,speed)
    spins[id]=speed
    metrics.spins=metrics.spins+1
end
us.StopSpin=function(id)
    spins[id]=0
    metrics.stops=metrics.stops+1
end
us.Hide,us.Show,us.EmitSfx,us.Signal,us.SetSignalMask=noOp,noOp,noOp,noOp,noOp
us.WaitForMove,us.WaitForTurn=noOp,noOp
function include(name)
    local chunk,err=loadstring(unitHeader .. readScript(name),name)
    assert(chunk,err)
    return chunk()
end
function step(frame,x,y,z,fx,fy,fz)
    world={frame=frame,x=x,y=y,z=z,fx=fx,fy=fy,fz=fz}
    for i=1,#threads do
        local thread=threads[i]
        if coroutine.status(thread.co)~="dead" and thread.wake<=frame then resume(thread) end
    end
end
function translation(name) return unpack(position(piece(name))) end
function angles(name) return unpack(rotation(piece(name))) end
function spin(name) return spins[piece(name)] or 0 end
'''


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    data = lua.execute((SCRIPTS/f"{MODEL}_track_data.lua").read_text(encoding="utf-8"))
    motion = lua.execute((SCRIPTS/"track_motion.lua").read_text(encoding="utf-8"))
    return lua, data, motion


def snapshot(lua, frame, x=0, y=0, z=0, yaw=0, fy=0):
    horizontal = math.sqrt(1-fy*fy)
    return lua.table_from(dict(frame=frame,x=x,y=y,z=z,
                               fx=math.sin(yaw)*horizontal,fy=fy,fz=math.cos(yaw)*horizontal))


class MotionMathTests(unittest.TestCase):
    def setUp(self):
        self.lua,self.data,self.motion=runtime()

    def test_rest_points_match_generated_rig(self):
        for i in range(1,self.data.linkCount+1):
            rest=self.data.links[i]
            y,z,a=self.motion.sample(self.data,rest.phase)
            self.assertAlmostEqual(y,rest.y,places=10)
            self.assertAlmostEqual(z,rest.z,places=10)
            self.assertAlmostEqual(self.motion.angleDifference(a,rest.angle),0,places=10)

    def test_path_is_closed_for_negative_and_multiple_laps(self):
        for s in (-1000,-1,0,35,78,140,1000):
            expected=self.motion.sample(self.data,s)
            actual=self.motion.sample(self.data,s+7*self.data.perimeter)
            for a,b in zip(actual[:2],expected[:2]):
                self.assertAlmostEqual(a,b,places=9)
            self.assertAlmostEqual(self.motion.angleDifference(expected[2],actual[2]),0,places=9)

    def test_path_has_no_position_or_angle_jump_at_joins(self):
        straight=2*self.data.halfStraight
        arc=math.pi*self.data.radius
        for seam in (0,straight,straight+arc,2*straight+arc,self.data.perimeter):
            before=self.motion.sample(self.data,seam-1e-7)
            after=self.motion.sample(self.data,seam+1e-7)
            self.assertLess(math.hypot(after[0]-before[0],after[1]-before[1]),3e-7)
            self.assertLess(abs(self.motion.angleDifference(before[2],after[2])),1e-6)

    def test_forward_and_reverse_follow_distance_not_time(self):
        old=snapshot(self.lua,0)
        for distance in (-9,9):
            result=self.motion.travel(old,snapshot(self.lua,3,z=distance),self.data.halfWidth)
            self.assertEqual(result,(distance,distance,3,False))

    def test_stopped_sideways_and_settling_do_not_roll(self):
        old=snapshot(self.lua,0)
        for new in (snapshot(self.lua,1),snapshot(self.lua,1,x=7),snapshot(self.lua,1,z=0.001)):
            self.assertEqual(self.motion.travel(old,new,self.data.halfWidth)[:2],(0,0))

    def test_pivot_drives_the_two_sides_in_opposite_directions(self):
        left,right,frames,_=self.motion.travel(snapshot(self.lua,0),
            snapshot(self.lua,15,yaw=math.pi/6),self.data.halfWidth)
        self.assertAlmostEqual(left,self.data.halfWidth*math.pi/6)
        self.assertAlmostEqual(right,-left)
        self.assertEqual(frames,15)

    def test_heading_wrap_uses_the_short_turn(self):
        result=self.motion.travel(snapshot(self.lua,0,yaw=math.radians(179)),
            snapshot(self.lua,1,yaw=math.radians(-179)),self.data.halfWidth)
        self.assertAlmostEqual(result[0],self.data.halfWidth*math.radians(2))
        self.assertAlmostEqual(result[1],-result[0])

    def test_slope_distance_includes_vertical_motion(self):
        old=snapshot(self.lua,0,fy=0.6)
        new=snapshot(self.lua,1,y=3,z=4,fy=0.6)
        self.assertEqual(self.motion.travel(old,new,self.data.halfWidth)[:2],(5,5))

    def test_teleports_and_duplicate_frames_do_not_wind_the_tracks(self):
        old=snapshot(self.lua,0)
        self.assertEqual(self.motion.travel(old,snapshot(self.lua,1,z=1000),self.data.halfWidth),(0,0,1,True))
        self.assertEqual(self.motion.travel(old,snapshot(self.lua,0,z=5),self.data.halfWidth),(0,0,0,False))


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.lua,self.data,self.motion=runtime()
        with zipfile.ZipFile(ROOT.parents[1]/"base"/"springcontent.sdz") as archive:
            name=next(n for n in archive.namelist() if n.lower()=="gamedata/unit_script_header.lua")
            self.lua.globals().unitHeader=archive.read(name).decode("utf-8")
        self.lua.globals().readScript=lambda name:(SCRIPTS/name).read_text(encoding="utf-8")
        manifest=json.loads((ROOT/"tools"/"previews"/f"{MODEL}_manifest.json").read_text(encoding="utf-8"))
        valid_pieces=set(manifest["pieces"])
        self.lua.globals().validPiece=lambda name:name in valid_pieces
        self.lua.execute(HARNESS)
        self.lua.globals().include(UNIT_SCRIPT)
        self.lua.globals().script.Create()
        self.g=self.lua.globals()

    def step(self,frame,z=0,x=0,yaw=0):
        self.g.step(frame,x,0,z,math.sin(yaw),0,math.cos(yaw))

    def assert_phase(self,side,phase):
        for i in range(1,self.data.linkCount+1):
            rest=self.data.links[i]
            name=rest.left if side=="left" else rest.right
            _,dy,dz=self.g.translation(name)
            angle,_,_=self.g.angles(name)
            y,z,a=self.motion.sample(self.data,rest.phase+phase)
            self.assertAlmostEqual(rest.y+dy,y,places=7)
            self.assertAlmostEqual(rest.z+dz,z,places=7)
            self.assertAlmostEqual(self.motion.angleDifference(rest.angle+angle,a),0,places=7)

    def test_idle_does_not_submit_transforms(self):
        for frame in range(1,61): self.step(frame)
        self.assertEqual(self.g.metrics.moveBatches,0)
        self.assertEqual(self.g.metrics.turnBatches,0)
        self.assertEqual(self.g.metrics.spins,0)

    def test_actual_translation_rolls_belts_and_both_wheel_sizes(self):
        for frame in range(1,31): self.step(frame,z=frame)
        self.assert_phase("left",30)
        self.assert_phase("right",30)
        self.assertAlmostEqual(self.g.spin("WheelL1"),30/self.data.wheelRadius)
        last=int(self.data.wheelCount or 6)
        self.assertAlmostEqual(self.g.spin(f"WheelR{last}"),30/self.data.wheelRadius)
        self.assertAlmostEqual(self.g.spin("IdlerRRear"),30/self.data.idlerRadius)
        self.assertEqual(self.g.metrics.moveBatches,30)
        self.assertEqual(self.g.metrics.turnBatches,30)
        self.assertEqual(self.g.metrics.maxMoveArgs,self.data.linkCount*2*8)

    def test_reverse_rolls_both_sides_backwards(self):
        for frame in range(1,31): self.step(frame,z=-0.5*frame)
        self.assert_phase("left",-15)
        self.assert_phase("right",-15)
        self.assertLess(self.g.spin("WheelL1"),0)
        self.assertLess(self.g.spin("WheelR1"),0)

    def test_pivot_works_without_start_moving_callback(self):
        for frame in range(1,91): self.step(frame,yaw=frame*math.pi/180)
        distance=self.data.halfWidth*math.pi/2
        self.assert_phase("left",distance)
        self.assert_phase("right",-distance)
        self.assertGreater(self.g.spin("WheelL1"),0)
        self.assertLess(self.g.spin("WheelR1"),0)

    def test_stopping_keeps_the_phase_but_stops_wheels(self):
        for frame in range(1,31): self.step(frame,z=frame)
        before=self.g.metrics.moveBatches
        for frame in range(31,91): self.step(frame,z=30)
        self.assert_phase("left",30)
        self.assertEqual(self.g.metrics.moveBatches,before)
        self.assertEqual(self.g.spin("WheelL1"),0)
        self.assertEqual(self.g.spin("IdlerRFront"),0)

    def test_movement_does_not_bob_the_chassis_on_flat_ground(self):
        if self.g.script.StartMoving:
            self.g.script.StartMoving()
        heights=[]
        for frame in range(1,91):
            self.step(frame,z=frame*0.5)
            heights.append(self.g.translation("Base")[1])
        self.assertLessEqual(max(abs(height) for height in heights),0.001,
                             "Flat-ground movement must not add a periodic local Y offset")
        self.assertGreater(self.g.metrics.moveBatches,0,"Tracks must still animate")

    def test_native_terrain_alignment_is_not_applied_twice(self):
        self.lua.execute("lowerkeys=function(values) return values end")
        definition=self.lua.execute((ROOT/"Units"/f"{UNIT_NAME}.lua").read_text(encoding="utf-8"))[UNIT_NAME]
        self.assertIs(definition["Upright"],False)
        self.assertGreater(definition["UpDirSmoothing"],0)
        self.assertLessEqual(definition["UpDirSmoothing"],0.95)
        self.lua.execute("Spring.GetGroundNormal=function() return 0.2,0.96,0.19 end")
        if self.g.script.StartMoving:
            self.g.script.StartMoving()
        for frame in range(1,31):
            self.step(frame,z=frame*0.5)
            pitch,_,roll=self.g.angles("Base")
            self.assertAlmostEqual(pitch,0,delta=1e-6)
            self.assertAlmostEqual(roll,0,delta=1e-6)

    def test_create_neutralizes_a_previous_chassis_pose(self):
        base=self.g.piece("Base")
        self.g.Spring.UnitScript.Move(base,2,0.7,0)
        self.g.Spring.UnitScript.Turn(base,1,0.1,0)
        self.g.Spring.UnitScript.Turn(base,3,-0.1,0)
        self.g.script.Create()
        self.assertEqual(self.g.translation("Base"),(0,0,0))
        self.assertEqual(self.g.angles("Base"),(0,0,0))

    def test_multiple_laps_and_resume_after_teleport(self):
        for frame in range(1,501): self.step(frame,z=frame*0.75)
        self.assert_phase("left",375)
        self.step(501,z=1375)
        self.assert_phase("left",375)
        self.assertEqual(self.g.spin("WheelL1"),0)
        self.step(502,z=1376)
        self.assert_phase("left",376)


if __name__=="__main__":
    unittest.main(argv=[sys.argv[0]]+remaining)
