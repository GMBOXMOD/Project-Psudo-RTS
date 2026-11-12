"""Replay the real Vehicle Factory script with a deterministic Lua 5.1 scheduler.

    python -I -B D:/Recoil/games/MyGame.sdd/tools/test_vehicle_factory_script.py -v
    python -I -B D:/Recoil/games/MyGame.sdd/tools/test_vehicle_factory_script.py --lua-path <existing-lupa-directory> -v

Loads the installed springcontent.sdz unit_script_header, the delivered script,
and the generated rig/manifest. Move/Turn interpolate, waits observe completion,
and signals cancel coroutines without magically cancelling native piece motors.
Activate/Deactivate/queries are synchronous; Create/build callbacks are threaded,
and Killed completes through its threaded return wrapper. Engine read APIs are
fixtures, not a replacement implementation of the controller.

This test never builds assets, installs dependencies, edits UnitDefs, launches an
engine or controls real products. Yard acceptance is an explicit engine fixture;
native YardMap, collision, pathfinding, resource starvation, four-facing queues,
visual quality and full M1A1 weapon-envelope clearance remain NOT_RUN.
"""

from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
from pathlib import Path
import random
import struct
import sys
import unittest
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "Scripts"
ARCHIVE = ROOT.parents[1] / "base" / "springcontent.sdz"
SCRIPT_NAME = "vehicle_factoryscript.lua"
FACTORY_ID = 7
LUA_RUNTIME = None


@lru_cache(maxsize=None)
def script_text(name):
    if name not in (SCRIPT_NAME, "vehicle_factory_data.lua"):
        raise AssertionError(f"Unexpected script dependency: {name}")
    return (SCRIPTS / name).read_text(encoding="utf-8-sig")


@lru_cache(maxsize=1)
def unit_header():
    # Never substitute a handwritten header: it supplies the actual local aliases
    # and axes used when the delivered script is loaded by the game.
    with zipfile.ZipFile(ARCHIVE) as archive:
        member = next(name for name in archive.namelist()
                      if name.lower() == "gamedata/unit_script_header.lua")
        return archive.read(member).decode("utf-8-sig")


@lru_cache(maxsize=1)
def manifest():
    return json.loads((ROOT / "tools/previews/vehicle_factory/manifest.json")
                      .read_text(encoding="utf-8-sig"))


@lru_cache(maxsize=None)
def model_bounds(name):
    """Use the real S3O model sphere, especially for M1A1, not the old R40 proxy."""
    with (ROOT / "Objects3d" / f"{name}.s3o").open("rb") as source:
        magic, version, radius, height, mx, my, mz = struct.unpack("<12si5f", source.read(36))
    if magic.rstrip(b"\0") != b"Spring unit" or version != 0:
        raise AssertionError(f"Unexpected S3O header: {name}")
    if not all(math.isfinite(v) for v in (radius, height, mx, my, mz)) or radius <= 0:
        raise AssertionError(f"Invalid S3O sphere: {name}")
    return dict(radius=radius, midX=mx, midY=my, midZ=mz)


def lua_runtime():
    global LUA_RUNTIME
    if LUA_RUNTIME is None:
        from lupa.lua51 import LuaRuntime
        LUA_RUNTIME = LuaRuntime
    return LUA_RUNTIME(unpack_returned_tuples=True)


