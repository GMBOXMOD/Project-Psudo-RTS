-- Vehicle Factory: rigid-piece visuals and the native factory door interlock.
-- Geometry/ranges come from the generator; production, resources, movement and
-- destruction remain engine-owned. Source-hashed native production/clearance
-- evidence is recorded separately in tools/previews/vehicle_factory/acceptance.
local data = include("vehicle_factory_data.lua")
assert(data.schemaVersion == 1, "Unsupported vehicle factory rig schema")

local Base = piece "Base"
local DoorL, DoorR = piece(data.door.leftPiece), piece(data.door.rightPiece)
local Gantry = piece(data.gantry.piece)
local HeadL, HeadR = piece(data.heads.leftPiece), piece(data.heads.rightPiece)
local NanoL, NanoR = piece(data.heads.nanoLeftPiece), piece(data.heads.nanoRightPiece)
local WorkLamp, BuildSpot = piece(data.workLamp.piece), piece(data.buildSpot.piece)
local FanL, FanR = piece(data.fans.leftPiece), piece(data.fans.rightPiece)

local SIG_DOOR, SIG_WORK = 1, 2
local POLL_MS, DOOR_SPEED = 100, 30
local GANTRY_SPEED, HEAD_SPEED, FAN_SPEED = 18, 8, math.pi * 2
local STALL_FRAMES = math.ceil(Game.gameSpeed * 0.6)
local PROGRESS_EPS, CLEARANCE_PAD = 0.0000001, 1
local TAU = math.pi * 2
local dead, wantedOpen, doorsOpen, gateReady = false, false, false, false
local buildingRequested, working, nanoRight = false, false, false
local doorGeneration, workGeneration, workRevision = 0, 0, 0
local products = {}

local function Clamp(value, minimum, maximum)
    return math.max(minimum, math.min(maximum, value))
end

local function Lerp(minimum, maximum, fraction)
    return Clamp(minimum + (maximum - minimum) * fraction, minimum, maximum)
end

local function Finite(value)
    return type(value) == "number" and value == value and math.abs(value) < math.huge
end

local function LiveDefinition(id)
    if type(id) ~= "number" or id == unitID or not Spring.ValidUnitID(id)
        or Spring.GetUnitIsDead(id) then
        return nil
    end
    local defID = Spring.GetUnitDefID(id)
    return defID and UnitDefs[defID]
end

local function RememberProduct()
    local id = Spring.GetUnitIsBuilding(unitID)
    if LiveDefinition(id) then
        products[id] = true
        return id
    end
end

-- Protect both the entire departure lane and the leaves' lateral sweep. A
-- completed product is not clear merely because StopBuilding was called.
local halfLeaf = data.door.leafWidthWorld * 0.5
local exitRects = {
    {
        minX = data.corridor.minXWorld, maxX = data.corridor.maxXWorld,
        minZ = data.corridor.rearInnerZWorld, maxZ = data.corridor.apronFrontZWorld,
    },
    {
        minX = math.min(data.door.closedLeftXWorld,
            data.door.closedLeftXWorld + data.door.leftOpenMoveWorld) - halfLeaf,
        maxX = math.max(data.door.closedRightXWorld,
            data.door.closedRightXWorld + data.door.rightOpenMoveWorld) + halfLeaf,
        minZ = data.door.pocketMinZWorld, maxZ = data.door.pocketMaxZWorld,
    },
}

local function HorizontalDirection(id)
    local fx, _, fz = Spring.GetUnitDirection(id)
    if not Finite(fx) or not Finite(fz) then return nil end
    local length = math.sqrt(fx * fx + fz * fz)
    if length < 0.00001 then return nil end
    return fx / length, fz / length
end

local function CircleIntersects(rect, x, z, radius)
    local dx = math.max(rect.minX - x, 0, x - rect.maxX)
    local dz = math.max(rect.minZ - z, 0, z - rect.maxZ)
    return dx * dx + dz * dz <= (radius + CLEARANCE_PAD) ^ 2
end

