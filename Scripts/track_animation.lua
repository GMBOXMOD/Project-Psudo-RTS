-- Each visible shoe follows the closed belt path. No shader or global clock.
local motion = include("track_motion.lua")
local gameSpeed = Game.gameSpeed or 30
local abs = math.abs
local unpack = unpack
local us = Spring.UnitScript

return function(data, wheelCount)
    local sides = {
        {key = "left", phase = 0, speed = 0, wheels = {}, idlers = {}},
        {key = "right", phase = 0, speed = 0, wheels = {}, idlers = {}},
    }
    local moveArgs, turnArgs = {}, {}
    local links = {}

    for sideIndex, side in ipairs(sides) do
        local label = sideIndex == 1 and "L" or "R"
        for i = 1, wheelCount do side.wheels[i] = piece("Wheel" .. label .. i) end
        side.idlers = {piece("Idler" .. label .. "Front"), piece("Idler" .. label .. "Rear")}
        for i, rest in ipairs(data.links) do
            local id = piece(rest[side.key])
            local index = #links + 1
            links[index] = {id = id, rest = rest, side = side,
                            y = rest.y, z = rest.z, angle = rest.angle}
            local m, t = (index - 1) * 8, (index - 1) * 4
            moveArgs[m+1], moveArgs[m+2], moveArgs[m+3], moveArgs[m+4] = id, y_axis, 0, 0
            moveArgs[m+5], moveArgs[m+6], moveArgs[m+7], moveArgs[m+8] = id, z_axis, 0, 0
            turnArgs[t+1], turnArgs[t+2], turnArgs[t+3], turnArgs[t+4] = id, x_axis, 0, 0
        end
    end

    local function ReadPose()
        local x, y, z = Spring.GetUnitPosition(unitID)
        local fx, fy, fz = Spring.GetUnitDirection(unitID)
        if not x or not fx then return end
        return {x=x, y=y, z=z, fx=fx, fy=fy, fz=fz, frame=Spring.GetGameFrame()}
    end

    local function SetWheelSpeed(side, speed)
        if abs(speed - side.speed) < 0.001 then return end
        side.speed = speed
        for _, id in ipairs(side.wheels) do
            if abs(speed) < 0.001 then
                us.StopSpin(id, x_axis, 0)
            else
                us.Spin(id, x_axis, speed / data.wheelRadius, 0)
            end
        end
        for _, id in ipairs(side.idlers) do
            if abs(speed) < 0.001 then
                us.StopSpin(id, x_axis, 0)
            else
                us.Spin(id, x_axis, speed / data.idlerRadius, 0)
            end
        end
    end

    local function UpdateBelts(seconds)
        for index, link in ipairs(links) do
            local rest = link.rest
            local y, z, angle = motion.sample(data, rest.phase + link.side.phase)
            local m, t = (index - 1) * 8, (index - 1) * 4
            moveArgs[m+3] = y - rest.y
            moveArgs[m+4] = abs(y - link.y) / seconds
            moveArgs[m+7] = z - rest.z
            moveArgs[m+8] = abs(z - link.z) / seconds
            turnArgs[t+3] = motion.angleDifference(rest.angle, angle)
            turnArgs[t+4] = abs(motion.angleDifference(link.angle, angle)) / seconds
            link.y, link.z, link.angle = y, z, angle
        end
        -- Flat groups of four arguments; both rigs submit just two engine calls.
        us.MultiMove(unpack(moveArgs))
        us.MultiTurn(unpack(turnArgs))
    end

    local function TrackThread()
        local previous = ReadPose()
        while true do
            Sleep(1000 / gameSpeed)
            local current = ReadPose()
            if not current then return end
            if previous then
                local left, right, frames, teleported = motion.travel(previous, current, data.halfWidth)
                if frames > 0 then
                    local seconds = frames / gameSpeed
                    SetWheelSpeed(sides[1], left / seconds)
                    SetWheelSpeed(sides[2], right / seconds)
                    if not teleported and (left ~= 0 or right ~= 0) then
                        sides[1].phase = (sides[1].phase + left) % data.perimeter
                        sides[2].phase = (sides[2].phase + right) % data.perimeter
                        UpdateBelts(seconds)
                    end
                end
            end
            previous = current
        end
    end

    return {
        Start = function()
            StartThread(TrackThread) -- also runs while pivoting without StartMoving
        end,
    }
end