HARNESS = r'''
Game = {gameSpeed=30, squareSize=8}
COB = {INBUILDSTANCE=5, YARD_OPEN=18, BUGGER_OFF=19}
SFX = {SHATTER=1}
unitID, unitDefID = 7, 1
script = {}
world = {
    frame=0, allowOpen=true, allowClose=true, dropSignals=false,
    enforceInterlocks=true, dying=false, target=nil, speedScale={}, extraUnits={},
}
UnitDefs = {
    [1]={isImmobile=true, isBuilding=true, canMove=true, speed=0, xsize=24, zsize=20},
    [2]={isImmobile=false, canMove=true, canFly=false, speed=40, xsize=4, zsize=4},
    [3]={isImmobile=true, isBuilding=true, canMove=false, speed=0, xsize=24, zsize=20},
    [4]={isImmobile=false, canMove=true, canFly=true, speed=120, xsize=4, zsize=4},
}
units = {}
events = {}
metrics = {moves=0, turns=0, starts=0, waits=0, signals=0, cancellations=0, radiusReads={}}
local ids, names, parents, offsets = {}, {}, {}, {}
local motors = {move={}, turn={}}
local visibility, values, threads = {}, {}, {}
local running
local lastYardRequest, lastYardRead, lastYardReadValue = 0, 0, nil
local EPS, TAU = 0.0000001, 2 * math.pi
local us = {}

local function finite(n)
    return type(n)=="number" and n==n and math.abs(n)<math.huge
end

local function pack(...)
    return {n=select("#", ...), ...}
end

-- Lua 5.1 has no built-in bitwise operator. Signals match ANY common bit, not
-- mask equality, and a child inherits its parent's mask at StartThread time.
local function intersects(a,b)
    while a>0 and b>0 do
        if a%2==1 and b%2==1 then return true end
        a,b=math.floor(a/2),math.floor(b/2)
    end
    return false
end

function addPiece(name, parent, x, y, z)
    assert(not ids[name], "Duplicate piece "..name)
    local id=#names+1
    ids[name],names[id]=id,name
    parents[id]=parent and assert(ids[parent], "Parent must precede child") or nil
    offsets[id]={x,y,z}
    visibility[id]=true
end

function piece(name)
    local id=ids[name]
    assert(id, "Unknown delivered piece: "..tostring(name))
    return id
end

local function motor(kind,id,axis)
    assert(names[id], "Unknown piece ID")
    assert(axis==1 or axis==2 or axis==3, "Bad axis")
    if not motors[kind][id] then motors[kind][id]={} end
    if not motors[kind][id][axis] then
        motors[kind][id][axis]={from=0,goal=0,delta=0,start=0,finish=0}
    end
    return motors[kind][id][axis]
end

local function sample(m)
    if world.frame>=m.finish-EPS then return m.goal end
    local t=(world.frame-m.start)/(m.finish-m.start)
    return m.from+m.delta*math.max(0,math.min(1,t))
end

local function moving(kind,id,axis)
    return world.frame < motor(kind,id,axis).finish-EPS
end

local function doorPosition(name)
    return sample(motor("move",piece(name),1))
end

local function doorsFullyOpen()
    return math.abs(doorPosition("DoorL")-rigData.door.leftOpenMoveWorld)<EPS
       and math.abs(doorPosition("DoorR")-rigData.door.rightOpenMoveWorld)<EPS
end

local function record(kind,fields)
    fields=fields or {}
    fields.kind,fields.frame,fields.thread=kind,world.frame,running and running.id or 0
    fields.index=#events+1
    events[#events+1]=fields
    return fields.index
end

local function requireThread(operation)
    assert(running and coroutine.running()==running.co,
           operation.." requires a unit-script coroutine, not a synchronous callin")
end

local function resumeThread(thread)
    if thread.cancelled or thread.done then return end
    local parent=running
    running=thread
    local result=pack(coroutine.resume(thread.co))
    running=parent
    assert(result[1], result[2])
    if coroutine.status(thread.co)=="dead" then
        thread.done=true
    else
        assert(type(result[2])=="table", "Unexpected coroutine yield")
        thread.wait=result[2]
    end
end

us.StartThread=function(fn,...)
    local args=pack(...)
    local thread={id=#threads+1,mask=running and running.mask or 0}
    thread.co=coroutine.create(function() return fn(unpack(args,1,args.n)) end)
    threads[#threads+1]=thread
    metrics.starts=metrics.starts+1
    record("start",{child=thread.id,inheritedMask=thread.mask})
    resumeThread(thread) -- run immediately to the first wait, as the engine does
    return thread.co
end

us.SetSignalMask=function(mask)
    requireThread("SetSignalMask")
    assert(mask>=0 and mask==math.floor(mask))
    running.mask=mask
    record("mask",{mask=mask})
end

us.Signal=function(mask)
    metrics.signals=metrics.signals+1
    record("signal",{mask=mask})
    if world.dropSignals then return end -- fault injection tests the epoch guard
    for _, thread in ipairs(threads) do
        if not thread.done and not thread.cancelled and intersects(thread.mask,mask) then
            thread.cancelled=true
            metrics.cancellations=metrics.cancellations+1
        end
    end
    if running and running.cancelled then coroutine.yield({kind="cancelled"}) end
end

us.Sleep=function(ms)
    requireThread("Sleep")
    assert(finite(ms) and ms>=0)
    local frames=math.max(1,math.ceil(ms*Game.gameSpeed/1000-EPS))
    return coroutine.yield({kind="sleep",wake=world.frame+frames})
end

local function waitMotion(kind,id,axis)
    requireThread("WaitFor"..kind)
    metrics.waits=metrics.waits+1
    record("wait",{motion=kind,piece=names[id],axis=axis})
    while moving(kind,id,axis) do
        coroutine.yield({kind=kind,piece=id,axis=axis})
    end
end
us.WaitForMove=function(id,axis) return waitMotion("move",id,axis) end
us.WaitForTurn=function(id,axis) return waitMotion("turn",id,axis) end
us.IsInMove=function(id,axis) return moving("move",id,axis) end
us.IsInTurn=function(id,axis) return moving("turn",id,axis) end

local function commandMotion(kind,id,axis,goal,speed)
    assert(finite(goal) and (speed==nil or (finite(speed) and speed>=0)))
    local m=motor(kind,id,axis)
    local current=sample(m)
    local name=names[id]
    if world.enforceInterlocks and not world.dying and kind=="move"
        and (name=="DoorL" or name=="DoorR") and speed and speed>0
        and goal==rigData.door.closedMoveWorld then
        assert((values[COB.INBUILDSTANCE] or 0)==0, "Closing before disabling construction")
        assert((values[COB.YARD_OPEN] or 0)==0, "Closing before yard acceptance")
        assert((values[COB.BUGGER_OFF] or 0)==0, "Closing with bugger-off still set")
        assert(lastYardRead>lastYardRequest and lastYardReadValue==0,
               "Closing without an actual accepted-yard readback")
    end
    m.from,m.goal,m.start=current,goal,world.frame
    m.delta=kind=="turn" and ((goal-current+math.pi)%TAU-math.pi) or goal-current
    local effective=(speed or 0)*(world.speedScale[name] or 1)
    if effective==0 or math.abs(m.delta)<EPS then
        m.from,m.delta,m.finish=goal,0,world.frame
    else
        m.finish=world.frame+math.abs(m.delta)*Game.gameSpeed/effective
    end
    if kind=="move" then metrics.moves=metrics.moves+1 else metrics.turns=metrics.turns+1 end
    record(kind,{piece=name,axis=axis,goal=goal,speed=speed or 0,from=current,
                 yard=values[COB.YARD_OPEN] or 0,stance=values[COB.INBUILDSTANCE] or 0})
end
us.Move=function(...) return commandMotion("move",...) end
us.Turn=function(...) return commandMotion("turn",...) end
us.GetPieceTranslation=function(id)
    return sample(motor("move",id,1)),sample(motor("move",id,2)),sample(motor("move",id,3))
end
us.GetPieceRotation=function(id)
    return sample(motor("turn",id,1)),sample(motor("turn",id,2)),sample(motor("turn",id,3))
end
us.Hide=function(id) visibility[id]=false; record("hide",{piece=names[id]}) end
us.Show=function(id) visibility[id]=true; record("show",{piece=names[id]}) end
us.Explode=function(id,flags) record("explode",{piece=names[id],flags=flags}) end
us.GetUnitValue=function(key)
    assert(key~=nil)
    local value=values[key] or 0
    local index=record("get",{key=key,value=value})
    if key==COB.YARD_OPEN then lastYardRead,lastYardReadValue=index,value end
    return value
end
us.SetUnitValue=function(key,value)
    assert(key~=nil)
    if world.enforceInterlocks and key==COB.YARD_OPEN and value==1 then
        assert(doorsFullyOpen(), "Opening the native yard before both doors arrived")
    end
    if world.enforceInterlocks and value==1
        and (key==COB.INBUILDSTANCE or key==COB.BUGGER_OFF) then
        assert(doorsFullyOpen(), "Release before BOTH interpolated doors arrived")
        assert(values[COB.YARD_OPEN]==1, "Release before engine accepted open yard")
        assert(lastYardRead>lastYardRequest and lastYardReadValue==1,
               "Release without actual yard-open readback")
    end
    local accepted=true
    if key==COB.YARD_OPEN then
        accepted=(value==1 and world.allowOpen) or (value==0 and world.allowClose)
    end
    if accepted then values[key]=value end
    local index=record("set",{key=key,value=value,actual=values[key] or 0,accepted=accepted,
                              left=doorPosition("DoorL"),right=doorPosition("DoorR")})
    if key==COB.YARD_OPEN then lastYardRequest=index end
end

local function valid(id)
    return units[id]~=nil and units[id].valid~=false
end
Spring = {
    UnitScript=us,
    ValidUnitID=valid,
    GetGameFrame=function() return world.frame end,
    GetUnitDefID=function(id) return valid(id) and units[id].defID or nil end,
    GetUnitIsDead=function(id)
        if not valid(id) then return nil end
        return units[id].dead==true
    end,
    GetUnitDirection=function(id)
        if not valid(id) then return nil end
        local u=units[id]
        return u.fx,u.fy,u.fz
    end,
    GetUnitPosition=function(id,midpoint)
        if not valid(id) or units[id].positionAvailable==false then return nil end
        local u=units[id]
        if midpoint then
            local dx,dy,dz=u.midX or 0,u.midY or 0,u.midZ or 0
            return u.x,u.y,u.z,u.x+u.fz*dx+u.fx*dz,u.y+dy,u.z-u.fx*dx+u.fz*dz
        end
        return u.x,u.y,u.z
    end,
    GetUnitRadius=function(id)
        metrics.radiusReads[id]=(metrics.radiusReads[id] or 0)+1
        return valid(id) and units[id].radius or nil
    end,
    GetUnitTransporter=function(id) return valid(id) and units[id].transporter or nil end,
    GetUnitHealth=function(id)
        if not valid(id) or units[id].healthAvailable==false then return nil end
        local u=units[id]
        return u.health,100,0,0,u.progress
    end,
    GetUnitIsBuilding=function(id)
        assert(id==unitID)
        return world.target
    end,
    GetAllUnits=function()
        local list={}
        for id in pairs(units) do
            if id~=world.omitFromQuery then list[#list+1]=id end
        end
        for _, id in ipairs(world.extraUnits) do list[#list+1]=id end
        table.sort(list)
        return list
    end,
}
local function forbidden() error("Controller attempted to control gameplay/products/resources") end
Spring.CreateUnit,Spring.DestroyUnit,Spring.GiveOrderToUnit=forbidden,forbidden,forbidden
Spring.SetUnitHealth,Spring.SetUnitPosition,Spring.SetUnitRotation=forbidden,forbidden,forbidden
Spring.AddUnitResource,Spring.UseUnitResource,Spring.SetUnitResources=forbidden,forbidden,forbidden
Spring.MoveCtrl=setmetatable({}, {__index=function() return forbidden end})

function include(name)
    local chunk,err=loadstring(unitHeader.."\n"..readScript(name),"@Scripts/"..name)
    assert(chunk,err)
    return chunk()
end
function runSource(source)
    local chunk,err=loadstring(unitHeader.."\n"..source,"@scheduler-probe")
    assert(chunk,err)
    return chunk()
end

local threadedCallins={Create=true,StartBuilding=true,StopBuilding=true}
local synchronousCallins={Activate=true,Deactivate=true,QueryBuildInfo=true,QueryNanoPiece=true}
function callin(name,...)
    assert(not running, "Engine callins enter from outside the coroutine scheduler")
    local fn=assert(script[name], "Missing callin "..name)
    if name=="Killed" then
        world.dying=true
        local args=pack(...)
        -- The native death-call wrapper consumes Killed's eventual return; the
        -- C++ callback must not receive a coroutine object as the wreck level.
        us.StartThread(function() world.deathResult=fn(unpack(args,1,args.n)) end)
        return nil
    elseif threadedCallins[name] then
        us.StartThread(fn,...)
        return nil
    end
    assert(synchronousCallins[name], "Unspecified callback wrapping: "..name)
    return fn(...)
end

function advance(frames)
    assert(frames>=0 and frames==math.floor(frames))
    for _=1,frames do
        world.frame=world.frame+1
        for i=1,#threads do
            local thread=threads[i]
            if not thread.done and not thread.cancelled then
                local wait=assert(thread.wait)
                local ready=wait.kind=="sleep" and wait.wake<=world.frame
                if wait.kind=="move" or wait.kind=="turn" then
                    ready=not moving(wait.kind,wait.piece,wait.axis)
                end
                if ready then resumeThread(thread) end
            end
        end
    end
end
function liveThreads(mask)
    local count=0
    for _, t in ipairs(threads) do
        if not t.done and not t.cancelled and (not mask or intersects(t.mask,mask)) then
            count=count+1
        end
    end
    return count
end
function value(key) return values[key] or 0 end -- inspection does NOT fake a script readback
function translation(name) return us.GetPieceTranslation(piece(name)) end
function angles(name) return us.GetPieceRotation(piece(name)) end
function goal(kind,name,axis) return motor(kind,piece(name),axis).goal end
function isMoving(kind,name,axis) return moving(kind,piece(name),axis) end
function visible(name) return visibility[piece(name)] end
function pieceWorld(name)
    local id=piece(name)
    local x,y,z=0,0,0
    while id do
        -- The queried locators have translation-only ancestors. A surprise
        -- rotation here is a controller regression, not ignored test geometry.
        local ax,ay,az=us.GetPieceRotation(id)
        assert(math.abs(ax)+math.abs(ay)+math.abs(az)<EPS, "Locator ancestor rotated")
        local dx,dy,dz=us.GetPieceTranslation(id)
        x,y,z=x+offsets[id][1]+dx,y+offsets[id][2]+dy,z+offsets[id][3]+dz
        id=parents[id]
    end
    local u=units[unitID]
    return u.x+u.fz*x+u.fx*z,u.y+y,u.z-u.fx*x+u.fz*z
end
'''


