-- Units/mbt.lua
-- ZTZ-99A 风格测试坦克；tools/build_ztz99a.py 生成 S3O/GLB 和贴图。
local unitName = "mbt"

local unitDef = {
    name           = "ZTZ-99A",
    Description    = "ZTZ-99A style MBT with digital camouflage and a 125mm gun",
    ObjectName     = "ztz99a.s3o",
    script         = "mbtscript.lua",
    Side           = "Beefys",
    Category       = "LAND TANK NOTAIR NOTSUB",
    TEDClass       = "Vech",
    UnitName       = "ZTZ99A",
    BuildPic       = "ztz99a.png",
    SoundCategory  = "TANK",

    MaxDamage      = 2400,
    SightDistance  = 520,
    RadarDistance  = 0,
    -- Engine follows the ground. upDirSmoothing is clamped by the engine to
    -- [0, 0.95]; 0.95 is the slowest reaction, so a terrace edge takes ~1s to
    -- settle instead of snapping the hull over.
    Upright        = false,
    UpDirSmoothing = 0.95,

    BuildCostEnergy = 2400,
    BuildCostMetal  = 600,
    BuildTime       = 600,

    Acceleration   = 0.12,
    BrakeRate      = 0.10,
    FootprintX     = 3,
    FootprintZ     = 3,
    MaxSlope       = 20,
    MaxVelocity    = 2.6,
    MaxWaterDepth  = 10,
    MovementClass  = "3x3",
    TurnRate       = 900,

    Builder        = false,
    CanAttack      = true,
    CanGuard       = true,
    CanMove        = true,
    CanPatrol      = true,
    CanStop        = true,
    LeaveTracks    = false,
    Reclaimable    = false,

    collisionVolumeOffsets = "0 18 1",
    collisionVolumeScales  = "48 33 70",
    collisionVolumeType    = "box",

    BadTargetCategory = "",
    NoChaseCategory   = "AIR",

    weapons = {
        [1] = { name = "MBTGun" },
    },
}

return lowerkeys({ [unitName] = unitDef })
