-- Test-only gadget, copied into a temporary dependent game by smoke_tracks.py.
function gadget:GetInfo()
    return {name="Track animation smoke", desc="Controlled track-motion checks",
            author="MyGame", layer=1000, enabled=true}
end
if not gadgetHandler:IsSyncedCode() then return false end

local config = VFS.Include("track_smoke_config.lua")
local data = VFS.Include(config.trackData)
local pi, tau = math.pi, 2*math.pi
local unit, pieces, previousL, previousR
local totalL, totalR = 0, 0
local snapshots = {}
local anchor, forwardX, forwardZ, pivotAngle
local maxPathError, maxAngleError = 0, 0
local maxBaseOffset, maxBaseTilt = 0, 0
local us = Spring.UnitScript
local function wrapped(delta, period) return (delta+period/2)%period-period/2 end

local function pathCoordinate(y,z)
    local half,cy,r = data.halfStraight,data.centerY,data.radius
    local straight,arc = 2*half,pi*r
    if z>half then
        local angle=math.atan2(z-half,y-cy)
        return straight+r*angle,angle,math.abs(math.sqrt((z-half)^2+(y-cy)^2)-r)
    elseif z < -half then
        local angle=math.atan2(z+half,y-cy)
        if angle<0 then angle=angle+tau end
        return 2*straight+arc+r*(angle-pi),angle,math.abs(math.sqrt((z+half)^2+(y-cy)^2)-r)
    elseif y>=cy then
        return z+half,0,math.abs(y-cy-r)
    else
        return straight+arc+half-z,pi,math.abs(y-cy+r)
    end
end

local function shoePhase(name,rest)
    local _,dy,dz = us.GetPieceTranslation(pieces[name])
    return pathCoordinate(rest.y+dy,rest.z+dz)
end

local function observe()
    us.CallAsUnit(unit,function()
        local left=shoePhase(data.links[1].left,data.links[1])
        local right=shoePhase(data.links[1].right,data.links[1])
        local _,baseY=us.GetPieceTranslation(pieces.Base)
        local baseX,_,baseZ=us.GetPieceRotation(pieces.Base)
        maxBaseOffset=math.max(maxBaseOffset,math.abs(baseY))
        maxBaseTilt=math.max(maxBaseTilt,math.abs(wrapped(baseX,tau)),math.abs(wrapped(baseZ,tau)))
        if previousL then
            totalL=totalL+wrapped(left-previousL,data.perimeter)
            totalR=totalR+wrapped(right-previousR,data.perimeter)
        end
        previousL,previousR=left,right
    end)
end

local function snapshot(name)
    local x,y,z=Spring.GetUnitPosition(unit)
    local leftSpin,rightSpin
    us.CallAsUnit(unit,function()
        leftSpin=us.IsInSpin(pieces.WheelL1,1)
        rightSpin=us.IsInSpin(pieces.WheelR1,1)
    end)
    snapshots[name]={left=totalL,right=totalR,x=x,y=y,z=z,leftSpin=leftSpin,rightSpin=rightSpin}
    Spring.Echo("[TRACK_SMOKE] snapshot "..name.." left="..totalL.." right="..totalR)
end

local function geometry()
    local root={Spring.GetUnitPieceMatrix(unit,pieces.Base)}
    us.CallAsUnit(unit,function()
        for _,rest in ipairs(data.links) do
            for _,name in ipairs({rest.left,rest.right}) do
                local id=pieces[name]
                local _,dy,dz=us.GetPieceTranslation(id)
                local _,angle,pathError=pathCoordinate(rest.y+dy,rest.z+dz)
                maxPathError=math.max(maxPathError,pathError)
                local m={Spring.GetUnitPieceMatrix(unit,id)}
                local ry,rz=-math.sin(rest.angle),math.cos(rest.angle)
                local tx,ty,tz=m[5]*ry+m[9]*rz,m[6]*ry+m[10]*rz,m[7]*ry+m[11]*rz
                -- Express the shoe's tangent relative to the model root.
                local bx=root[1]*tx+root[2]*ty+root[3]*tz
                local by=root[5]*tx+root[6]*ty+root[7]*tz
                local bz=root[9]*tx+root[10]*ty+root[11]*tz
                local length=math.sqrt(bx*bx+by*by+bz*bz)
                local dot=(-math.sin(angle)*by+math.cos(angle)*bz)/length
                maxAngleError=math.max(maxAngleError,math.acos(math.max(-1,math.min(1,dot))))
            end
        end
    end)
end

local function check(name,passed)
    Spring.Echo("[TRACK_SMOKE] CHECK "..name.."="..tostring(passed))
end