class FactoryHarness:
    def __init__(self, facing=0, origin=(230.0, 12.0, -470.0), controller=True):
        self.lua = lua_runtime()
        self.g = self.lua.globals()
        self.g.unitHeader = unit_header()
        self.g.readScript = script_text
        self.lua.execute(HARNESS)
        rig = manifest()
        if rig["nodes"] != 12 or len(rig["pieces"]) != 12:
            raise AssertionError("The delivered factory must retain its 12-piece contract")
        for item in rig["piece_statistics"]:
            self.g.addPiece(item["name"], item["parent"], *item["offset_world"])
        self.data = self.g.include("vehicle_factory_data.lua")
        self.g.rigData = self.data
        self.facing = facing
        self.origin = origin
        self.fx, self.fz = math.sin(facing * math.pi / 2), math.cos(facing * math.pi / 2)
        self.add_unit(FACTORY_ID, def_id=1, model="vehicle_factory")
        self.g.world.enforceInterlocks = controller
        if controller:
            self.g.include(SCRIPT_NAME)
            self.call("Create")

    def add_unit(self, unit=20, x=0.0, z=0.0, y=0.0, radius=16.0, progress=0.2,
                 def_id=2, model=None, facing=None, **extra):
        yaw = (self.facing if facing is None else facing) * math.pi / 2
        fields = dict(valid=True, dead=False, defID=def_id, health=100, progress=progress,
                      radius=radius, midX=0, midY=0, midZ=0,
                      fx=math.sin(yaw), fy=0, fz=math.cos(yaw))
        if model:
            fields.update(model_bounds(model))
        fields.update(extra)
        self.g.units[unit] = self.lua.table_from(fields)
        self.place(unit, x=x, z=z, y=y)
        return self.g.units[unit]

    def place(self, unit, x=0.0, z=0.0, y=0.0):
        u = self.g.units[unit]
        ox, oy, oz = self.origin
        u.x, u.y, u.z = ox + self.fz*x + self.fx*z, oy + y, oz - self.fx*x + self.fz*z

    def call(self, name, *args):
        return self.g.callin(name, *args)

    def advance(self, frames):
        self.g.advance(frames)

    def until(self, predicate, limit=240):
        for _ in range(limit):
            if predicate():
                return
            self.advance(1)
        raise AssertionError(f"Condition did not become true by frame {self.g.world.frame}")

    def state(self, key):
        return self.g.value(self.g.COB[key])

    def open(self):
        self.call("Activate")
        self.until(lambda: self.state("INBUILDSTANCE") == 1)

    def start_product(self, unit=20, progress=0.2, **kwargs):
        u = self.add_unit(unit, z=self.data.buildSpot.positionWorld.z, progress=progress, **kwargs)
        self.g.world.target = unit
        self.call("StartBuilding", 0, 0)
        self.advance(6)  # establish an actual target/progress baseline
        return u

    def work(self):
        self.open()
        u = self.start_product()
        u.progress = 0.22
        self.advance(3)
        if not self.g.visible("WorkLamp"):
            raise AssertionError("Real progress did not start the work animation")
        return u

    def event_list(self, kind=None, since=0):
        events = [self.g.events[i] for i in range(since+1, len(self.g.events)+1)]
        return [event for event in events if kind is None or event.kind == kind]

    def work_goals(self):
        return (
            self.g.goal("move", "Gantry", 3),
            self.g.goal("move", "HeadL", 1), self.g.goal("move", "HeadL", 2),
            self.g.goal("move", "HeadR", 1), self.g.goal("move", "HeadR", 2),
            self.g.goal("turn", "FanL", 2), self.g.goal("turn", "FanR", 2),
        )


