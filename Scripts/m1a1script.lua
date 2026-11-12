-- M1A1 low-poly rig: turret, gun recoil, and seven-wheel differential tracks.
local Base   = piece "Base"
local Turret = piece "Turret"
local Gun    = piece "Gun"
local Flare  = piece "Flare"

local trackData = include("m1a1_track_data.lua")
local Tracks = include("track_animation.lua")(trackData, trackData.wheelCount)

local SIG_AIM = 2
local SIG_RECOIL = 16
local aimSpeed = math.rad(90)
local pitchSpeed = math.rad(60)

local function RestoreAfterDelay()
    Sleep(2000)
    Turn(Turret, y_axis, 0, aimSpeed)
    Turn(Gun, x_axis, 0, pitchSpeed)
    WaitForTurn(Turret, y_axis)
    WaitForTurn(Gun, x_axis)
end

function script.Create()
    -- The engine follows the ground; never add a second tilt or periodic bob.
    Move(Base, y_axis, 0, 0)
    Turn(Base, x_axis, 0, 0)
    Turn(Base, z_axis, 0, 0)
    Hide(Flare)
    Tracks.Start()
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
    Move(Gun, z_axis, -1.2, 24)
    WaitForMove(Gun, z_axis)
    Move(Gun, z_axis, 0, 5)
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