local function FootprintIntersects(rect, x, z, halfX, halfZ, cosine, sine)
    -- SAT for the neighbour's oriented footprint in this factory's local X/Z.
    -- A static factory's large spherical model radius is NOT its occupied yard.
    local dx = x - (rect.minX + rect.maxX) * 0.5
    local dz = z - (rect.minZ + rect.maxZ) * 0.5
    local rx, rz = (rect.maxX - rect.minX) * 0.5, (rect.maxZ - rect.minZ) * 0.5
    local c, s = math.abs(cosine), math.abs(sine)
    return math.abs(dx) <= rx + halfX * c + halfZ * s + CLEARANCE_PAD
        and math.abs(dz) <= rz + halfX * s + halfZ * c + CLEARANCE_PAD
        and math.abs(dx * cosine - dz * sine) <= halfX + rx * c + rz * s + CLEARANCE_PAD
        and math.abs(dx * sine + dz * cosine) <= halfZ + rx * s + rz * c + CLEARANCE_PAD
end

local function BlocksExit(id, ox, oy, oz, fx, fz)
    local def = LiveDefinition(id)
    if not def or Spring.GetUnitTransporter(id) then return false end
    local x, y, z, mx, my, mz = Spring.GetUnitPosition(id, true)
    if not Finite(x) or not Finite(y) or not Finite(z) then return false end
    local radius = Spring.GetUnitRadius(id)
    -- A still-live object with unavailable bounds is not permission to close.
    if not Finite(radius) or radius < 0 then return true end
    mx, my, mz = mx or x, my or y, mz or z
    if not Finite(mx) or not Finite(my) or not Finite(mz) then return false end
    if my - radius > oy + data.door.topYWorld + CLEARANCE_PAD
        or my + radius < oy + data.door.bottomYWorld - CLEARANCE_PAD then
        return false -- airborne/underground units do not occupy the door volume
    end

    local static = def.isImmobile or def.isBuilding or def.canMove == false
    if static and Finite(def.xsize) and Finite(def.zsize)
        and def.xsize > 0 and def.zsize > 0 then
        local nfx, nfz = HorizontalDirection(id)
        if nfx then
            -- Footprints are centred on the base, not on the model midpoint.
            local dx, dz = x - ox, z - oz
            local lx, lz = dx * fz - dz * fx, dx * fx + dz * fz
            local cosine, sine = fx * nfx + fz * nfz, fz * nfx - fx * nfz
            local halfX = def.xsize * Game.squareSize * 0.5
            local halfZ = def.zsize * Game.squareSize * 0.5
            for i = 1, #exitRects do
                if FootprintIntersects(exitRects[i], lx, lz, halfX, halfZ, cosine, sine) then
                    return true
                end
            end
            return false
        end
    end

    -- Mobile units use their actual runtime sphere and its actual midpoint.
    -- In particular, the old four-product R40 proxy does not cover M1A1.
    local dx, dz = mx - ox, mz - oz
    local lx, lz = dx * fz - dz * fx, dx * fx + dz * fz
    for i = 1, #exitRects do
        if CircleIntersects(exitRects[i], lx, lz, radius) then return true end
    end
    return false
end

local function ExitOccupied()
    local ox, oy, oz = Spring.GetUnitPosition(unitID)
    local fx, fz = HorizontalDirection(unitID)
    if not Finite(ox) or not Finite(oy) or not Finite(oz) or not fx then return true end
    RememberProduct()
    for id in pairs(products) do
        if BlocksExit(id, ox, oy, oz, fx, fz) then return true end
        products[id] = nil
    end
    -- Only used while closing, not by the working/idle animation loop. A scan
    -- of actual units avoids a guessed query radius that misses long products.
    local units = Spring.GetAllUnits()
    if not units then return true end
    for i = 1, #units do
        if BlocksExit(units[i], ox, oy, oz, fx, fz) then return true end
    end
    return false
end

local function DoorCurrent(generation, open)
    return not dead and generation == doorGeneration and wantedOpen == open
end

local function OpenDoors(generation, open)
    if not DoorCurrent(generation, open) then return false end
    doorsOpen = false
    Move(DoorL, x_axis, data.door.leftOpenMoveWorld, DOOR_SPEED)
    Move(DoorR, x_axis, data.door.rightOpenMoveWorld, DOOR_SPEED)
    WaitForMove(DoorL, x_axis)
    if not DoorCurrent(generation, open) then return false end
    WaitForMove(DoorR, x_axis)
    if not DoorCurrent(generation, open) then return false end
    doorsOpen = true
    return true
end

