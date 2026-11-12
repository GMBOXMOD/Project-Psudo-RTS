-- Separate display name for the M1A1; same sandbox balance as the existing MBT.
local weaponName = "M1A1Gun"

local weaponDef = {
    name             = "120mm Cannon",
    weaponType       = "Cannon",
    range            = 620,
    reloadTime       = 3.2,
    weaponVelocity   = 500,
    damage           = { default = 350 },
    areaOfEffect     = 64,
    turret           = true,
    rgbColor         = "1 0.85 0.4",
    size             = 6,
    stages           = 20,
    separation       = 1,
    avoidFriendly    = true,
    avoidGround      = true,
    explosionGenerator = "custom:duronflash",
}

return lowerkeys({ [weaponName] = weaponDef })
