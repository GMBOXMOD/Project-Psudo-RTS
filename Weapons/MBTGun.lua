-- Weapons/MBTGun.lua
-- 125mm 主炮，挂在 MBT 的第 1 号武器位
local weaponName = "MBTGun"

local weaponDef = {
    name             = "125mm Cannon",
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
