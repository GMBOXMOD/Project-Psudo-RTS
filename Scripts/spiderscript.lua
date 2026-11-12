-- Scripts/spiderscript.lua
-- SP-6 Engineer: six-legged gait, two construction arms and the nano emitters.
-- Piece names match Objects3d/spider.s3o and the editable spider.glb export.
local Base = piece "Base"

local ArmL, ArmR = piece "ArmL", piece "ArmR"
local ForearmL, ForearmR = piece "ForearmL", piece "ForearmR"
local NanoL, NanoR = piece "NanoL", piece "NanoR"

local Gait = include("spider_gait.lua")(include("spider_rig_data.lua"))

local SIG_BUILD = 4
local building = false
local nanoSide = false

local function RestPose()
    Turn(ArmL, x_axis, 0, 4)
    Turn(ArmR, x_axis, 0, 4)
    Turn(ForearmL, x_axis, 0, 4)
    Turn(ForearmR, x_axis, 0, 4)
end

local function BuildLoop()
    while building do
        Turn(ArmL, x_axis, math.rad(-7), 5)
        Turn(ArmR, x_axis, math.rad(-16), 5)
        Turn(ForearmL, x_axis, math.rad(5), 5)
        Turn(ForearmR, x_axis, math.rad(14), 5)
        Sleep(360)
        if not building then break end
        Turn(ArmL, x_axis, math.rad(-16), 5)
        Turn(ArmR, x_axis, math.rad(-7), 5)
        Turn(ForearmL, x_axis, math.rad(14), 5)
        Turn(ForearmR, x_axis, math.rad(5), 5)
        Sleep(360)
    end
end

function script.Create()
    -- The engine follows the ground; never add a second tilt or a periodic bob.
    Move(Base, y_axis, 0, 0)
    Turn(Base, x_axis, 0, 0)
    Turn(Base, z_axis, 0, 0)
    RestPose()
    Gait.Rest()
    Gait.Start()
end

function script.StartBuilding(heading, pitch)
    Signal(SIG_BUILD)
    SetSignalMask(SIG_BUILD)
    SetUnitValue(COB.INBUILDSTANCE, 1)
    building = true
    StartThread(BuildLoop)
end

function script.StopBuilding()
    SetUnitValue(COB.INBUILDSTANCE, 0)
    building = false
    Signal(SIG_BUILD)
    RestPose()
end

-- The engine draws the nano spray from the returned piece; alternate the arms.
function script.QueryNanoPiece()
    nanoSide = not nanoSide
    return nanoSide and NanoL or NanoR
end

function script.Killed(recentDamage, maxHealth)
    return 0
end
