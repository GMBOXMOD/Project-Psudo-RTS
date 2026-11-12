-- Test-only gadget copied into a temporary dependent game by smoke_spider.py.
function gadget:GetInfo()
    return {name="Spider animation smoke", desc="Native tripod and builder checks",
            author="MyGame", layer=1000, enabled=true}
end
if not gadgetHandler:IsSyncedCode() then return false end

local config = VFS.Include("spider_smoke_config.lua")
local data = VFS.Include("scripts/spider_rig_data.lua")
local us = Spring.UnitScript
local abs, max, sqrt = math.abs, math.max, math.sqrt
local unit, pieces, previous, done
local x, y, z, yaw = 1024, 0, 1024, 0
local maxCoordinates, maxLifted, maxRestart, minGap = 0, 0, 0, 0
local maxForwardSlip, maxReverseSlip, maxStopped, maxBase = 0, 0, 0, 0
local stoppedSamples, idleLifted = 0, 0
local forwardSamples, reverseSamples, pivotSamples, wrongPivot = 0, 0, 0, 0
local buildUnit, buildProgress, built, buildArms, nanoOK, menuOK
local moveStart, moveFrame, movedAfterBuild, gaitAfterBuild

local function Basis()
    -- Piece matrices retain model +X. GetUnitPiecePosition flips X for the
    -- engine's right vector; GetUnitPiecePosDir is an emitter, not the pivot.
    local front, up, right = Spring.GetUnitVectors(unit)
    return {origin={Spring.GetUnitPosition(unit)},
            ex={-right[1],-right[2],-right[3]}, ey=up, ez=front}
end

local function World(basis, p)
    local out = {}
    for i = 1, 3 do
        out[i] = basis.origin[i] + basis.ex[i]*p[1] + basis.ey[i]*p[2] + basis.ez[i]*p[3]
    end
    return out
end

local function Sample()
    local result = {basis=Basis(), feet={}}
    local grounded = {}
    us.CallAsUnit(unit, function()
        local bx, by, bz = us.GetPieceTranslation(pieces.Base)
        local rx, ry, rz = us.GetPieceRotation(pieces.Base)
        maxBase = max(maxBase, abs(bx), abs(by), abs(bz), abs(rx), abs(ry), abs(rz))
        for _, leg in ipairs(data.legs) do
            local _, _, angle = us.GetPieceRotation(pieces[leg.knee])
            grounded[leg.knee] = abs((angle+math.pi)%(2*math.pi)-math.pi) < 0.0001
        end
    end)
    for _, leg in ipairs(data.legs) do
        local m = {Spring.GetUnitPieceMatrix(unit, pieces[leg.knee])}
        local localFoot = {m[1]*data.foot.x+m[5]*data.foot.y+m[13],
                           m[2]*data.foot.x+m[6]*data.foot.y+m[14],
                           m[3]*data.foot.x+m[7]*data.foot.y+m[15]}
        local worldFoot = World(result.basis, localFoot)
        local px, py, pz = Spring.GetUnitPiecePosition(unit, pieces[leg.knee])
        maxCoordinates = max(maxCoordinates, abs(m[13]+px), abs(m[14]-py), abs(m[15]-pz))
        result.feet[leg.knee] = {p=localFoot, world=worldFoot, grounded=grounded[leg.knee],
                                gap=worldFoot[2]-Spring.GetGroundHeight(worldFoot[1],worldFoot[3])}
    end
    return result
end

local function Observe(frame)
    local current = Sample()
    local lifted = 0
    local fx, _, fz = Spring.GetUnitDirection(unit)
    for name, foot in pairs(current.feet) do
        minGap = math.min(minGap, foot.gap)
        if foot.gap > 0.12 then lifted = lifted + 1 end
        local old = previous and previous.feet[name]
        if old and foot.grounded and old.grounded then
            local dx, dz = foot.world[1]-old.world[1], foot.world[3]-old.world[3]
            if frame >= 195 and frame <= 268 then
                forwardSamples = forwardSamples + 1
                maxForwardSlip = max(maxForwardSlip, abs(dx*fx+dz*fz))
            elseif frame >= 465 and frame <= 538 then
                reverseSamples = reverseSamples + 1
                maxReverseSlip = max(maxReverseSlip, abs(dx*fx+dz*fz))
            elseif frame >= 335 and frame <= 408 then
                pivotSamples = pivotSamples + 1
                local carried = World(current.basis, old.p)
                local bx, bz = carried[1]-old.world[1], carried[3]-old.world[3]
                local rx, rz = foot.world[1]-carried[1], foot.world[3]-carried[3]
                if bx*rx+bz*rz >= -0.000001 then wrongPivot = wrongPivot + 1 end
            end
        end
        if old and frame >= 785 and frame <= 815 then
            local dx, dy, dz = foot.world[1]-old.world[1], foot.world[2]-old.world[2], foot.world[3]-old.world[3]
            maxStopped = max(maxStopped, sqrt(dx*dx+dy*dy+dz*dz))
            stoppedSamples = stoppedSamples + 1
        end
    end
    if frame >= 785 and frame <= 815 then idleLifted = max(idleLifted, lifted) end
    maxLifted = max(maxLifted, lifted)
    if frame >= 132 and frame <= 155 then maxRestart = max(maxRestart, lifted) end
    previous = current
