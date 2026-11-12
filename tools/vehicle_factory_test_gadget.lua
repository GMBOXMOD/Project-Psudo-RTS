-- Test-only synced fixture. Copied to an isolated dependent game by the runner.
-- Never change product positions, health/progress, build rates or unit scripts.
function gadget:GetInfo()
    return {name="Vehicle Factory native smoke", desc="Real factory production and departure",
            author="MyGame", layer=1000, enabled=true}
end
if not gadgetHandler:IsSyncedCode() then return false end

local config = VFS.Include("vehicle_factory_test_config.lua")
local data = VFS.Include("scripts/vehicle_factory_data.lua")
local us = Spring.UnitScript
local abs, min, max, sqrt = math.abs, math.min, math.max, math.sqrt
local checks, factories, factoryByID, products = {}, {}, {}, {}
local done, initialized, currentShot, shotSequence = false, false, nil, 0
local shotsRequested, shotsAcked = {}, {}
local frameNow = 0
local construction, stall, obstruction, collisionProbe
local neighbor
local fullStarted = false
local RegisterFactory, SetRally
local requiredShots = {}
for _, stage in ipairs(config.requiredShots) do requiredShots[stage] = true end

local function Json(value)
    local kind = type(value)
    if kind == "nil" then return "null" end
    if kind == "boolean" then return value and "true" or "false" end
    if kind == "number" then
        assert(value == value and abs(value) < math.huge, "Non-finite evidence value")
        return string.format("%.12g", value)
    end
    if kind == "string" then
        local escaped = value:gsub("\\", "\\\\"):gsub('"', '\\"')
            :gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t")
        return '"'..escaped..'"'
    end
    assert(kind == "table", "Unsupported evidence type "..kind)
    local result = {}
    if #value > 0 then
        for i = 1, #value do result[#result+1] = Json(value[i]) end
        return "["..table.concat(result, ",").."]"
    end
    local keys = {}
    for key in pairs(value) do keys[#keys+1] = key end
    table.sort(keys)
    for _, key in ipairs(keys) do result[#result+1] = Json(tostring(key))..":"..Json(value[key]) end
    return "{"..table.concat(result, ",").."}"
end

local function Log(event, values)
    values = values or {}
    values.event, values.frame, values.mode = event, frameNow, config.mode
    Spring.Echo("[VF_SMOKE] "..Json(values))
end

local function Check(name, passed, detail)
    assert(checks[name] == nil, "Duplicate check "..name)
    checks[name] = not not passed
    Log("check", {name=name, passed=checks[name], detail=detail})
end

local function RequestShot(stage, factory, unit, height, tx, tz)
    if shotsRequested[stage] then return true end
    if currentShot then return false end
    local code
    for i, name in ipairs(config.requiredShots) do if name == stage then code = i end end
    assert(code, "Unknown screenshot stage "..stage)
    shotSequence = shotSequence + 1
    currentShot = {stage=stage, seq=shotSequence, requested=frameNow}
    shotsRequested[stage] = true
    Spring.SetGameRulesParam("vf_shot_stage", code)
    Spring.SetGameRulesParam("vf_shot_factory", factory and factory.id or -1)
    Spring.SetGameRulesParam("vf_shot_unit", unit or -1)
    Spring.SetGameRulesParam("vf_shot_x", tx or (factory and factory.x) or 1536)
    Spring.SetGameRulesParam("vf_shot_y", factory and factory.y or 0)
    Spring.SetGameRulesParam("vf_shot_z", tz or (factory and factory.z) or 1536)
    Spring.SetGameRulesParam("vf_shot_height", height or 520)
    Spring.SetGameRulesParam("vf_shot_seq", shotSequence)
    Log("screenshot_request", {stage=stage, seq=shotSequence, factory=factory and factory.id, unit=unit})
    return true
end

function gadget:RecvLuaMsg(message, playerID)
    local sequence = tonumber(message:match("^vf_shot_ack:(%d+)$"))
    if sequence and playerID == 0 and currentShot and sequence == currentShot.seq then
        shotsAcked[currentShot.stage] = true
        Log("screenshot_ack", {stage=currentShot.stage, seq=sequence})
        currentShot = nil
    end
end

local function IsLive(id)
    return id and Spring.ValidUnitID(id) and not Spring.GetUnitIsDead(id)
end

local function LocalPoint(factory, x, y, z)
    local dx, dz = x-factory.x, z-factory.z
    return dx*factory.fz-dz*factory.fx, y-factory.y, dx*factory.fx+dz*factory.fz
end

local function WorldPoint(factory, x, z)
    return factory.x+x*factory.fz+z*factory.fx, factory.y, factory.z-x*factory.fx+z*factory.fz
end

local function NativeState(factory)
    local result = {}
    us.CallAsUnit(factory.id, function()
        local env = assert(us.GetScriptEnv(factory.id), "No native factory script environment")
        assert(env.COB and us.GetUnitValue, "No native COB readback interface")
        result.yard = us.GetUnitValue(env.COB.YARD_OPEN)
        result.stance = us.GetUnitValue(env.COB.INBUILDSTANCE)
        result.bugger = us.GetUnitValue(env.COB.BUGGER_OFF)
        result.left = us.GetPieceTranslation(factory.pieces.DoorL)
        result.right = us.GetPieceTranslation(factory.pieces.DoorR)
        local _, _, gantry = us.GetPieceTranslation(factory.pieces.Gantry)
        local _, ly = us.GetPieceTranslation(factory.pieces.HeadL)
        local _, ry = us.GetPieceTranslation(factory.pieces.HeadR)
        result.gantry, result.headL, result.headR = gantry, ly, ry
        local _, fan = us.GetPieceRotation(factory.pieces.FanL)
        result.fan = fan
    end)
    result.open = abs(result.left-data.door.leftOpenMoveWorld)<0.01
                  and abs(result.right-data.door.rightOpenMoveWorld)<0.01
    result.closed = abs(result.left)<0.01 and abs(result.right)<0.01
    result.rest = abs(result.gantry-data.gantry.minMoveWorld)<0.02
                  and abs(result.headL-data.heads.maxYMoveWorld)<0.02
                  and abs(result.headR-data.heads.maxYMoveWorld)<0.02
    return result
end

local function Envelope(id, name, factory)
    local origin = {Spring.GetUnitPosition(id)}
    local front, up, right = Spring.GetUnitVectors(id)
    assert(origin[1] and front and right, "No native unit transform")
    local pieces = Spring.GetUnitPieceMap(id)
    local lo, hi = {math.huge, math.huge, math.huge}, {-math.huge,-math.huge,-math.huge}
    local parts = {}
    local calibration, count = 0, 0
    for _, bounds in ipairs(config.bounds[name].pieces) do
        local pieceID = assert(pieces[bounds.name], "Missing product piece "..bounds.name)
        local matrix = {Spring.GetUnitPieceMatrix(id, pieceID)}
        assert(#matrix == 16, "Incomplete native piece matrix")
        local px, py, pz = Spring.GetUnitPiecePosition(id, pieceID)
        -- Engine GetUnitPiecePosition uses its right vector; the piece matrix
        -- keeps model +X. Verify this on the actual native data, not by guessing.
        calibration = max(calibration, abs(matrix[13]+px), abs(matrix[14]-py), abs(matrix[15]-pz))
        local part = {name=bounds.name, min={math.huge,math.huge,math.huge}, max={-math.huge,-math.huge,-math.huge}}
        for _, p in ipairs(bounds.corners) do
            local mx = matrix[1]*p[1]+matrix[5]*p[2]+matrix[9]*p[3]+matrix[13]
            local my = matrix[2]*p[1]+matrix[6]*p[2]+matrix[10]*p[3]+matrix[14]
            local mz = matrix[3]*p[1]+matrix[7]*p[2]+matrix[11]*p[3]+matrix[15]
            local wx = origin[1]-right[1]*mx+up[1]*my+front[1]*mz
            local wy = origin[2]-right[2]*mx+up[2]*my+front[2]*mz
            local wz = origin[3]-right[3]*mx+up[3]*my+front[3]*mz
            local x, y, z = LocalPoint(factory, wx, wy, wz)
            lo[1], lo[2], lo[3] = min(lo[1],x), min(lo[2],y), min(lo[3],z)
            hi[1], hi[2], hi[3] = max(hi[1],x), max(hi[2],y), max(hi[3],z)
            part.min[1], part.min[2], part.min[3] = min(part.min[1],x), min(part.min[2],y), min(part.min[3],z)
            part.max[1], part.max[2], part.max[3] = max(part.max[1],x), max(part.max[2],y), max(part.max[3],z)
            count = count+1
        end
        parts[#parts+1] = part
    end
    assert(count > 0 and calibration < 0.01, "Native piece/basis calibration failed: "..calibration)
    return {min=lo, max=hi, matrixError=calibration, corners=count}, parts
end

local function FactorySolids(factory)
    local boxes, matrices = {}, {}
    for _, solid in ipairs(config.solids) do
        local matrix = matrices[solid.piece]
        if not matrix then
            matrix = {Spring.GetUnitPieceMatrix(factory.id, factory.pieces[solid.piece])}
            assert(#matrix==16, "Missing factory matrix "..solid.piece)
            matrices[solid.piece] = matrix
        end
        local box = {name=solid.name,min={math.huge,math.huge,math.huge},max={-math.huge,-math.huge,-math.huge}}
        for _, x in ipairs({solid.min[1],solid.max[1]}) do
            for _, y in ipairs({solid.min[2],solid.max[2]}) do
                for _, z in ipairs({solid.min[3],solid.max[3]}) do
                    local p = {matrix[1]*x+matrix[5]*y+matrix[9]*z+matrix[13],
                               matrix[2]*x+matrix[6]*y+matrix[10]*z+matrix[14],
                               matrix[3]*x+matrix[7]*y+matrix[11]*z+matrix[15]}
                    for axis=1,3 do
                        box.min[axis], box.max[axis] = min(box.min[axis],p[axis]), max(box.max[axis],p[axis])
                    end
                end
            end
        end
        boxes[#boxes+1] = box
    end
    return boxes
end

local function Overlaps(a, b)
    for axis=1,3 do
        if a.max[axis] <= b.min[axis]+0.02 or a.min[axis] >= b.max[axis]-0.02 then return false end
    end
    return true
end

local function ObserveClearance(product, envelope, parts)
    product.geometrySamples = product.geometrySamples+1
    for _, solid in ipairs(product.factory.solids) do
        if Overlaps(envelope, solid) then
            for _, part in ipairs(parts) do
                if Overlaps(part,solid) then
                    product.geometryHits = product.geometryHits+1
                    local pair = part.name.." / "..solid.name
                    if not product.hitPairs[pair] then
                        product.hitPairs[pair] = true
                        Log("geometry_hit", {key=product.key,id=product.id,pair=pair,part=part,solid=solid,
                                             progress=product.previous,state=product.factory.state})
                    end
                end
            end
        end
    end
end

RegisterFactory = function(id, label, facing, team, role)
    local bx, by, bz = Spring.GetUnitPosition(id)
    local def = UnitDefNames.factory.id
    local fx, _, fz = Spring.GetUnitDirection(id)
    local factory = {id=id, label=label, facing=facing, team=team,
        x=bx, y=by, z=bz, fx=fx, fz=fz, pieces=Spring.GetUnitPieceMap(id), plan={},
        created={}, openingSamples=0, interlockViolations=0, stopSamples=0, registeredFrame=frameNow}
    factories[#factories+1], factoryByID[id] = factory, factory
    Log("fixture_unit", {id=id, role=role, label=label, facing=facing,
                         team=team, position={Spring.GetUnitPosition(id)}, buildProgress=select(5,Spring.GetUnitHealth(id))})
    local interface = Spring.GetUnitBuildFacing(id) == facing
    for _, piece in ipairs({"Base","DoorL","DoorR","Gantry","HeadL","HeadR","NanoL","NanoR","FanL","FanR","WorkLamp","BuildSpot"}) do
        interface = interface and factory.pieces[piece] ~= nil
    end
    local defData = UnitDefs[def]
    local names = {}
    for _, option in ipairs(defData.buildOptions or {}) do names[#names+1] = UnitDefs[option].name end
    for i, name in ipairs(config.catalogue) do interface = interface and names[i] == name end
    interface = interface and #names == #config.catalogue and defData.xsize == 24 and defData.zsize == 20
    Check(label.."_factory_00_interface", interface, {menu=names, xsize=defData.xsize,zsize=defData.zsize,square=Game.squareSize})
    local collision = {Spring.GetUnitCollisionVolumeData(id)}
    Check(label.."_factory_00_collision_size", abs(collision[1]-192)<0.01 and abs(collision[2]-83.5)<0.01
          and abs(collision[3]-156)<0.01 and abs(collision[4])+abs(collision[5])+abs(collision[6])<0.01,
          {native=collision, base_and_mid={Spring.GetUnitPosition(id,true)},
           s3o_midpoint=config.bounds.factory.midpoint, offset_reference="Established separately by native projectile boundary probes"})
    return factory
end

local function CreateFactory(label, facing, team, x, z)
    local def = UnitDefNames.factory.id
    local bx, by, bz = Spring.Pos2BuildPos(def, x, Spring.GetGroundHeight(x,z), z, facing)
    local id = assert(Spring.CreateUnit("factory", bx, by, bz, facing, team), "Factory fixture failed")
    return RegisterFactory(id,label,facing,team,"direct_created_completed_factory")
end

SetRally = function(factory, localX, localZ)
    local x, y, z = WorldPoint(factory, localX, localZ)
    factory.rally = {x,y,z}
    Spring.GiveOrderToUnit(factory.id, CMD.MOVE, factory.rally, {})
    Log("rally_order", {factory=factory.id, label=factory.label, target=factory.rally, options="none"})
end

local function AddProduct(factory, name, sequence)
    local product = {factory=factory, name=name, sequence=sequence, key=string.format("%s_%s_%02d",factory.label,name,sequence),
                     queuedFrame=frameNow, rally={unpack(factory.rally)}, advances=0, sawTarget=false,
                     geometrySamples=0, geometryHits=0, hitPairs={}}
    factory.plan[#factory.plan+1] = product
    -- Native factory build orders APPEND without SHIFT (SHIFT would add five).
    Spring.GiveOrderToUnit(factory.id, -UnitDefNames[name].id, {}, {})
    Log("build_order", {factory=factory.id, key=product.key, name=name, sequence=sequence, options="none"})
    return product
end

function gadget:UnitCreated(id, defID, team, builderID)
    if not initialized or not builderID then return end
    if construction and builderID==construction.builder and defID==UnitDefNames.factory.id then
        assert(not construction.id, "Repeated factory construction")
        construction.id, construction.createdFrame = id, frameNow
        construction.firstProgress = select(5,Spring.GetUnitHealth(id))
        Log("factory_construction_created", {id=id,builder=builderID,progress=construction.firstProgress,
                                             position={Spring.GetUnitPosition(id)}})
        return
    end
    local factory = factoryByID[builderID]
    if not factory then return end
    local index = #factory.created+1
    local product = factory.plan[index]
    local name = UnitDefs[defID].name
    if not product or product.name ~= name then
        Log("unexpected_product", {factory=builderID,id=id,index=index,name=name})
        return
    end
    factory.created[index], products[id] = product, product
    product.id, product.builderID, product.createdFrame = id, builderID, frameNow
    product.firstProgress = select(5, Spring.GetUnitHealth(id))
    if config.mode=="full" then
        local lateral = product.sequence==1 and 0 or (product.sequence%2==0 and -115 or 115)
        SetRally(factory,lateral,320+product.sequence*35)
        product.rally = {unpack(factory.rally)}
    end
    Spring.GiveOrderToUnit(id, CMD.FIRE_STATE, {0}, {})
    local entryState = NativeState(factory)
    product.entryState = entryState
    if not entryState.open or entryState.stance~=1 or entryState.yard~=1 then
        factory.interlockViolations = factory.interlockViolations+1
    end
    Log("product_created", {key=product.key,id=id,factory=builderID,progress=product.firstProgress,
                            role="native_factory_product",position={Spring.GetUnitPosition(id)},entryState=entryState})
end

function gadget:UnitFinished(id)
    if construction and id==construction.id then
        construction.finishedFrame = frameNow
        Log("factory_construction_finished", {id=id,builder=construction.builder,progress=select(5,Spring.GetUnitHealth(id))})
    end
    local product = products[id]
    if product then
        product.finishedCallin = frameNow
        Log("unit_finished_callin", {key=product.key,id=id,progress=select(5,Spring.GetUnitHealth(id))})
    end
end

function gadget:UnitFromFactory(id, defID, team, factoryID)
    local product = products[id]
    if product then
        product.fromFactory = factoryID
        Log("unit_from_factory", {key=product.key,id=id,factory=factoryID,progress=select(5,Spring.GetUnitHealth(id))})
    end
end

local function ObserveFactory(factory)
    local state = NativeState(factory)
    factory.state = state
    if frameNow%3==0 then factory.solids = FactorySolids(factory) end
    if factory.queuedFrame then
        if not state.open and not factory.gateFrame then
            factory.openingSamples = factory.openingSamples+1
            -- Native CFactory opens its yard before calling the visual script.
            -- INBUILDSTANCE, not a permanently closed yard, gates creation.
            if state.stance ~= 0 or Spring.GetUnitIsBuilding(factory.id) then
                factory.interlockViolations=factory.interlockViolations+1
            end
            if state.yard==1 then factory.earlyYardSamples=(factory.earlyYardSamples or 0)+1 end
        end
        if state.open and state.yard==1 and state.stance==1 and not factory.gateFrame then
            factory.gateFrame = frameNow
            Log("gate_release", {factory=factory.id,label=factory.label,state=state,waitFrames=frameNow-factory.queuedFrame})
        end
    end
    if frameNow % 30 == 0 then
        Log("factory_sample", {factory=factory.id,label=factory.label,state=state,target=Spring.GetUnitIsBuilding(factory.id)})
    end
    return state
end

local function ObserveProduct(product)
    if not IsLive(product.id) or product.rallyFrame then return end
    local factory = product.factory
    local _, _, _, _, progress = Spring.GetUnitHealth(product.id)
    if Spring.GetUnitIsBuilding(factory.id) == product.id then product.sawTarget = true end
    if product.previous and progress > product.previous+0.0000001 and progress < 1 then
        product.advances = product.advances+1
        if factory.state and not factory.state.rest then factory.sawWork = true end
    end
    product.previous = progress
    product.maxProgress = max(product.maxProgress or 0, progress)
    if progress >= 1 and not product.finishedFrame then
        product.finishedFrame = frameNow
        Log("product_finished", {key=product.key,id=product.id,progress=progress,
            elapsedFrames=frameNow-product.createdFrame,advances=product.advances})
    end
    if frameNow % 3 ~= 0 then return end
    local envelope, parts = Envelope(product.id, product.name, factory)
    product.envelope = envelope
    if not product.yardFrame then ObserveClearance(product,envelope,parts) end
    if progress >= 1 then
        if not product.doorFrame and envelope.min[3]>data.door.planeZWorld+data.door.leafThicknessWorld/2+1 then
            product.doorFrame = frameNow
            Log("door_clear", {key=product.key,id=product.id,progress=progress,envelope=envelope})
        end
        local yardFront = max(data.foundation.halfZWorld, data.footprint.worldZ/2)
        if not product.yardFrame and envelope.min[3]>yardFront+1 then
            product.yardFrame = frameNow
            Log("yard_clear", {key=product.key,id=product.id,progress=progress,envelope=envelope,yardFront=yardFront})
        end
        local x, _, z = Spring.GetUnitPosition(product.id)
        local distance = sqrt((x-product.rally[1])^2+(z-product.rally[3])^2)
        if product.yardFrame and distance<=32 and not product.rallyFrame then
            product.rallyFrame = frameNow
            Log("rally_arrival", {key=product.key,id=product.id,progress=progress,distance=distance,
                                   position={Spring.GetUnitPosition(product.id)},envelope=envelope})
        end
    end
    if frameNow%30==0 then
        Log("product_sample", {key=product.key,id=product.id,progress=progress,position={Spring.GetUnitPosition(product.id)},
                                envelope=envelope,target=Spring.GetUnitIsBuilding(factory.id)})
    end
end

local function CheckProduct(product)
    local key = product.key
    Check(key.."_native_product", product.id and product.builderID==product.factory.id and product.sawTarget
          and product.firstProgress and product.firstProgress<0.2,
          {id=product.id,builder=product.builderID,firstProgress=product.firstProgress,sawTarget=product.sawTarget})
    local elapsed = product.finishedFrame and product.finishedFrame-product.createdFrame
    local expectedFrames = config.buildTimes[product.name]/10*Game.gameSpeed
    Check(key.."_real_progress", product.advances>=10 and product.maxProgress and product.maxProgress>=1
          and elapsed and elapsed>=expectedFrames-30,
          {id=product.id,advances=product.advances,elapsedFrames=elapsed,minimumExpectedFrames=expectedFrames-30})
    Check(key.."_finished", product.finishedFrame and product.finishedCallin and product.fromFactory==product.factory.id,
          {id=product.id,finishedFrame=product.finishedFrame,finishedCallin=product.finishedCallin,fromFactory=product.fromFactory})
    Check(key.."_door_clear", product.doorFrame~=nil, {id=product.id,frame=product.doorFrame})
    Check(key.."_yard_clear", product.yardFrame~=nil, {id=product.id,frame=product.yardFrame})
    Check(key.."_rally", product.rallyFrame~=nil, {id=product.id,frame=product.rallyFrame,target=product.rally})
    Check(key.."_geometry_clear", product.geometrySamples>=10 and product.geometryHits==0,
          {id=product.id,samples=product.geometrySamples,hits=product.geometryHits,
           scope="10 Hz live piece boxes versus actual fixed components and moving machines; not unrestricted combat poses"})
end

local function Finish(reason)
    if done then return end
    for _, factory in ipairs(factories) do
        if factory.queuedFrame then
            Check(factory.label.."_factory_00_door_wait", factory.openingSamples>5 and factory.interlockViolations==0,
                  {samples=factory.openingSamples,violations=factory.interlockViolations,
                   enginePreopenedYardSamples=factory.earlyYardSamples or 0})
            Check(factory.label.."_factory_00_gate_release", factory.gateFrame~=nil,
                  {frame=factory.gateFrame,queuedFrame=factory.queuedFrame})
            Check(factory.label.."_factory_00_work_progress", factory.sawWork)
            Check(factory.label.."_factory_00_stop", factory.stopSamples>=15,
                  {restingClosedSamples=factory.stopSamples,state=factory.state})
            local queue = Spring.GetFactoryCommands(factory.id,-1) or {}
            Check(factory.label.."_factory_00_queue_exact", #factory.created==#factory.plan and #queue==0,
                  {actual=#factory.created,expected=#factory.plan,remaining=queue})
            for _, product in ipairs(factory.plan) do CheckProduct(product) end
        end
    end
    for _, name in ipairs(config.requiredChecks) do
        if checks[name] == nil then Check(name,false,"Phase not reached") end
    end
    Log("scenario_end", {reason=reason,checkCount=#config.requiredChecks,shotCount=shotSequence})
    done = true
    Spring.SetGameRulesParam("vf_done",1)
end

local function Setup()
    local y = Spring.GetGroundHeight(1536,1536)
    Spring.LevelHeightMap(768,768,min(3584,Game.mapSizeX-128),min(3584,Game.mapSizeZ-128),y)
    local flat = true
    for _, p in ipairs({{1024,1024},{1536,1536},{1792,1792},{2200,2200}}) do
        flat = flat and abs(Spring.GetGroundHeight(p[1],p[2])-y)<0.01
    end
    Check("fixture_flat",flat,{height=y,scope="isolated level patch only; arbitrary slopes NOT_RUN"})
    for _, team in ipairs({0,1}) do
        Spring.SetTeamResource(team,"ms",100000)
        Spring.SetTeamResource(team,"es",100000)
        Spring.SetTeamResource(team,"m",100000)
        Spring.SetTeamResource(team,"e",100000)
    end
    local economy = UnitDefs[UnitDefNames.factory.id].buildSpeed==10
        and UnitDefs[UnitDefNames.factory.id].buildTime==620 and UnitDefs[UnitDefNames.spider.id].buildSpeed==6
    local actual = {}
    for _, name in ipairs(config.catalogue) do
        actual[name] = UnitDefs[UnitDefNames[name].id].buildTime
        economy = economy and actual[name]==config.buildTimes[name]
    end
    Check("unchanged_economy",economy,{products=actual,factoryBuildTime=UnitDefs[UnitDefNames.factory.id].buildTime,
          factoryWorker=UnitDefs[UnitDefNames.factory.id].buildSpeed,spiderWorker=UnitDefs[UnitDefNames.spider.id].buildSpeed})
    initialized = true
    local factory
    if config.mode=="quick" then
        factory = CreateFactory("f0",0,0,1536,1536)
    else
        factory = CreateFactory("f0",0,0,2208,2896)
        CreateFactory("f1",1,1,2896,2208)
        CreateFactory("f2",2,0,2208,1440)
        CreateFactory("f3",3,1,1440,2208)
        local nx,ny,nz = Spring.Pos2BuildPos(UnitDefNames.factory.id,factory.x+224,factory.y,factory.z,0)
        local site = Spring.TestBuildOrder(UnitDefNames.factory.id,nx,ny,nz,0)
        neighbor = assert(Spring.CreateUnit("factory",nx,ny,nz,0,1), "Neighbor fixture failed")
        Check("neighbor_placement", site>0 and abs(nx-factory.x)>=192 and abs(nz-factory.z)<1,
              {id=neighbor,team=1,site=site,separation=abs(nx-factory.x),position={nx,ny,nz}})
        collisionProbe = {results={},byID={},index=0,rays={
            {factory=1,name="roof_inside",pos={0,79,200},speed={0,0,-12},hit=true},
            {factory=1,name="roof_outside",pos={0,81,200},speed={0,0,-12},hit=false},
            {factory=1,name="side_inside",pos={95,40,200},speed={0,0,-12},hit=true},
            {factory=1,name="side_outside",pos={97,40,200},speed={0,0,-12},hit=false},
            {factory=1,name="front_inside",pos={0,150,77},speed={0,-4.5,0},hit=true},
            {factory=1,name="front_outside",pos={0,150,79},speed={0,-4.5,0},hit=false},
            {factory=2,name="rotated_side_inside",pos={95,40,200},speed={0,0,-12},hit=true},
            {factory=2,name="rotated_side_outside",pos={97,40,200},speed={0,0,-12},hit=false},
            {factory=3,name="reversed_front_inside",pos={0,150,77},speed={0,-4.5,0},hit=true},
            {factory=3,name="reversed_front_outside",pos={0,150,79},speed={0,-4.5,0},hit=false},
            {factory=4,name="rotated_roof_inside",pos={0,79,200},speed={0,0,-12},hit=true},
            {factory=4,name="rotated_roof_outside",pos={0,81,200},speed={0,0,-12},hit=false},
        }}
    end
    Spring.SetGameRulesParam("vf_ready",1)
    Log("ready", {mode=config.mode,engine=Engine.version,gameSpeed=Game.gameSpeed,factory=factory.id,
                  installedDefinition=config.installedDefinition})
end

local function RunQuick()
    local factory = factories[1]
    local state = ObserveFactory(factory)
    if not factory.initialChecked and frameNow>=60 then
        factory.initialChecked = true
        Check("f0_factory_00_closed_initial",state.closed and state.yard==0 and state.stance==0 and state.rest,state)
        RequestShot("f0_factory_00_idle",factory,nil,540)
    end
    if shotsAcked.f0_factory_00_idle and not factory.queuedFrame then
        SetRally(factory,0,320)
        factory.queuedFrame = frameNow
        AddProduct(factory,"spider",1)
    end
    for _, product in ipairs(factory.plan) do
        ObserveProduct(product)
        if product.previous and product.previous>0.25 and product.previous<0.65 then
            RequestShot("f0_spider_01_production",factory,product.id,490)
        end
        if product.rallyFrame then
            local tx, _, tz = WorldPoint(factory,0,140)
            RequestShot("f0_spider_01_rally",factory,product.id,750,tx,tz)
        end
    end
    local product = factory.plan[1]
    if product and product.rallyFrame and state.closed and state.yard==0 and state.stance==0 and state.rest then
        factory.stopSamples = factory.stopSamples+1
    else
        factory.stopSamples = 0
    end
    if factory.stopSamples>=30 and shotsAcked.f0_spider_01_rally and not currentShot then Finish("finished") end
end

function gadget:UnitDamaged(id, defID, team, damage, paralyzer, weaponDefID, projectileID)
    if not collisionProbe or weaponDefID~=WeaponDefNames.vf_collision_probe.id then return end
    local ray = collisionProbe.byID[projectileID]
    if ray then
        ray.hitID = id
        ray.hitFrame = frameNow
        Log("collision_probe_hit", {name=ray.name,projectile=projectileID,id=id,damage=damage})
    end
end

local function RunCollisionProbe()
    local probe = collisionProbe
    if probe.complete then return true end
    local ray = probe.rays[probe.index]
    if ray and not ray.cleaned and frameNow-ray.started>=24 then
        local x,y,z = Spring.GetProjectilePosition(ray.projectile)
        if x then
            -- Expiring laser rounds call Collision too. Delete a surviving ray
            -- before expiry so proximity damage cannot masquerade as a box hit.
            Spring.DeleteProjectile(ray.projectile)
            Log("collision_probe_removed",{name=ray.name,projectile=ray.projectile,position={x,y,z},reason="before_ttl_expiry"})
        end
        ray.cleaned = true
    end
    if ray and frameNow-ray.started>=36 then
        local target = factories[ray.factory].id
        local actual = ray.hitID==target
        local result = {name=ray.name,factory=target,expectedHit=ray.hit,actualHit=actual,
                        projectile=ray.projectile,localPosition=ray.pos,localSpeed=ray.speed,hitID=ray.hitID}
        probe.results[#probe.results+1] = result
        Log("collision_probe_result",result)
        probe.current = nil
    elseif ray then
        return false
    end
    probe.index = probe.index+1
    ray = probe.rays[probe.index]
    if not ray then
        local passed = #probe.results==#probe.rays
        for _, result in ipairs(probe.results) do passed = passed and result.actualHit==result.expectedHit end
        Check("collision_reference",passed,{results=probe.results,
              reference="S3O midpoint plus configured offsets, rotated into world space; roof 80, side 96, front 78",
              method="Native projectile inside/outside boundary tests, not configuration getter alone"})
        probe.complete = true
        return true
    end
    local factory = factories[ray.factory]
    local x,_,z = WorldPoint(factory,ray.pos[1],ray.pos[3])
    local speed = {ray.speed[1]*factory.fz+ray.speed[3]*factory.fx,ray.speed[2],
                   -ray.speed[1]*factory.fx+ray.speed[3]*factory.fz}
    ray.started = frameNow
    ray.projectile = assert(Spring.SpawnProjectile(WeaponDefNames.vf_collision_probe.id,
        {pos={x,factory.y+ray.pos[2],z},speed=speed,ttl=120}), "Collision probe did not spawn")
    probe.byID[ray.projectile] = ray
    Log("collision_probe_shot",{name=ray.name,projectile=ray.projectile,factory=factory.id,
                               expectedHit=ray.hit,localPosition=ray.pos,localSpeed=ray.speed})
    return false
end

local function StartConstruction()
    local x,y,z = Spring.Pos2BuildPos(UnitDefNames.factory.id,1408,Spring.GetGroundHeight(1408,1408),1408,0)
    local builder = assert(Spring.CreateUnit("spider",x-170,y,z,0,0), "Engineer fixture failed")
    construction = {builder=builder,x=x,y=y,z=z,orderedFrame=frameNow,advances=0}
    Log("fixture_unit",{id=builder,role="construction_engineer",position={Spring.GetUnitPosition(builder)}})
    Spring.GiveOrderToUnit(builder,-UnitDefNames.factory.id,{x,y,z,0},{})
    Log("factory_construction_order",{builder=builder,target={x,y,z},facing=0,
                                      site=Spring.TestBuildOrder(UnitDefNames.factory.id,x,y,z,0),options="none"})
end

local function ObserveConstruction()
    if not construction or not IsLive(construction.id) then return end
    local c = construction
    local progress = select(5,Spring.GetUnitHealth(c.id))
    if c.previous and progress>c.previous+0.0000001 then c.advances=c.advances+1 end
    c.previous = progress
    if Spring.GetUnitIsBuilding(c.builder)==c.id then c.sawTarget=true end
    if frameNow%30==0 and not c.finishedFrame then
        Log("factory_construction_sample",{id=c.id,builder=c.builder,progress=progress,
                                            target=Spring.GetUnitIsBuilding(c.builder)})
    end
    if progress>0.15 and progress<0.65 then
        RequestShot("factory_under_construction",c,nil,740)
    end
    if c.finishedFrame and not c.factory then
        local elapsed = c.finishedFrame-c.createdFrame
        Check("spider_build_factory",c.firstProgress<0.01 and c.advances>50 and c.sawTarget
              and elapsed>=620/6*Game.gameSpeed-30 and progress==1,
              {id=c.id,builder=c.builder,firstProgress=c.firstProgress,progress=progress,
               advances=c.advances,sawTarget=c.sawTarget,elapsedFrames=elapsed})
        c.factory = RegisterFactory(c.id,"b0",0,0,"spider_built_completed_factory")
        Spring.GiveOrderToUnit(c.builder,CMD.MOVE,{c.x-230,c.y,c.z-170},{})
        Log("builder_departure_order",{id=c.builder,target={c.x-230,c.y,c.z-170},options="none"})
    end
end

local function SetFixtureResources(value)
    for _, team in ipairs({0,1}) do
        Spring.SetTeamResource(team,"m",value)
        Spring.SetTeamResource(team,"e",value)
    end
end

local function ObserveStall()
    local factory = factories[2]
    local product = factory.plan[5]
    if not product or not product.id then return end
    if not stall and product.previous and product.previous>0.22 and product.previous<0.7 then
        stall = {product=product,started=frameNow,progress=product.previous,stableSamples=0,restSamples=0}
        Log("resource_stall_start",{id=product.id,key=product.key,progress=product.previous,teams={0,1}})
    end
    if not stall then return end
    if not stall.released then
        SetFixtureResources(0)
        if frameNow-stall.started>60 then
            if abs(product.previous-stall.progress)<0.000001 then
                stall.stableSamples=stall.stableSamples+1
                if factory.state.rest and Spring.GetUnitIsBuilding(factory.id)==product.id then
                    stall.restSamples=stall.restSamples+1
                end
            else
                stall.progress, stall.stableSamples, stall.restSamples = product.previous,0,0
            end
        else
            stall.progress = product.previous
        end
        if stall.restSamples>=30 then
            RequestShot("f1_scout_05_stalled",factory,product.id,580)
        end
        if frameNow-stall.started>=270 and shotsAcked.f1_scout_05_stalled then
            Check("resource_stall",stall.stableSamples>=90 and stall.restSamples>=60,
                  {id=product.id,progress=product.previous,stableSamples=stall.stableSamples,restSamples=stall.restSamples,
                   target=Spring.GetUnitIsBuilding(factory.id),state=factory.state})
            stall.released, stall.resumeProgress = frameNow,product.previous
            SetFixtureResources(100000)
            Log("resource_stall_release",{id=product.id,key=product.key,progress=product.previous})
        end
    elseif not stall.recovered and product.previous>stall.resumeProgress+0.03 and not factory.state.rest then
        stall.recovered = frameNow
        Check("resource_recovery",Spring.GetUnitIsBuilding(factory.id)==product.id,
              {id=product.id,progress=product.previous,fromProgress=stall.resumeProgress,state=factory.state})
        Log("resource_stall_recovered",{id=product.id,key=product.key,progress=product.previous})
    end
end

local function ObserveObstruction()
    local factory = factories[1]
    local product = factory.plan[8]
    if not product or not product.id or not product.finishedFrame or not product.envelope then return end
    local x,y,z = Spring.GetUnitPosition(product.id)
    local _,_,localZ = LocalPoint(factory,x,y,z)
    if not obstruction and product.fromFactory==factory.id and localZ>=58
       and product.envelope.min[3]<data.door.planeZWorld+2 then
        Spring.GiveOrderToUnit(product.id,CMD.WAIT,{},{})
        obstruction = {product=product,started=frameNow,samples=0,closedSamples=0,stanceZeroSamples=0}
        Log("exit_obstruction_start",{id=product.id,key=product.key,position={x,y,z},envelope=product.envelope,command="WAIT"})
    end
    if not obstruction then return end
    if not obstruction.released then
        local atDoor = product.envelope.min[3]<data.door.planeZWorld+2
                       and product.envelope.max[3]>data.door.planeZWorld-2
        if frameNow-obstruction.started>=30 and atDoor then
            obstruction.samples = obstruction.samples+1
            if not factory.state.open or factory.state.yard~=1 then obstruction.closedSamples=obstruction.closedSamples+1 end
            if factory.state.stance==0 then obstruction.stanceZeroSamples=obstruction.stanceZeroSamples+1 end
            if obstruction.samples>=45 then RequestShot("f0_spider_08_blocked",factory,product.id,670) end
        end
        if frameNow-obstruction.started>=300 and shotsAcked.f0_spider_08_blocked then
            Check("exit_obstruction",obstruction.samples>=90 and obstruction.closedSamples==0,
                  {id=product.id,samples=obstruction.samples,prematureCloseSamples=obstruction.closedSamples,
                   stanceZeroSamples=obstruction.stanceZeroSamples,envelope=product.envelope,state=factory.state,
                   remainingQueue=Spring.GetFactoryCommands(factory.id,-1)})
            obstruction.released = frameNow
            Spring.GiveOrderToUnit(product.id,CMD.MOVE,product.rally,{})
            Log("exit_obstruction_release",{id=product.id,key=product.key,target=product.rally,command="MOVE"})
        end
    elseif not obstruction.recovered and product.rallyFrame and factory.stopSamples>=30 then
        obstruction.recovered = frameNow
        Check("exit_recovery",product.yardFrame>obstruction.released and product.rallyFrame>product.yardFrame,
              {id=product.id,releasedFrame=obstruction.released,yardFrame=product.yardFrame,rallyFrame=product.rallyFrame,
               state=factory.state})
    end
end

local function AllDeparted(factory)
    if #factory.plan==0 or #factory.plan~=#factory.created then return false end
    for _, product in ipairs(factory.plan) do if not product.rallyFrame then return false end end
    return true
end

local function RunFull()
    for _, factory in ipairs(factories) do
        local state = ObserveFactory(factory)
        if not factory.initialChecked and frameNow>=factory.registeredFrame+30 then
            factory.initialChecked = true
            Check(factory.label.."_factory_00_closed_initial",state.closed and state.yard==0 and state.stance==0 and state.rest,state)
        end
        for _, product in ipairs(factory.plan) do
            ObserveProduct(product)
            local stage = product.key.."_production"
            if requiredShots[stage] and product.previous and product.previous>0.18 and product.previous<0.75 then
                RequestShot(stage,factory,product.id,600)
            end
        end
        if AllDeparted(factory) and state.closed and state.yard==0 and state.stance==0 and state.rest then
            factory.stopSamples=factory.stopSamples+1
        else
            factory.stopSamples=0
        end
    end
    if not shotsRequested.f0_factory_00_idle and frameNow>=60 then
        local factory = factories[1]
        RequestShot("f0_factory_00_idle",factory,nil,880,factory.x+95,factory.z)
    end
    if not fullStarted and shotsAcked.f0_factory_00_idle and RunCollisionProbe() then
        fullStarted = true
        for _, factory in ipairs(factories) do
            SetRally(factory,0,355)
            factory.queuedFrame = frameNow
            for index,name in ipairs(config.catalogue) do AddProduct(factory,name,index) end
            if factory.label=="f0" then AddProduct(factory,"spider",7); AddProduct(factory,"spider",8) end
        end
        StartConstruction()
    end
    if not fullStarted then return end
    ObserveConstruction()
    if construction.factory and construction.factory.initialChecked and not construction.factory.queuedFrame then
        local factory = construction.factory
        SetRally(factory,0,355)
        factory.queuedFrame = frameNow
        AddProduct(factory,"spider",1)
    end
    ObserveStall()
    ObserveObstruction()
    local complete = #factories==5 and stall and stall.recovered and obstruction and obstruction.recovered
    for _, factory in ipairs(factories) do complete=complete and factory.stopSamples>=30 end
    if complete then
        if checks.rally_directions==nil then
            local left,right = false,false
            for _, product in ipairs(factories[1].plan) do
                local x = LocalPoint(factories[1],product.rally[1],product.rally[2],product.rally[3])
                left,right = left or x < -100,right or x > 100
            end
            Check("rally_directions",left and right,{left=left,right=right,actualRallyArrivals=#factories[1].plan})
        end
        local factory = factories[1]
        RequestShot("base_final",factory,nil,1150,factory.x+80,factory.z+200)
        local captured = not currentShot
        for _, stage in ipairs(config.requiredShots) do captured=captured and shotsAcked[stage] end
        if captured then Finish("finished") end
    end
end

function gadget:GameFrame(frame)
    if done then return end
    frameNow = frame
    local ok, err = pcall(function()
        if frame==30 then Setup() end
        if not initialized then return end
        if config.mode=="quick" then RunQuick() elseif config.mode=="full" then RunFull() else error("Unknown scenario") end
        if not done and frame>=config.maxFrames then Finish("simulation_timeout") end
    end)
    if not ok then
        done = true
        Spring.SetGameRulesParam("vf_done",1)
        -- The native synced sandbox deliberately has no debug.traceback.
        Log("error",{message=tostring(err)})
    end
end