local function Open(generation)
    SetSignalMask(SIG_DOOR)
    if not DoorCurrent(generation, true) then return end
    SetUnitValue(COB.INBUILDSTANCE, 0)
    SetUnitValue(COB.BUGGER_OFF, 0)
    if not OpenDoors(generation, true) then return end
    while DoorCurrent(generation, true) do
        SetUnitValue(COB.YARD_OPEN, 1)
        -- SetUnitValue is a request. In particular, it is not an acknowledgement.
        if GetUnitValue(COB.YARD_OPEN) == 1 then
            gateReady = true
            SetUnitValue(COB.INBUILDSTANCE, 1)
            SetUnitValue(COB.BUGGER_OFF, 1)
            return
        end
        Sleep(POLL_MS)
    end
end

local function Close(generation)
    SetSignalMask(SIG_DOOR)
    if not DoorCurrent(generation, false) then return end
    SetUnitValue(COB.INBUILDSTANCE, 0) -- stop admitting new construction first
    while DoorCurrent(generation, false) do
        if not ExitOccupied() then
            SetUnitValue(COB.YARD_OPEN, 0)
            if GetUnitValue(COB.YARD_OPEN) == 0 then
                SetUnitValue(COB.BUGGER_OFF, 0)
                doorsOpen = false
                Move(DoorL, x_axis, data.door.closedMoveWorld, DOOR_SPEED)
                Move(DoorR, x_axis, data.door.closedMoveWorld, DOOR_SPEED)
                WaitForMove(DoorL, x_axis)
                if not DoorCurrent(generation, false) then return end
                WaitForMove(DoorR, x_axis)
                return
            end
        end
        -- Keep an obstructed/refused yard physically passable, even when a
        -- Deactivate interrupted opening. Never force or steer the product.
        if not doorsOpen and not OpenDoors(generation, false) then return end
        if not DoorCurrent(generation, false) then return end
        SetUnitValue(COB.YARD_OPEN, 1)
        if GetUnitValue(COB.YARD_OPEN) == 1 then
            SetUnitValue(COB.BUGGER_OFF, 1)
        else
            SetUnitValue(COB.BUGGER_OFF, 0)
        end
        Sleep(POLL_MS)
    end
end

local function RestWork(force, instant)
    if not working and not force then return end
    working = false
    Hide(WorkLamp)
    local gantrySpeed, headSpeed, fanSpeed = GANTRY_SPEED, HEAD_SPEED, FAN_SPEED
    if instant then gantrySpeed, headSpeed, fanSpeed = 0, 0, 0 end
    Move(Gantry, z_axis, data.gantry.minMoveWorld, gantrySpeed)
    local hx = Clamp(0, data.heads.minXMoveWorld, data.heads.maxXMoveWorld)
    local hy = data.heads.maxYMoveWorld
    Move(HeadL, x_axis, hx, headSpeed)
    Move(HeadR, x_axis, hx, headSpeed)
    Move(HeadL, y_axis, hy, headSpeed)
    Move(HeadR, y_axis, hy, headSpeed)
    Turn(FanL, y_axis, data.fans.minAngleRadians, fanSpeed)
    Turn(FanR, y_axis, data.fans.minAngleRadians, fanSpeed)
end

local function WorkPose(progress)
    -- Phase advances only with the real product's build progress, not wall time
    -- or resource guesses. On recovery it resumes that product's same phase.
    local sweep = 0.5 - 0.5 * math.cos(progress * TAU * 3)
    local cross = 0.5 + 0.5 * math.sin(progress * TAU * 5)
    local plunge = 0.5 + 0.5 * math.sin(progress * TAU * 4)
    Move(Gantry, z_axis, Lerp(data.gantry.minMoveWorld, data.gantry.maxMoveWorld, sweep), GANTRY_SPEED)
    Move(HeadL, x_axis, Lerp(data.heads.minXMoveWorld, data.heads.maxXMoveWorld, cross), HEAD_SPEED)
    Move(HeadR, x_axis, Lerp(data.heads.minXMoveWorld, data.heads.maxXMoveWorld, 1 - cross), HEAD_SPEED)
    Move(HeadL, y_axis, Lerp(data.heads.minYMoveWorld, data.heads.maxYMoveWorld, plunge), HEAD_SPEED)
    Move(HeadR, y_axis, Lerp(data.heads.minYMoveWorld, data.heads.maxYMoveWorld, 1 - plunge), HEAD_SPEED)
    local fan = (progress * 12) % 1
    Turn(FanL, y_axis, Lerp(data.fans.minAngleRadians, data.fans.maxAngleRadians, fan), FAN_SPEED)
    Turn(FanR, y_axis, Lerp(data.fans.minAngleRadians, data.fans.maxAngleRadians, 1 - fan), FAN_SPEED)
    if not working then Show(WorkLamp) end
    working = true