end

local function Check(name, passed)
    Spring.Echo("[SPIDER_SMOKE] CHECK "..name.."="..tostring(not not passed))
end

local function Finish()
    Check("native_coordinates", maxCoordinates < 0.01)
    Check("tripod_support", maxLifted <= 3 and maxLifted > 0)
    Check("restart_support", maxRestart <= 3 and maxRestart > 0)
    Check("feet_above_ground", minGap > -0.15)
    Check("forward_contact", forwardSamples > 100 and maxForwardSlip < 0.06)
    Check("reverse_contact", reverseSamples > 100 and maxReverseSlip < 0.06)
    Check("pivot_direction", pivotSamples > 100 and wrongPivot == 0)
    Check("stopped", stoppedSamples > 120 and idleLifted == 0 and maxStopped < 0.02)
    Check("stable_chassis", maxBase < 0.0001)
    if not config.gaitOnly then
        Check("build_menu", menuOK)
        Check("construction_progress", buildProgress and buildProgress > 0.1)
        Check("construction_complete", built)
        Check("build_arms", buildArms)
        Check("nano_emitters", nanoOK)
        Check("move_after_build", movedAfterBuild)
    end
    Spring.Echo(string.format("[SPIDER_SMOKE] geometry_error=%.6f max_lifted=%d restart_lifted=%d min_gap=%.6f",
                              maxCoordinates, maxLifted, maxRestart, minGap))
    Spring.Echo(string.format("[SPIDER_SMOKE] forward_slip=%.6f reverse_slip=%.6f wrong_pivot=%d/%d idle_drift=%.6f",
                              maxForwardSlip, maxReverseSlip, wrongPivot, pivotSamples, maxStopped))
    done = true
    Spring.SetGameRulesParam("spider_smoke_done", 1)
end

local function StartBuild()
    Spring.MoveCtrl.Disable(unit)
    Spring.GiveOrderToUnit(unit, CMD.STOP, {}, {})
    Spring.SetTeamResource(0, "ms", 10000)
    Spring.SetTeamResource(0, "es", 10000)
    Spring.SetTeamResource(0, "m", 10000)
    Spring.SetTeamResource(0, "e", 10000)
    local ux, uy, uz = Spring.GetUnitPosition(unit)
    for _, delta in ipairs({{0,80},{80,0},{0,-80},{-80,0},{64,64},{-64,-64}}) do
        local bx, by, bz = Spring.Pos2BuildPos(UnitDefNames.llt.id, ux+delta[1], uy, uz+delta[2], 0)
        local valid = Spring.TestBuildOrder(UnitDefNames.llt.id, bx, by, bz, 0)
        if valid == 2 then
            Spring.GiveOrderToUnit(unit, -UnitDefNames.llt.id, {bx,by,bz,0}, {})
            Spring.Echo("[SPIDER_SMOKE] build_order test_result="..valid.." x="..bx.." z="..bz)
            return
        end
    end
    error("No free LLT site on the isolated test patch")
end

