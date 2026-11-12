-- Six-legged, displacement-driven tripod gait. One clock preserves the two
-- support groups through stops and turns; direction changes the stroke, not the
-- phase offset. Foot-space strokes are converted to the exported rigid hinges.
local motion = include("track_motion.lua")
local gameSpeed = Game.gameSpeed or 30
local abs, min, max = math.abs, math.min, math.max
local sin, cos, asin = math.sin, math.cos, math.asin
local pi = math.pi

local function Clamp(value, low, high)
    return max(low, min(high, value))
end

local function Approach(value, target, step)
    return value + Clamp(target - value, -step, step)
end

return function(data)
    local legs = {}
    local radius = data.knee.x + data.foot.x
    for i, leg in ipairs(data.legs) do
        local yaw = leg.yaw or 0
        legs[i] = {
            hip = piece(leg.hip),
            knee = piece(leg.knee),
            yaw = yaw,
            phase = leg.phase or 0,
            footX = leg.x + radius * cos(yaw),
            footZ = -radius * sin(yaw),
            hipAngle = yaw,
            lift = 0,
            scale = 0,
        }
    end

    local stride = data.stride
    local stance = data.stanceFraction
    local span = stride * stance * 0.5
    local hipSpeed, kneeSpeed = 6.0, 12.0
    local phase, started = 0, false

    -- A short double-support interval gives the old tripod time to land before
    -- the next lifts. During stance the foot cancels real fore/aft travel.
    local function Gait(p)
        if p < stance then
            return 1 - 2 * p / stance, 0
        end
        local t = (p - stance) / (1 - stance)
        return -1 + 2 * t * t * (3 - 2 * t), data.kneeLift * sin(t * pi)
    end

    local function Apply(leg, dt)
        local stroke, lift = Gait((phase + leg.phase) % 1)
        -- Ease a planted foot back into swing after a pause, but never carry a
        -- lifted goal across the next tripod's support boundary.
        leg.lift = min(lift, leg.lift + 3.0 * dt)
        local reach = data.knee.x + data.foot.x * cos(leg.lift)
                      - data.foot.y * sin(leg.lift)
        local z = leg.footZ + stroke * span * leg.scale
        local angle = asin(Clamp(-z / reach, -1, 1))
        if cos(leg.yaw) < 0 then angle = pi - angle end
        -- hipAmplitude is an angular safety limit, not an unrelated step size.
        angle = leg.yaw + Clamp(motion.angleDifference(leg.yaw, angle),
                               -data.hipAmplitude, data.hipAmplitude)
        leg.hipAngle = leg.hipAngle + Clamp(motion.angleDifference(leg.hipAngle, angle),
                                           -hipSpeed * dt, hipSpeed * dt)
        Turn(leg.hip, y_axis, leg.hipAngle, hipSpeed)
        Turn(leg.knee, z_axis, leg.lift, kneeSpeed)
    end

    local function ReadPose()
        local x, y, z = Spring.GetUnitPosition(unitID)
        local fx, fy, fz = Spring.GetUnitDirection(unitID)
        if not x or not fx then return end
        return {x = x, y = y, z = z, fx = fx, fy = fy, fz = fz,
                frame = Spring.GetGameFrame()}
    end

    local function GaitThread()
        local previous = ReadPose()
        while true do
            Sleep(1000 / gameSpeed)
            local current = ReadPose()
            if not current then return end
            if previous then
                local left, right, frames, teleported =
                    motion.travel(previous, current, 1)
                if frames > 0 and not teleported then
                    local dt = frames / gameSpeed
                    local forward = (left + right) * 0.5
                    local yaw = (left - right) * 0.5
                    local moving = abs(forward) > 0.01 or abs(yaw) > 0.0005
                    if moving then
                        local distance = 0
                        for i = 1, #legs do
                            local leg = legs[i]
                            -- Positive body yaw advances the left feet, not the
                            -- right. Use foot reach, not just the narrow hull.
                            leg.travel = forward - yaw * leg.footX
                            distance = max(distance, abs(leg.travel))
                        end
                        phase = (phase + distance / stride) % 1
                        for i = 1, #legs do
                            local leg = legs[i]
                            leg.scale = Approach(leg.scale, leg.travel / distance, 7.5 * dt)
                            Apply(leg, dt)
                        end
                    else
                        for i = 1, #legs do
                            local leg = legs[i]
                            if leg.lift > 0 then
                                -- Settle only the visible knee. Never rewrite the
                                -- shared clock or a leg's fixed tripod offset.
                                leg.lift = Approach(leg.lift, 0, 3.0 * dt)
                                Turn(leg.knee, z_axis, leg.lift, kneeSpeed)
                            end
                        end
                    end
                end
            end
            previous = current
        end
    end

    return {
        Start = function()
            if started then return end
            started = true
            StartThread(GaitThread)
        end,
        Rest = function()
            for i = 1, #legs do
                local leg = legs[i]
                Turn(leg.hip, y_axis, leg.yaw, 0)
                Turn(leg.knee, z_axis, 0, 0)
            end
        end,
    }
end