end

local function WorkLoop(generation)
    SetSignalMask(SIG_WORK)
    local sampledTarget, previousProgress, advancedAt
    local revision = workRevision
    while not dead and generation == workGeneration do
        local target = RememberProduct()
        local progress
        if buildingRequested and wantedOpen and gateReady and target then
            local health, _, _, _, built = Spring.GetUnitHealth(target)
            if Finite(health) and health > 0 and Finite(built) and built >= 0 and built < 1 then
                progress = built
            end
        end
        local frame = Spring.GetGameFrame()
        if not progress then
            RestWork()
            sampledTarget, previousProgress, advancedAt = nil, nil, nil
            revision = workRevision
        elseif sampledTarget ~= target or revision ~= workRevision then
            RestWork()
            sampledTarget, previousProgress, advancedAt = target, progress, nil
            revision = workRevision
        elseif progress > previousProgress + PROGRESS_EPS then
            previousProgress, advancedAt = progress, frame
            WorkPose(progress)
        elseif progress < previousProgress - PROGRESS_EPS then
            previousProgress, advancedAt = progress, nil
            RestWork() -- reclaim/regression is not productive work
        elseif advancedAt and frame - advancedAt >= STALL_FRAMES then
            RestWork()
        end
        Sleep(POLL_MS)
    end
end

local function RequestDoor(open)
    if dead then return end
    wantedOpen, gateReady = open, false
    workRevision = workRevision + 1
    doorGeneration = doorGeneration + 1
    Signal(SIG_DOOR)
    -- Activate/Deactivate are synchronous callins. Only the child coroutine may
    -- SetSignalMask, Sleep or WaitForMove; the work loop has a separate lifetime.
    StartThread(open and Open or Close, doorGeneration)
end

function script.Create()
    SetUnitValue(COB.INBUILDSTANCE, 0)
    SetUnitValue(COB.BUGGER_OFF, 0)
    SetUnitValue(COB.YARD_OPEN, 0)
    Move(DoorL, x_axis, data.door.closedMoveWorld, 0)
    Move(DoorR, x_axis, data.door.closedMoveWorld, 0)
    RestWork(true, true)
    -- Base and BuildSpot are never animated. The engine owns terrain placement
    -- and construction rendering; marker nodes remain on their real parents.
    workGeneration = workGeneration + 1
    StartThread(WorkLoop, workGeneration)
end

function script.Activate()
    RequestDoor(true)
    return 1
end

function script.Deactivate()
    RequestDoor(false)
    return 0
end

function script.StartBuilding(heading, pitch)
    if dead then return end
    RememberProduct()
    buildingRequested = true
    workRevision = workRevision + 1
    -- This is not the engineer-spider stance flag. Only the door interlock
    -- controls INBUILDSTANCE, and a callback alone is not evidence of progress.
end

function script.StopBuilding()
    if dead then return end
    RememberProduct()
    buildingRequested = false
    workRevision = workRevision + 1
    RestWork()
    -- Keep products and the door state: the last vehicle may still be inside.
end

function script.QueryBuildInfo()
    return BuildSpot
end

function script.QueryNanoPiece()
    nanoRight = not nanoRight
    return nanoRight and NanoL or NanoR
end

function script.Killed(recentDamage, maxHealth)
    dead, wantedOpen, gateReady, buildingRequested = true, false, false, false
    doorGeneration, workGeneration = doorGeneration + 1, workGeneration + 1
    Signal(SIG_DOOR)
    Signal(SIG_WORK)
    SetUnitValue(COB.INBUILDSTANCE, 0)
    SetUnitValue(COB.BUGGER_OFF, 0)
    RestWork(true, true)
    Move(DoorL, x_axis, data.door.closedMoveWorld, 0)
    Move(DoorR, x_axis, data.door.closedMoveWorld, 0)
    products = {}
    -- Removal owns blocking cleanup; do not force a live, occupied yard closed.
    -- Preserve the legacy explosion/return convention, not a new wreck mechanic.
    Explode(Base, SFX.SHATTER)
    local severity = maxHealth > 0 and recentDamage / maxHealth or 1
    return severity <= 0.33 and 1 or 2
end