local function RunFrame(frame)
    if frame == 30 then
        -- The patch is test-fixture terrain, never a change to the map archive.
        y = Spring.GetGroundHeight(x,z)
        Spring.LevelHeightMap(768,768,1408,1408,y)
        unit = Spring.CreateUnit("spider",x,y,z,0,0)
        assert(unit, "Missing test spider")
        pieces = Spring.GetUnitPieceMap(unit)
        Spring.MoveCtrl.Enable(unit)
        Spring.MoveCtrl.SetVelocity(unit,0,0,0)
        Spring.MoveCtrl.SetRotation(unit,0,0,0)
        Spring.MoveCtrl.SetPosition(unit,x,y,z)
        Spring.GiveOrderToUnit(unit,CMD.FIRE_STATE,{0},{})
        Spring.SetGameRulesParam("spider_smoke_unit",unit)
        local available = {}
        for _, desc in ipairs(Spring.GetUnitCmdDescs(unit)) do available[desc.id] = true end
        menuOK = true
        for _, name in ipairs({"extractor","energyreactor","llt","factory"}) do
            menuOK = menuOK and available[-UnitDefNames[name].id]
        end
        Spring.Echo("[SPIDER_SMOKE] ready")
    end
    if not unit then return end
    local distance, turn = 0, 0
    if (frame >= 90 and frame <= 101) or (frame >= 132 and frame <= 143)
       or (frame >= 180 and frame <= 269) then
        distance = 0.5
    elseif frame >= 320 and frame <= 409 then
        turn = 0.015
    elseif frame >= 450 and frame <= 539 then
        distance = -0.5
    elseif frame >= 590 and frame <= 709 then
        distance, turn = 0.4, 0.01
    elseif frame >= 730 and frame <= 759 then
        turn = 0.025 -- crosses the signed heading wrap
    end
    if frame <= 820 and (distance ~= 0 or turn ~= 0) then
        x, z = x+math.sin(yaw+turn*0.5)*distance, z+math.cos(yaw+turn*0.5)*distance
        yaw = yaw + turn
        Spring.MoveCtrl.SetRotation(unit,0,-yaw,0)
        Spring.MoveCtrl.SetPosition(unit,x,y,z)
    end
    if frame >= 60 and frame <= 820 then Observe(frame) end
    if frame == 820 then
        if config.gaitOnly then Finish() else StartBuild() end
    end
    if frame > 820 and not config.gaitOnly then
        local target = Spring.GetUnitIsBuilding(unit)
        if target then
            buildUnit = target
            local _, _, _, _, progress = Spring.GetUnitHealth(target)
            buildProgress = max(buildProgress or 0, progress or 0)
            us.CallAsUnit(unit,function()
                local a = us.GetPieceRotation(pieces.ArmL)
                local b = us.GetPieceRotation(pieces.ArmR)
                buildArms = buildArms or (abs(a)>0.05 and abs(b)>0.05 and abs(a-b)>0.02)
                local env = us.GetScriptEnv(unit)
                local first, second = env.script.QueryNanoPiece(), env.script.QueryNanoPiece()
                nanoOK = (first==pieces.NanoL and second==pieces.NanoR)
                         or (first==pieces.NanoR and second==pieces.NanoL)
            end)
            if buildProgress > 0.1 then Spring.SetGameRulesParam("spider_smoke_build_shot",1) end
        end
        if buildUnit and not built then
            local _, _, _, _, progress = Spring.GetUnitHealth(buildUnit)
            if progress and progress >= 1 then
                built = true
                Spring.Echo("[SPIDER_SMOKE] construction_complete frame="..frame)
                local ux, uy, uz = Spring.GetUnitPosition(unit)
                moveStart, moveFrame = {ux,uy,uz}, frame
                Spring.GiveOrderToUnit(unit,CMD.MOVE,{ux+65,uy,uz},{})
            end
        end
        if built then
            us.CallAsUnit(unit,function()
                for _, leg in ipairs(data.legs) do
                    local _, _, angle = us.GetPieceRotation(pieces[leg.knee])
                    gaitAfterBuild = gaitAfterBuild or abs((angle+math.pi)%(2*math.pi)-math.pi) > 0.02
                end
            end)
        end
        if built and frame >= moveFrame+90 then
            local ux, _, uz = Spring.GetUnitPosition(unit)
            movedAfterBuild = (ux-moveStart[1])^2+(uz-moveStart[3])^2 > 25 and gaitAfterBuild
            Finish()
        elseif frame >= 2200 then
            Finish()
        end
    end
end

function gadget:GameFrame(frame)
    if done then return end
    local ok, err = pcall(RunFrame, frame)
    if not ok then
        Spring.Echo("[SPIDER_SMOKE] ERROR "..tostring(err))
        done = true
        Spring.SetGameRulesParam("spider_smoke_done",1)
    end
end
