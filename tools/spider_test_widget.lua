-- Test-only camera; three sparse captures, never a frame-by-frame recording.
function widget:GetInfo()
    return {name="Spider smoke camera", desc="Camera and screenshots for SP-6",
            author="MyGame", layer=9999, enabled=true}
end
local timer = Spring.GetTimer()
local started, configured, finished, buildShot = false, false, false, false

function widget:Update()
    if not started and Spring.DiffTimers(Spring.GetTimer(),timer)>2 then
        started = true
        Spring.SendCommands("forcestart")
    end
end

function widget:GameFrame(frame)
    local unit = Spring.GetGameRulesParam("spider_smoke_unit")
    if unit then
        if not configured then
            configured = true
            Spring.SendCommands({"hideinterface 1","viewta"})
            Spring.SetCameraState({mode=1,height=180,angle=0.65,flipped=1},0)
        end
        if frame%3 == 0 then
            local x,y,z = Spring.GetUnitPosition(unit)
            if x then Spring.SetCameraTarget(x,y+10,z,0) end
            Spring.SelectUnitArray({})
        end
    end
    if frame == 205 or frame == 650 then
        Spring.SendCommands("screenshot png")
        Spring.Echo("[SPIDER_SMOKE] shot frame="..frame)
    end
    if not buildShot and Spring.GetGameRulesParam("spider_smoke_build_shot")==1 then
        buildShot = frame
        Spring.SetCameraState({mode=1,height=280,angle=0.65,flipped=1},0)
    elseif buildShot and frame == buildShot+12 then
        Spring.SendCommands("screenshot png")
        Spring.Echo("[SPIDER_SMOKE] shot building")
    end
    if not finished and Spring.GetGameRulesParam("spider_smoke_done")==1 then
        finished = true
        Spring.Echo("[SPIDER_SMOKE] complete")
        Spring.SendCommands("quitforce")
    end
end
