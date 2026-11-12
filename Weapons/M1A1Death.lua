-- Explicit visual-only death effect for the M1A1 test unit.
local weaponName = "M1A1Death"

local weaponDef = {
    name               = "M1A1 wreck effect",
    weaponType         = "Cannon",
    areaOfEffect       = 0,
    damage             = { default = 0 },
    impulseFactor      = 0,
    craterMult         = 0,
    craterBoost        = 0,
    explosionGenerator = "custom:duronflash",
}

return lowerkeys({ [weaponName] = weaponDef })
