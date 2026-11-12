-- Pure geometry and differential-drive math shared by the animation and tests.
local TrackMotion = {}
local pi, tau = math.pi, 2 * math.pi
local sqrt, abs = math.sqrt, math.abs
local atan2 = math.atan2 or function(y, x)
    if x > 0 then return math.atan(y / x) end
    if x < 0 then return math.atan(y / x) + (y >= 0 and pi or -pi) end
    if y > 0 then return pi / 2 end
    if y < 0 then return -pi / 2 end
    return 0
end

function TrackMotion.angleDifference(previous, current)
    return (current - previous + pi) % tau - pi
end

-- Positive distance: upper run forwards, front arc down, lower run backwards.
-- The returned angle is the right-handed X rotation of a canonical shoe.
function TrackMotion.sample(data, distance)
    local straight = 2 * data.halfStraight
    local arc = pi * data.radius
    local s = distance % data.perimeter
    if s < straight then
        return data.centerY + data.radius, -data.halfStraight + s, 0
    end
    s = s - straight
    if s < arc then
        local angle = s / data.radius
        return data.centerY + data.radius * math.cos(angle),
               data.halfStraight + data.radius * math.sin(angle), angle
    end
    s = s - arc
    if s < straight then
        return data.centerY - data.radius, data.halfStraight - s, pi
    end
    local angle = pi + (s - straight) / data.radius
    return data.centerY + data.radius * math.cos(angle),
           -data.halfStraight + data.radius * math.sin(angle), angle
end

-- Snapshots contain position, forward vector and simulation frame, not wall time.
function TrackMotion.travel(previous, current, halfWidth)
    local frames = current.frame - previous.frame
    if frames <= 0 then return 0, 0, 0, false end
    local dx, dy, dz = current.x - previous.x, current.y - previous.y, current.z - previous.z
    if dx * dx + dy * dy + dz * dz > (128 * frames) ^ 2 then
        return 0, 0, frames, true -- a teleport must not spin the belts
    end

    local fx = previous.fx + current.fx
    local fy = previous.fy + current.fy
    local fz = previous.fz + current.fz
    local length = sqrt(fx * fx + fy * fy + fz * fz)
    if length < 0.000001 then
        fx, fy, fz = current.fx, current.fy, current.fz
        length = sqrt(fx * fx + fy * fy + fz * fz)
    end
    local forward = length > 0.000001 and (dx * fx + dy * fy + dz * fz) / length or 0
    local yaw = atan2(previous.fz * current.fx - previous.fx * current.fz,
                      previous.fx * current.fx + previous.fz * current.fz)
    -- Suppress sub-pixel ground settling while the tank is parked.
    if abs(forward) < 0.002 * frames then forward = 0 end
    if abs(yaw) < 0.0001 * frames then yaw = 0 end
    return forward + halfWidth * yaw, forward - halfWidth * yaw, frames, false
end

return TrackMotion