local function finish()
    local a,b=snapshots.forwardStart,snapshots.forwardEnd
    check("forward",b.left-a.left>10 and b.right-a.right>10)
    a,b=snapshots.stopA,snapshots.stopB
    check("stopped",math.abs(b.left-a.left)<0.05 and math.abs(b.right-a.right)<0.05
          and not b.leftSpin and not b.rightSpin)
    a,b=snapshots.reverseStart,snapshots.reverseEnd
    check("reverse",b.left-a.left < -5 and b.right-a.right < -5)
    a,b=snapshots.pivotStart,snapshots.pivotEnd
    local left,right=b.left-a.left,b.right-a.right
    check("pivot",left*right<0 and math.abs(left)>10 and math.abs(right)>10 and math.abs(left+right)<0.4)
    check("closed_path",maxPathError<0.03)
    check("shoe_orientation",maxAngleError<0.05)
    check("stable_chassis",maxBaseOffset<0.001 and maxBaseTilt<0.0001)
    Spring.Echo("[TRACK_SMOKE] max_chassis_offset="..maxBaseOffset.." max_chassis_tilt="..maxBaseTilt)
    Spring.Echo("[TRACK_SMOKE] max_path_error="..maxPathError.." max_angle_error="..maxAngleError)
    Spring.SetGameRulesParam("track_smoke_done",1)
end

function gadget:GameFrame(frame)
    if frame==30 then
        unit=(Spring.GetTeamUnits(0) or {})[1]
        assert(unit,"Missing test tank")
        assert(Spring.GetUnitDefID(unit)==UnitDefNames[config.unitName].id,"Wrong test tank")
        pieces=Spring.GetUnitPieceMap(unit)
        for _,rest in ipairs(data.links) do assert(pieces[rest.left] and pieces[rest.right]) end
        Spring.GiveOrderToUnit(unit,CMD.FIRE_STATE,{0},{})
        Spring.GiveOrderToUnit(unit,CMD.MOVE_STATE,{0},{})
        Spring.SetGameRulesParam("track_smoke_unit",unit)
        Spring.Echo("[TRACK_SMOKE] ready")
    end
    if not unit then return end
    observe()
    if frame==90 then
        snapshot("forwardStart")
        local x,y,z=Spring.GetUnitPosition(unit)
        local fx,_,fz=Spring.GetUnitDirection(unit)
        local length=math.sqrt(fx*fx+fz*fz)
        fx,fz=fx/length,fz/length
        Spring.GiveOrderToUnit(unit,CMD.MOVE,{x+fx*100,Spring.GetGroundHeight(x+fx*100,z+fz*100),z+fz*100},{})
    elseif frame==165 then
        snapshot("forwardEnd")
        Spring.GiveOrderToUnit(unit,CMD.STOP,{}, {})
    elseif frame==230 then
        snapshot("stopA")
    elseif frame==260 then
        snapshot("stopB")
        geometry()
    elseif frame==280 then
        Spring.MoveCtrl.Enable(unit)
        Spring.MoveCtrl.SetVelocity(unit,0,0,0)
        local x,y,z=Spring.GetUnitPosition(unit)
        anchor={x=x,y=y,z=z}
        local fx,_,fz=Spring.GetUnitDirection(unit)
        local length=math.sqrt(fx*fx+fz*fz)
        forwardX,forwardZ=fx/length,fz/length
    elseif frame==390 then
        geometry()
    elseif frame==400 then
        local x,y,z=Spring.GetUnitPosition(unit)
        anchor={x=x,y=y,z=z}
    elseif frame==410 then
        snapshot("reverseStart")
    elseif frame==485 then
        snapshot("reverseEnd")
    elseif frame==510 then
        geometry()
    elseif frame==520 then
        -- MoveCtrl world yaw has the opposite sign to the engine heading.
        pivotAngle=-Spring.GetUnitHeading(unit)*tau/65536
    elseif frame==530 then
        snapshot("pivotStart")
    elseif frame==605 then
        snapshot("pivotEnd")
    elseif frame==650 then
        geometry()
    elseif frame==680 then
        Spring.MoveCtrl.Disable(unit)
        finish()
    end
    -- Only this temporary test game uses MoveCtrl; the actual unit's driving
    -- settings are untouched. Slow motion makes individual shoes inspectable.
    if frame>280 and frame<=370 then
        local distance=(frame-280)*0.15
        local x,z=anchor.x+forwardX*distance,anchor.z+forwardZ*distance
        Spring.MoveCtrl.SetPosition(unit,x,Spring.GetGroundHeight(x,z),z)
    elseif frame>400 and frame<=490 then
        local distance=(frame-400)*0.15
        local x,z=anchor.x-forwardX*distance,anchor.z-forwardZ*distance
        Spring.MoveCtrl.SetPosition(unit,x,Spring.GetGroundHeight(x,z),z)
    elseif frame>520 and frame<=610 then
        Spring.MoveCtrl.SetRotation(unit,0,pivotAngle+(frame-520)*pi/180,0)
    end
end
