-- Wheeled-vehicle controller: wheel spin follows real displacement, not a timer.
-- Reuses the differential-drive math that already drives the tracked units.
local motion = include("track_motion.lua")
local gameSpeed = Game.gameSpeed or 30
local abs = math.abs
local us = Spring.UnitScript

return function(data)
    local sides = {
        {key = "left", wheels = {}, speed = 0},
        {key = "right", wheels = {}, speed = 0},
    }
    for _, side in ipairs(sides) do
        for _, name in ipairs(data[side.key]) do
            side.wheels[#side.wheels + 1] = piece(name)
        end
    end

    local function SetSpeed(side, speed)
        if abs(speed - side.speed) < 0.02 then return end
        side.speed = speed
        for _, id in ipairs(side.wheels) do
            if abs(speed) < 0.02 then
                us.StopSpin(id, x_axis, 0)
            else
                us.Spin(id, x_axis, speed, 0)
            end
        end
    end

    local function ReadPose()
        local x, y, z = Spring.GetUnitPosition(unitID)
        local fx, fy, fz = Spring.GetUnitDirection(unitID)
        if not x or not fx then return end
        return {x = x, y = y, z = z, fx = fx, fy = fy, fz = fz,
                frame = Spring.GetGameFrame()}
    end

    local function WheelThread()
        local previous = ReadPose()
        while true do
            Sleep(1000 / gameSpeed)
            local current = ReadPose()
            if not current then return end
            if previous then
                local left, right, frames, teleported =
                    motion.travel(previous, current, data.halfWidth)
                if frames > 0 then
                    if teleported then
                        SetSpeed(sides[1], 0)
                        SetSpeed(sides[2], 0)
                    else
                        local seconds = frames / gameSpeed
                        SetSpeed(sides[1], left / (seconds * data.radius))
                        SetSpeed(sides[2], right / (seconds * data.radius))
                    end
                end
            end
            previous = current
        end
    end

    return {
        Start = function()
            StartThread(WheelThread)
        end,
    }
end
