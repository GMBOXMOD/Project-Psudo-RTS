-- Wiki: http://springrts.com/wiki/Movedefs.lua
-- See also; http://springrts.com/wiki/Units-UnitDefs#Tag:movementClass

local moveDefs 	=	 {
	{
		name			=	"2x2",
		footprintX		=	2,
		footprintZ		=	2,
		maxWaterDepth	=	10,
		maxSlope		=	20,
	},
	{
		name			=	"3x3",
		footprintX		=	3,
		footprintZ		=	3,
		maxWaterDepth	=	10,
		maxSlope		=	20,
	},
	{
		-- Six-legged engineer: legs climb what wheels cannot.
		name			=	"spider3x3",
		footprintX		=	3,
		footprintZ		=	3,
		maxWaterDepth	=	10,
		maxSlope		=	90,
	},
}

return moveDefs