class SchedulerTests(unittest.TestCase):
    def test_real_header_sync_callbacks_cannot_wait_or_set_signal_masks(self):
        for operation in ("Sleep(1)", "SetSignalMask(1)", 'WaitForMove(piece("DoorL"),x_axis)'):
            with self.subTest(operation=operation):
                rig = FactoryHarness(controller=False)
                self.assertGreater(len(rig.g.unitHeader), 100)
                rig.g.runSource("function script.Activate() " + operation + " return 1 end")
                with self.assertRaisesRegex(Exception, "requires a unit-script coroutine"):
                    rig.call("Activate")

    def test_move_turn_interpolation_and_wait_completion_are_not_instant(self):
        rig = FactoryHarness(controller=False)
        rig.g.runSource('''
            function script.StartBuilding()
                Move(piece("DoorL"),x_axis,-48,24)
                WaitForMove(piece("DoorL"),x_axis)
                world.moveFinished=world.frame
                Turn(piece("FanL"),y_axis,math.pi/2,math.pi)
                WaitForTurn(piece("FanL"),y_axis)
                world.turnFinished=world.frame
            end
        ''')
        self.assertIsNone(rig.call("StartBuilding", 0, 0))
        self.assertEqual(rig.g.translation("DoorL")[0], 0)
        rig.advance(30)
        self.assertAlmostEqual(rig.g.translation("DoorL")[0], -24)
        self.assertIsNone(rig.g.world.moveFinished)
        rig.advance(30)
        self.assertEqual(rig.g.world.moveFinished, 60)
        self.assertEqual(rig.g.angles("FanL")[1], 0)
        rig.advance(7)
        self.assertAlmostEqual(rig.g.angles("FanL")[1], math.pi*7/30)
        self.assertIsNone(rig.g.world.turnFinished)
        rig.advance(8)
        self.assertEqual(rig.g.world.turnFinished, 75)
        self.assertAlmostEqual(rig.g.angles("FanL")[1], math.pi/2)

    def test_signal_bit_overlap_inheritance_and_native_motor_survival(self):
        rig = FactoryHarness(controller=False)
        rig.g.runSource('''
            function script.StartBuilding()
                StartThread(function()
                    SetSignalMask(1)
                    StartThread(function() Sleep(1000); world.inheritedFired=true end)
                    Move(piece("DoorL"),x_axis,-48,24)
                    WaitForMove(piece("DoorL"),x_axis)
                    world.cancelledFired=true
                end)
                StartThread(function()
                    SetSignalMask(2)
                    Sleep(500)
                    world.survivorFired=true
                end)
            end
            function script.StopBuilding() Signal(5) end
        ''')
        rig.call("StartBuilding", 0, 0)
        rig.advance(10)
        rig.call("StopBuilding")
        self.assertEqual(rig.g.liveThreads(1), 0)
        self.assertEqual(rig.g.liveThreads(2), 1)
        rig.advance(80)
        self.assertIsNone(rig.g.world.inheritedFired)
        self.assertIsNone(rig.g.world.cancelledFired)
        self.assertTrue(rig.g.world.survivorFired)
        self.assertEqual(rig.g.translation("DoorL")[0], -48)
        self.assertEqual(rig.g.liveThreads(), 0)


