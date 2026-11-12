-- Scripts/scoutscript.lua
-- FV-6 Scout: autocannon turret, gun recoil, six wheels driven by real travel.
-- Piece names match Objects3d/scout.s3o and the editable scout.glb export.
local Base   = piece "Base"
local Turret = piece "Turret"
local Gun    = piece "Gun"
local Flare  = piece "Flare"

local Wheels = include("wheel_animation.lua")(include("scout_rig_data.lua"))

local SIG_AIM    = 2
local SIG_RECOIL = 16

local aimSpeed   = math.rad(120)
local pitchSpeed = math.rad(90)

local function RestoreAfterDelay()
    Sleep(2000)
    Turn(Turret, y_axis, 0, aimSpeed)
    Turn(Gun, x_axis, 0, pitchSpeed)
    WaitForTurn(Turret, y_axis)
    WaitForTurn(Gun, x_axis)
end

function script.Create()
    -- The engine already follows the ground; never add a second tilt or a bob.
    Move(Base, y_axis, 0, 0)
    Turn(Base, x_axis, 0, 0)
    Turn(Base, z_axis, 0, 0)
    Hide(Flare)
    Wheels.Start()
end

function script.AimWeapon(weaponID, heading, pitch)
    Signal(SIG_AIM)
    SetSignalMask(SIG_AIM)
    Turn(Turret, y_axis, heading, aimSpeed)
    Turn(Gun, x_axis, -pitch, pitchSpeed)
    WaitForTurn(Turret, y_axis)
    WaitForTurn(Gun, x_axis)
    StartThread(RestoreAfterDelay)
    return true
end

local function Recoil()
    Signal(SIG_RECOIL)
    SetSignalMask(SIG_RECOIL)
    Move(Gun, z_axis, -0.7, 30)
    WaitForMove(Gun, z_axis)
    Move(Gun, z_axis, 0, 8)
end

function script.FireWeapon(weaponID)
    EmitSfx(Flare, 0)
    StartThread(Recoil)
end

function script.QueryWeapon()
    return Flare
end

function script.AimFromWeapon()
    return Gun
end

function script.Killed(recentDamage, maxHealth)
    return 0
end
