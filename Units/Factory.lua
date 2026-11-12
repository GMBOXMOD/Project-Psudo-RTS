local unitName  =  "factory"

local unitDef  =  {
--Internal settings
BuildPic = "vehicle_factory.png",
    Category = "BUILDING LAND NOTAIR NOTSUB",
    ObjectName = "vehicle_factory.s3o",
    name = "Vehicle Factory",
    Side = "Beffys",
    TEDClass = "Building",
    UnitName = "Factory1",
    script = "vehicle_factoryscript.lua",
	--corpse = [[groundfactory_dead]],
--Unit limitations and properties
    Description = "Vehicle assembly workshop with a sheltered production bay.",
    MaxDamage = 3000,
    idleTime = 0,
    idleAutoHeal = 0,
    RadarDistance = 0,
    SightDistance = 600,
    SoundCategory = "Building",
    Upright = 1,
	maxWaterDepth = 4,
--Energy and metal related
    BuildCostEnergy = 1550,
    BuildCostMetal = 620,
    Buildtime = 620, 
--Size and Abilites
   MaxSlope = 33,
   FootprintX = 12,
   FootprintZ = 10,
   canSelfDestruct = 1,
   repairable = 1,
   CanMove = 1,
   CanPatrol = 0,
 --Building
 Builder = true,
canBeAssisted = true,
canAssist = false,
ShowNanoSpray = true,
CanBeAssisted = true,
canCapture = false,
canResurrect = false,
canReclaim = false,
canRepair = true,
canRestore = false,	
workerTime = 10,
buildoptions = 
	{
	[[spider]],
	[[stumpy]],
	[[flare]],
	[[duron]],
    [[scout]],
    [[m1a1]],
	},
	--Hitbox
collisionVolumeOffsets    =  "0 0 0",
collisionVolumeScales     =  "192 83.5 156",
collisionVolumeType       =  "box",
	YardMap ="oooooooooooo oooooooooooo ooooccccoooo ooooccccoooo ooooccccoooo ooooccccoooo ooooccccoooo ooooccccoooo ooooccccoooo ooooccccoooo",
--Weapons and related
	explodeAs = [[FactoryExplosion]],
	selfDestructAs = [[FactoryExplosion]],
    


}

return lowerkeys({ [unitName]  =  unitDef })