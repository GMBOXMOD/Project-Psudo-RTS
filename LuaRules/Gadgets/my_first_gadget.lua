--------------------------------------------------------------------------------
-- my_first_gadget.lua
-- 你的第一个 gadget —— Recoil 的游戏逻辑从这里开始
--
-- 放在 LuaRules/Gadgets/ 下就会自动加载，不需要任何注册
-- 运行在「同步端」：所有玩家电脑上跑同一份代码，必须算出完全一样的结果
--------------------------------------------------------------------------------

function gadget:GetInfo()
	return {
		name    = "My First Gadget",
		desc    = "每 10 秒给所有队伍加资源，并打印单位创建/销毁日志",
		author  = "me",
		date    = "2026-11-08",
		license = "GPL v3",
		layer   = 0,      -- 数字小的先加载，用来控制 gadget 之间的顺序
		enabled = true,   -- 默认启用
	}
end

-- LuaRules 会在「同步端」和「非同步端」各执行一次这个文件。
-- 下面这句的意思：如果当前是非同步端，直接退出，不要执行后面的代码。
if not gadgetHandler:IsSyncedCode() then
	return false
end

--------------------------------------------------------------------------------
-- 参数：改这几个数字就能改变行为
--------------------------------------------------------------------------------

local FRAMES_PER_SECOND = 30      -- Recoil 的模拟帧率固定 30 帧/秒
local INTERVAL_SECONDS  = 10      -- 每隔多少秒触发一次
local METAL_PER_TICK    = 10      -- 每次给多少金属
local ENERGY_PER_TICK   = 100     -- 每次给多少能量

--------------------------------------------------------------------------------
-- call-in：引擎会在特定时机自动调用下面这些函数（函数名不能改）
--------------------------------------------------------------------------------

-- 游戏开始时调用一次
function gadget:GameStart()
	Spring.Echo("[MyGame] 游戏开始！地图：" .. Game.mapName)
	Spring.CreateUnit("factory", 1606, Spring.GetGroundHeight(1606,1576), 1576, "north", 0)
	Spring.CreateUnit("m1a1", 1700, Spring.GetGroundHeight(1700,1660), 1660, "west", 0)
end

-- 每个模拟帧调用一次（每秒 30 次）。用计数器自己控制触发频率。
local frameCounter = 0

function gadget:GameFrame(frame)
	frameCounter = frameCounter + 1

	if frameCounter < FRAMES_PER_SECOND * INTERVAL_SECONDS then
		return
	end
	frameCounter = 0

	-- GetTeamList() 返回当前所有队伍 ID 的数组
	local teams = Spring.GetTeamList()

	for i = 1, #teams do
		local teamID = teams[i]
		Spring.AddTeamResource(teamID, "m", METAL_PER_TICK)
		Spring.AddTeamResource(teamID, "e", ENERGY_PER_TICK)
	end

	local seconds = math.floor(frame / FRAMES_PER_SECOND)
	Spring.Echo("[MyGame] " .. seconds .. " 秒：全员 +"
		.. METAL_PER_TICK .. " 金属 +" .. ENERGY_PER_TICK .. " 能量")
end

-- 有单位被创建出来时调用
function gadget:UnitCreated(unitID, unitDefID, teamID)
	local def = UnitDefs[unitDefID]
	if def then
		Spring.Echo("[MyGame] 队伍 " .. teamID .. " 造出了 " .. def.name)
	end
end

-- 单位被摧毁时调用
function gadget:UnitDestroyed(unitID, unitDefID, teamID)
	local def = UnitDefs[unitDefID]
	if def then
		Spring.Echo("[MyGame] 队伍 " .. teamID .. " 损失了 " .. def.name)
	end
end