class FactoryScriptTests(unittest.TestCase):
    def assert_open(self, rig, ready=True):
        self.assertAlmostEqual(rig.g.translation("DoorL")[0], rig.data.door.leftOpenMoveWorld)
        self.assertAlmostEqual(rig.g.translation("DoorR")[0], rig.data.door.rightOpenMoveWorld)
        self.assertEqual(rig.state("YARD_OPEN"), 1)
        self.assertEqual(rig.state("INBUILDSTANCE"), int(ready))
        self.assertEqual(rig.state("BUGGER_OFF"), 1)

    def assert_closed(self, rig):
        for name in ("DoorL", "DoorR"):
            self.assertAlmostEqual(rig.g.translation(name)[0], rig.data.door.closedMoveWorld)
            self.assertFalse(rig.g.isMoving("move", name, 1))
        for key in ("YARD_OPEN", "INBUILDSTANCE", "BUGGER_OFF"):
            self.assertEqual(rig.state(key), 0)

    def close_and_wait(self, rig):
        rig.call("Deactivate")
        rig.until(lambda: rig.state("YARD_OPEN") == 0 and
                  not rig.g.isMoving("move", "DoorL", 1) and
                  not rig.g.isMoving("move", "DoorR", 1))
        self.assert_closed(rig)

    def assert_home(self, rig):
        self.assertFalse(rig.g.visible("WorkLamp"))
        self.assertAlmostEqual(rig.g.translation("Gantry")[2], rig.data.gantry.minMoveWorld)
        for name in ("HeadL", "HeadR"):
            self.assertAlmostEqual(rig.g.translation(name)[0], 0)
            self.assertAlmostEqual(rig.g.translation(name)[1], rig.data.heads.maxYMoveWorld)
        for name in ("FanL", "FanR"):
            self.assertAlmostEqual(rig.g.angles(name)[1], rig.data.fans.minAngleRadians)

    def assert_root_stable(self, rig, build_world):
        for name in ("Base", "BuildSpot"):
            self.assertEqual(tuple(rig.g.translation(name)), (0, 0, 0))
            self.assertEqual(tuple(rig.g.angles(name)), (0, 0, 0))
            self.assertFalse(any(e.piece == name for e in rig.event_list() if e.kind in ("move", "turn")))
        self.assertEqual(tuple(rig.g.pieceWorld("BuildSpot")), build_world)

    def assert_all_goals_in_rig(self, rig):
        d = rig.data
        bounds = {
            ("DoorL", 1): (d.door.leftOpenMoveWorld, d.door.closedMoveWorld),
            ("DoorR", 1): (d.door.closedMoveWorld, d.door.rightOpenMoveWorld),
            ("Gantry", 3): (d.gantry.minMoveWorld, d.gantry.maxMoveWorld),
            ("HeadL", 1): (d.heads.minXMoveWorld, d.heads.maxXMoveWorld),
            ("HeadR", 1): (d.heads.minXMoveWorld, d.heads.maxXMoveWorld),
            ("HeadL", 2): (d.heads.minYMoveWorld, d.heads.maxYMoveWorld),
            ("HeadR", 2): (d.heads.minYMoveWorld, d.heads.maxYMoveWorld),
        }
        for event in rig.event_list("move"):
            key = (event.piece, event.axis)
            self.assertIn(key, bounds)
            low, high = bounds[key]
            self.assertGreaterEqual(event.goal, low-1e-8)
            self.assertLessEqual(event.goal, high+1e-8)
        for event in rig.event_list("turn"):
            self.assertIn(event.piece, ("FanL", "FanR"))
            self.assertEqual(event.axis, 2)
            self.assertGreaterEqual(event.goal, d.fans.minAngleRadians-1e-8)
            self.assertLessEqual(event.goal, d.fans.maxAngleRadians+1e-8)

    def test_initial_state_and_idle_do_not_animate_the_foundation(self):
        rig = FactoryHarness()
        build_world = tuple(rig.g.pieceWorld("BuildSpot"))
        self.assert_closed(rig)
        self.assert_home(rig)
        before = (rig.g.metrics.moves, rig.g.metrics.turns)
        rig.advance(300)
        self.assertEqual((rig.g.metrics.moves, rig.g.metrics.turns), before)
        self.assertEqual(rig.g.liveThreads(1), 0)
        self.assertEqual(rig.g.liveThreads(2), 1)
        self.assert_root_stable(rig, build_world)

    def test_activate_is_synchronous_and_does_not_treat_goals_as_arrival(self):
        rig = FactoryHarness()
        self.assertEqual(rig.call("Activate"), 1)
        self.assertEqual(rig.g.translation("DoorL")[0], 0)
        self.assertEqual(rig.g.translation("DoorR")[0], 0)
        rig.advance(24)
        self.assertAlmostEqual(rig.g.translation("DoorL")[0], -24)
        self.assertAlmostEqual(rig.g.translation("DoorR")[0], 24)
        for key in ("INBUILDSTANCE", "YARD_OPEN", "BUGGER_OFF"):
            self.assertEqual(rig.state(key), 0)
        rig.advance(23)
        self.assertEqual(rig.state("INBUILDSTANCE"), 0)
        rig.advance(1)
        self.assert_open(rig)

    def test_both_doors_must_finish_even_when_one_motor_is_slower(self):
        rig = FactoryHarness()
        rig.g.world.speedScale["DoorR"] = 0.5
        rig.call("Activate")
        rig.advance(48)
        self.assertEqual(rig.g.translation("DoorL")[0], -48)
        self.assertEqual(rig.g.translation("DoorR")[0], 24)
        self.assertEqual(rig.state("YARD_OPEN"), 0)
        self.assertEqual(rig.state("INBUILDSTANCE"), 0)
        rig.advance(47)
        self.assertEqual(rig.state("BUGGER_OFF"), 0)
        rig.advance(1)
        self.assert_open(rig)

    def test_open_yard_request_must_be_accepted_and_read_back(self):
        rig = FactoryHarness()
        rig.g.world.allowOpen = False
        rig.call("Activate")
        rig.advance(150)
        self.assertEqual(rig.g.translation("DoorL")[0], -48)
        for key in ("YARD_OPEN", "INBUILDSTANCE", "BUGGER_OFF"):
            self.assertEqual(rig.state(key), 0)
        refused = [e for e in rig.event_list("set") if e.key == rig.g.COB.YARD_OPEN and e.value == 1]
        self.assertGreater(len(refused), 1)
        self.assertTrue(all(not e.accepted and e.actual == 0 for e in refused))
        rig.g.world.allowOpen = True
        rig.advance(3)
        self.assert_open(rig)

    def test_build_callbacks_cannot_bypass_or_revoke_the_door_interlock(self):
        rig = FactoryHarness()
        marker = len(rig.g.events)
        u = rig.start_product()
        for _ in range(10):
            u.progress += 0.01
            rig.advance(3)
        rig.call("StopBuilding")
        self.assert_closed(rig)
        self.assert_home(rig)
        self.assertEqual(rig.event_list("set", marker), [])
        rig.open()
        marker = len(rig.g.events)
        rig.call("StartBuilding", 1.3, -0.8)
        rig.call("StopBuilding")
        self.assertEqual(rig.event_list("set", marker), [])
        self.assert_open(rig)

    def test_cancel_partial_open_closes_without_a_late_release(self):
        rig = FactoryHarness()
        rig.call("Activate")
        rig.advance(12)
        self.assertEqual(rig.call("Deactivate"), 0)
        self.assertAlmostEqual(rig.g.translation("DoorL")[0], -12)
        self.assertEqual(rig.state("INBUILDSTANCE"), 0)
        rig.advance(180)
        self.assert_closed(rig)
        self.assertGreater(rig.g.metrics.cancellations, 0)
        self.assertEqual(rig.g.liveThreads(2), 1)
        self.assertFalse(any(e.value == 1 for e in rig.event_list("set")))

    def test_open_close_open_reverses_from_the_interpolated_pose(self):
        rig = FactoryHarness()
        rig.open()
        rig.call("Deactivate")
        rig.advance(12)
        self.assertAlmostEqual(rig.g.translation("DoorL")[0], -36)
        rig.call("Activate")
        self.assertAlmostEqual(rig.g.translation("DoorL")[0], -36)
        self.assertEqual(rig.state("INBUILDSTANCE"), 0)
        rig.advance(11)
        self.assertEqual(rig.state("YARD_OPEN"), 0)
        rig.advance(1)
        self.assert_open(rig)
        rig.advance(180)
        self.assert_open(rig)
        self.assertEqual(rig.g.liveThreads(1), 0)
        self.assertEqual(rig.g.liveThreads(2), 1)

    def test_generation_guards_retire_waiters_even_with_lost_signals(self):
        rig = FactoryHarness()
        rig.g.world.dropSignals = True
        for call, delay in (("Activate", 9), ("Deactivate", 3), ("Activate", 1), ("Deactivate", 180)):
            rig.call(call)
            rig.advance(delay)
        self.assert_closed(rig)
        rig.open()
        rig.call("Deactivate")
        rig.advance(8)
        rig.call("Activate")
        rig.advance(180)
        self.assert_open(rig)
        self.assertEqual(rig.g.liveThreads(1), 0)
        self.assertEqual(rig.g.liveThreads(2), 1)

    def test_cancel_yard_wait_and_reenter_does_not_restore_old_intent(self):
        for lost_signals in (False, True):
            with self.subTest(lost_signals=lost_signals):
                rig = FactoryHarness()
                rig.g.world.dropSignals = lost_signals
                rig.g.world.allowOpen = False
                rig.call("Activate")
                rig.advance(90)
                rig.call("Deactivate")
                rig.advance(6)
                rig.call("Activate")
                rig.g.world.allowOpen = True
                rig.advance(180)
                self.assert_open(rig)
                self.assertEqual(rig.g.liveThreads(1), 0)

    def test_reopening_retires_a_refused_close_before_acceptance_changes(self):
        for lost_signals in (False, True):
            with self.subTest(lost_signals=lost_signals):
                rig = FactoryHarness()
                rig.open()
                rig.g.world.dropSignals = lost_signals
                rig.g.world.allowClose = False
                rig.call("Deactivate")
                rig.advance(30)
                self.assert_open(rig, ready=False)
                rig.call("Activate")
                rig.g.world.allowClose = True
                marker = len(rig.g.events)
                rig.advance(120)
                self.assert_open(rig)
                self.assertEqual(rig.g.liveThreads(1), 0)
                self.assertFalse(any(e.value == 0 and e.key == rig.g.COB.YARD_OPEN
                                     for e in rig.event_list("set", marker)))

    def test_completed_product_is_not_clear_on_stop_building(self):
        rig = FactoryHarness()
        rig.open()
        u = rig.start_product()
        u.progress = 1
        rig.g.world.target = None
        rig.call("StopBuilding")
        rig.call("Deactivate")
        rig.advance(120)
        self.assert_open(rig, ready=False)
        rig.place(20, z=rig.data.door.planeZWorld)
        rig.advance(30)
        self.assert_open(rig, ready=False)
        rig.place(20, z=rig.data.corridor.apronFrontZWorld + u.radius + 5)
        rig.advance(90)
        self.assert_closed(rig)

    def test_remembers_real_product_after_target_query_is_cleared(self):
        rig = FactoryHarness()
        rig.open()
        rig.start_product()
        rig.g.world.target = None
        rig.g.world.omitFromQuery = 20  # exercise retained target, independently of the scan
        rig.call("StopBuilding")
        rig.call("Deactivate")
        rig.advance(90)
        self.assert_open(rig, ready=False)
        rig.g.units[20].valid = False  # real cancellation/deletion, not a fabricated departure
        rig.advance(90)
        self.assert_closed(rig)

    def test_old_product_is_not_forgotten_when_the_next_product_appears(self):
        rig = FactoryHarness()
        rig.open()
        rig.start_product(20)
        rig.g.units[20].progress = 1
        rig.call("StopBuilding")
        rig.start_product(21)
        rig.call("Deactivate")
        rig.place(21, z=300)
        rig.advance(90)
        self.assert_open(rig, ready=False)
        rig.place(20, z=300)
        rig.advance(90)
        self.assert_closed(rig)

    def test_doorway_ground_unit_and_lateral_leaf_sweep_block_closing(self):
        for x, z in ((0, 52), (90, 52), (0, 85)):
            with self.subTest(x=x, z=z):
                rig = FactoryHarness()
                rig.open()
                rig.add_unit(30, x=x, z=z, radius=10)
                rig.call("Deactivate")
                rig.advance(90)
                self.assert_open(rig, ready=False)
                rig.place(30, x=300, z=300)
                rig.advance(90)
                self.assert_closed(rig)

    def test_cancelling_open_with_a_blocker_finishes_opening_for_clearance(self):
        rig = FactoryHarness()
        rig.call("Activate")
        rig.advance(10)
        rig.add_unit(30, z=52)
        rig.call("Deactivate")
        rig.advance(15)
        self.assertEqual(rig.state("BUGGER_OFF"), 0)
        self.assertEqual(rig.state("INBUILDSTANCE"), 0)
        rig.advance(60)
        self.assert_open(rig, ready=False)
        rig.g.units[30].dead = True
        rig.advance(90)
        self.assert_closed(rig)

    def test_refused_yard_close_keeps_physical_doors_open_until_accepted(self):
        rig = FactoryHarness()
        rig.open()
        rig.g.world.allowClose = False
        marker = len(rig.g.events)
        rig.call("Deactivate")
        rig.advance(150)
        self.assert_open(rig, ready=False)
        self.assertFalse(any(e.goal == 0 and e.piece in ("DoorL", "DoorR")
                             for e in rig.event_list("move", marker)))
        rig.g.world.allowClose = True
        rig.advance(3)
        self.assertEqual(rig.state("YARD_OPEN"), 0)
        self.assertEqual(rig.state("BUGGER_OFF"), 0)
        self.assertNotEqual(rig.g.translation("DoorL")[0], 0)
        rig.advance(60)
        self.assert_closed(rig)

    def test_m1a1_live_radius_and_model_midpoint_are_used_in_all_four_facings(self):
        sphere = model_bounds("m1a1")
        self.assertGreater(sphere["radius"], 40)
        for facing in range(4):
            with self.subTest(facing=facing):
                rig = FactoryHarness(facing=facing)
                rig.open()
                gap = (40 + sphere["radius"]) * 0.5
                z = rig.data.corridor.apronFrontZWorld + gap - sphere["midZ"]
                rig.add_unit(30, x=-sphere["midX"], z=z, model="m1a1", progress=1)
                rig.call("Deactivate")
                rig.advance(90)
                self.assert_open(rig, ready=False)
                self.assertGreater(rig.g.metrics.radiusReads[30], 0)
                # Move only the fixture. The controller has no product-control API.
                rig.place(30, x=-sphere["midX"],
                          z=rig.data.corridor.apronFrontZWorld + sphere["radius"] + 5 - sphere["midZ"])
                rig.advance(90)
                self.assert_closed(rig)

    def test_static_neighbour_footprints_do_not_block_a_distant_door(self):
        for facing in range(4):
            with self.subTest(facing=facing):
                rig = FactoryHarness(facing=facing)
                rig.open()
                rig.add_unit(30, x=192, def_id=3, model="vehicle_factory")
                rig.add_unit(31, z=160, def_id=3, model="vehicle_factory")
                rig.add_unit(32, z=-160, def_id=3, model="vehicle_factory")
                # A rotated rectangular neighbour must not reuse an unrotated box.
                rig.add_unit(33, z=176, def_id=3, model="vehicle_factory", facing=(facing+1) % 4)
                self.close_and_wait(rig)

    def test_static_unit_actually_in_the_doorway_is_not_ignored(self):
        rig = FactoryHarness()
        rig.open()
        rig.add_unit(30, z=52, def_id=3, model="vehicle_factory")
        rig.call("Deactivate")
        rig.advance(90)
        self.assert_open(rig, ready=False)
        rig.place(30, x=500, z=500)
        rig.advance(90)
        self.assert_closed(rig)

    def test_self_invalid_airborne_transported_and_remote_units_are_ignored(self):
        rig = FactoryHarness(facing=3)
        rig.open()
        rig.add_unit(30, z=52, valid=False)
        rig.add_unit(31, z=52, dead=True)
        rig.add_unit(32, z=52, def_id=999)
        rig.add_unit(33, z=52, positionAvailable=False)
        rig.add_unit(34, z=52, y=1000, def_id=4, radius=30)
        rig.add_unit(35, z=52, transporter=34)
        rig.add_unit(36, x=500, z=0)
        rig.add_unit(37, z=-300)
        rig.g.world.extraUnits = rig.lua.table_from([99999])
        self.close_and_wait(rig)  # GetAllUnits also always contains the factory itself

    def test_live_unknown_radius_and_missing_factory_basis_fail_closed(self):
        for missing in ("radius", "direction"):
            with self.subTest(missing=missing):
                rig = FactoryHarness()
                rig.open()
                if missing == "radius":
                    u = rig.add_unit(30, z=52)
                    u.radius = None
                else:
                    u = rig.g.units[FACTORY_ID]
                    u.fx, u.fz = 0, 0
                rig.call("Deactivate")
                rig.advance(90)
                self.assert_open(rig, ready=False)
                if missing == "radius":
                    u.radius = 16
                    rig.place(30, z=300)
                else:
                    u.fx, u.fz = rig.fx, rig.fz
                rig.advance(90)
                self.assert_closed(rig)

    def test_actual_progress_stall_and_resume_drive_work_not_elapsed_time(self):
        rig = FactoryHarness()
        rig.open()
        rig.call("StartBuilding", 0, 0)
        rig.advance(90)
        self.assert_home(rig)  # a callback without a target is insufficient
        u = rig.start_product(progress=0.2)
        rig.advance(60)
        self.assert_home(rig)  # a stationary progress value is insufficient too
        u.progress = 0.22
        rig.advance(3)
        self.assertTrue(rig.g.visible("WorkLamp"))
        first_goals = rig.work_goals()
        self.assertNotEqual(first_goals[0], 0)
        rig.advance(90)
        self.assert_home(rig)
        before = (rig.g.metrics.moves, rig.g.metrics.turns)
        rig.advance(90)
        self.assertEqual((rig.g.metrics.moves, rig.g.metrics.turns), before)
        u.progress = 0.24
        rig.advance(3)
        self.assertTrue(rig.g.visible("WorkLamp"))
        self.assertNotEqual(rig.work_goals(), first_goals)
        uninterrupted = FactoryHarness()
        uninterrupted.open()
        other = uninterrupted.start_product(progress=0.23)
        other.progress = 0.24
        uninterrupted.advance(3)
        for resumed, fresh in zip(rig.work_goals(), uninterrupted.work_goals()):
            self.assertAlmostEqual(resumed, fresh)
        self.assert_all_goals_in_rig(rig)

    def test_stop_building_homes_immediately_without_closing_or_revoking_stance(self):
        rig = FactoryHarness()
        rig.work()
        rig.call("StopBuilding")
        self.assertFalse(rig.g.visible("WorkLamp"))
        self.assert_open(rig)
        self.assertEqual(rig.g.goal("move", "Gantry", 3), rig.data.gantry.minMoveWorld)
        rig.advance(90)
        self.assert_home(rig)
        self.assert_open(rig)
        self.assertTrue(rig.g.units[20].valid)

    def test_cancel_death_invalid_health_completion_and_regression_home_work(self):
        for state in ("no-target", "invalid", "dead", "no-health", "zero-health", "no-progress",
                      "nan-progress", "complete", "regression"):
            with self.subTest(state=state):
                rig = FactoryHarness()
                u = rig.work()
                if state == "no-target":
                    rig.g.world.target = None
                elif state == "invalid":
                    u.valid = False
                elif state == "dead":
                    u.dead = True
                elif state == "no-health":
                    u.healthAvailable = False
                elif state == "zero-health":
                    u.health = 0
                elif state == "no-progress":
                    u.progress = None
                elif state == "nan-progress":
                    u.progress = float("nan")
                elif state == "complete":
                    u.progress = 1
                else:
                    u.progress = 0.1
                rig.advance(3)
                self.assertFalse(rig.g.visible("WorkLamp"))
                rig.advance(90)
                self.assert_home(rig)
                self.assert_open(rig)

    def test_replaced_target_needs_its_own_progress_sample(self):
        rig = FactoryHarness()
        rig.work()
        replacement = rig.add_unit(21, progress=0.8)
        rig.g.world.target = 21
        rig.advance(3)
        self.assertFalse(rig.g.visible("WorkLamp"))
        rig.advance(90)
        self.assert_home(rig)
        replacement.progress = 0.81
        rig.advance(3)
        self.assertTrue(rig.g.visible("WorkLamp"))

    def test_deactivate_pauses_work_and_reactivation_needs_fresh_progress(self):
        rig = FactoryHarness()
        u = rig.work()
        rig.call("Deactivate")
        rig.advance(3)
        self.assertFalse(rig.g.visible("WorkLamp"))
        self.assert_open(rig, ready=False)  # the actual product still occupies the lane
        u.progress = 0.23
        rig.advance(90)
        self.assert_home(rig)
        rig.call("Activate")
        rig.advance(6)
        self.assertFalse(rig.g.visible("WorkLamp"))
        self.assert_open(rig)
        u.progress = 0.24
        rig.advance(3)
        self.assertTrue(rig.g.visible("WorkLamp"))

    def test_queries_are_synchronous_stable_and_alternate_real_nano_nodes(self):
        rig = FactoryHarness(facing=1)
        build_world = tuple(rig.g.pieceWorld("BuildSpot"))
        expected = [rig.g.piece("NanoL"), rig.g.piece("NanoR")] * 5
        starts = rig.g.metrics.starts
        self.assertEqual([rig.call("QueryNanoPiece") for _ in range(10)], expected)
        self.assertEqual(rig.call("QueryBuildInfo"), rig.g.piece("BuildSpot"))
        self.assertEqual(rig.g.metrics.starts, starts)
        idle_nano = tuple(rig.g.pieceWorld("NanoL"))
        rig.work()
        rig.advance(8)
        self.assertNotEqual(tuple(rig.g.pieceWorld("NanoL")), idle_nano)
        self.assertEqual([rig.call("QueryNanoPiece") for _ in range(10)], expected)
        self.assertEqual(rig.call("QueryBuildInfo"), rig.g.piece("BuildSpot"))
        self.assert_root_stable(rig, build_world)

    def test_seeded_progress_and_rapid_callbacks_keep_all_rig_goals_bounded(self):
        rng = random.Random(612)
        rig = FactoryHarness(facing=2)
        build_world = tuple(rig.g.pieceWorld("BuildSpot"))
        rig.open()
        u = rig.start_product(progress=0)
        for _ in range(250):
            action = rng.randrange(12)
            if action == 0:
                rig.call("Deactivate")
            elif action == 1:
                rig.call("Activate")
            elif action == 2:
                rig.call("StopBuilding")
            elif action == 3:
                rig.call("StartBuilding", rng.uniform(-math.pi, math.pi), rng.uniform(-1, 1))
            elif action < 10:
                u.progress = (u.progress + rng.uniform(0.0001, 0.03)) % 0.99
            rig.advance(rng.randint(1, 9))
            self.assertEqual(rig.call("QueryBuildInfo"), rig.g.piece("BuildSpot"))
        self.assert_all_goals_in_rig(rig)
        self.assert_root_stable(rig, build_world)
        rig.call("StopBuilding")
        rig.advance(90)
        self.assert_home(rig)

    def test_death_cancels_threads_motors_and_work_without_new_wreck_logic(self):
        for state in ("opening", "yard-wait", "working", "blocked-close"):
            with self.subTest(state=state):
                rig = FactoryHarness()
                if state == "working" or state == "blocked-close":
                    rig.work()
                    if state == "blocked-close":
                        rig.g.world.allowClose = False
                        rig.call("Deactivate")
                else:
                    rig.g.world.allowOpen = state != "yard-wait"
                    rig.call("Activate")
                    rig.advance(12 if state == "opening" else 90)
                build_world = tuple(rig.g.pieceWorld("BuildSpot"))
                damage = 100 if state == "opening" else 700
                self.assertIsNone(rig.call("Killed", damage, 1000))
                self.assertEqual(rig.g.world.deathResult, 1 if damage == 100 else 2)
                self.assertEqual(rig.g.liveThreads(), 0)
                self.assertEqual(rig.state("INBUILDSTANCE"), 0)
                self.assertEqual(rig.state("BUGGER_OFF"), 0)
                self.assert_home(rig)
                channels = {(e.kind, e.piece, e.axis) for e in rig.event_list()
                            if e.kind in ("move", "turn")}
                for kind, name, axis in channels:
                    self.assertFalse(rig.g.isMoving(kind, name, axis))
                explosions = rig.event_list("explode")
                self.assertEqual(len(explosions), 1)
                self.assertEqual(explosions[0].piece, "Base")
                self.assertEqual(explosions[0].flags, rig.g.SFX.SHATTER)
                marker = len(rig.g.events)
                rig.call("Activate")
                rig.call("Deactivate")
                rig.call("StartBuilding", 0, 0)
                rig.call("StopBuilding")
                rig.advance(180)
                self.assertFalse([e for e in rig.event_list(since=marker)
                                  if e.kind in ("move", "turn", "set", "show", "explode")])
                self.assert_root_stable(rig, build_world)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lua-path", type=Path,
                        help="Existing directory containing lupa.lua51; nothing is installed")
    args, remaining = parser.parse_known_args()
    if args.lua_path:
        directory = args.lua_path.resolve()
        if not directory.is_dir():
            parser.error(f"Lua package directory does not exist: {directory}")
        sys.path.insert(0, str(directory))
    try:
        lua_runtime()
    except ImportError as error:
        print(f"NOT_RUN: Lua 5.1 controller tests require lupa.lua51 ({error}). "
              "Use --lua-path with an existing installation.", file=sys.stderr)
        return 2
    result = unittest.main(argv=[sys.argv[0], *remaining], exit=False).result
    print("NOT_RUN: native engine production/yard/pathfinding, visual and geometry acceptance.")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
