-- Test-only widget, loaded from the isolated write directory by smoke_tracks.py.
function widget:GetInfo()
    return {name="Track smoke camera", desc="Camera and screenshots for track checks",
            author="MyGame", layer=9999, enabled=true}
end
local timer=Spring.GetTimer()
local started,configured,finished=false,false,false
local unit
local minFPS,maxFPS=10000,0

function widget:Update()
    if not started and Spring.DiffTimers(Spring.GetTimer(),timer)>2 then
        started=true
        Spring.SendCommands("forcestart")
    end
end

function widget:GameFrame(frame)
    unit=unit or Spring.GetGameRulesParam("track_smoke_unit")
    if unit then
        if not configured then
            configured=true
            Spring.SendCommands({"hideinterface 1","viewta"})
            Spring.SetCameraState({mode=1,height=140,angle=0.55,flipped=1},0)
        end
        if frame%3==0 then
            local x,y,z=Spring.GetUnitPosition(unit)
            if x then Spring.SetCameraTarget(x,y+10,z,0) end
            Spring.SelectUnitArray({})
        end
        if frame>90 and frame%30==0 then
            local fps=Spring.GetFPS()
            minFPS,maxFPS=math.min(minFPS,fps),math.max(maxFPS,fps)
        end
    end
    -- Keep captures sparse; some drivers stall on high-frequency capture.
    if frame==140 or frame==620 then
        Spring.SendCommands("screenshot png")
        Spring.Echo("[TRACK_SMOKE] shot frame="..frame)
    end
    if not finished and Spring.GetGameRulesParam("track_smoke_done")==1 then
        finished=true
        Spring.Echo("[TRACK_SMOKE] fps_min="..minFPS.." fps_max="..maxFPS)
        Spring.Echo("[TRACK_SMOKE] complete")
        Spring.SendCommands("quitforce")
    end
end
