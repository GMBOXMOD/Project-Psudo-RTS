-- Weapons/ScoutGun.lua
-- Light autocannon for the FV-6: faster than the tank gun, much less punch.
local weaponName = "ScoutGun"

local weaponDef = {
    name             = "30mm Autocannon",
    weaponType       = "Cannon",
    range            = 430,
    reloadTime       = 0.9,
    weaponVelocity   = 700,
    damage           = { default = 65 },
    areaOfEffect     = 24,
    turret           = true,
    rgbColor         = "1 0.85 0.4",
    size             = 4,
    stages           = 16,
    separation       = 1,
    avoidFriendly    = true,
    avoidGround      = true,
    explosionGenerator = "custom:duronflash",
}

return lowerkeys({ [weaponName] = weaponDef })
