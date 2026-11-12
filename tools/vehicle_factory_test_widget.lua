-- Native test camera. Sparse, named phases only; no GIF/high-rate capture.
function widget:GetInfo()
    return {name="Vehicle Factory smoke camera", desc="Isolated native camera and evidence",
            author="MyGame", layer=9999, enabled=true}
end
local config = VFS.Include("vehicle_factory_test_config.lua")
local timer = Spring.GetTimer()
local started, configured, finished = false, false, false
local pending, lastSequence, lastCapture, doneTimer = nil, 0, nil, nil

local function Quote(value)
    return '"'..tostring(value):gsub("\\","\\\\"):gsub('"','\\"'):gsub("\n","\\n")..'"'
end
local function Log(event, fields)
    local result = {'"event":'..Quote(event), '"frame":'..Spring.GetGameFrame(), '"mode":'..Quote(config.mode)}
    for name, value in pairs(fields or {}) do
        local encoded = type(value)=="string" and Quote(value) or tostring(value)
        result[#result+1] = Quote(name)..":"..encoded
    end
    Spring.Echo("[VF_SMOKE] {"..table.concat(result,",").."}")
end

function widget:Initialize()
    Log("widget_loaded")
end

local function SetCamera()
    local x = Spring.GetGameRulesParam("vf_shot_x")
    local y = Spring.GetGameRulesParam("vf_shot_y")
    local z = Spring.GetGameRulesParam("vf_shot_z")
    local height = Spring.GetGameRulesParam("vf_shot_height")
    Spring.SetCameraState({mode=1,height=height,angle=0.72,flipped=1},0)
    Spring.SetCameraTarget(x,y+18,z,0)
    local factory = Spring.GetGameRulesParam("vf_shot_factory")
    if factory and factory>=0 then Spring.SelectUnitArray({factory}) else Spring.SelectUnitArray({}) end
end

function widget:Update()
    local now = Spring.GetTimer()
    if not started and Spring.DiffTimers(now,timer)>2 then
        started = true
        Spring.SendCommands("forcestart")
    end
    if not configured and Spring.GetGameRulesParam("vf_ready")==1 then
        configured = true
        Spring.SendCommands({"hideinterface 1","viewta","setmaxspeed "..config.speed,"setminspeed "..config.speed})
        -- These affect playback only. Readback below records the actual factors.
        for i=1,12 do Spring.SendCommands("speedup") end
        Log("playback_requested", {factor=config.speed})
    end
    local sequence = Spring.GetGameRulesParam("vf_shot_seq") or 0
    if sequence>lastSequence and not pending then
        local stageID = Spring.GetGameRulesParam("vf_shot_stage")
        pending = {seq=sequence,stage=assert(config.requiredShots[stageID]),timer=now,phase="aim"}
        -- Slow playback while framing, never product progress/build rates. This
        -- lets sparse captures catch short construction windows without racing.
        Spring.SendCommands({"setminspeed 1","setmaxspeed 1"})
        SetCamera()
    end
    if pending and pending.phase=="aim" and Spring.DiffTimers(now,pending.timer)>0.2
       and (not lastCapture or Spring.DiffTimers(now,lastCapture)>1.5) then
        SetCamera()
        local unit = Spring.GetGameRulesParam("vf_shot_unit")
        local progress = unit and unit>=0 and select(5,Spring.GetUnitHealth(unit)) or -1
        Spring.SendCommands("screenshot png")
        Log("screenshot", {stage=pending.stage,seq=pending.seq,unit=unit or -1,progress=progress or -1,
                           factory=Spring.GetGameRulesParam("vf_shot_factory") or -1,
                           height=Spring.GetGameRulesParam("vf_shot_height") or -1})
        pending.phase, pending.timer, lastCapture = "save_wait", now, now
    elseif pending and pending.phase=="save_wait" and Spring.DiffTimers(now,pending.timer)>0.3 then
        -- Wait through several rendered frames before the synced scenario can end.
        Spring.SendLuaRulesMsg("vf_shot_ack:"..pending.seq)
        Spring.SendCommands({"setmaxspeed "..config.speed,"setminspeed "..config.speed})
        lastSequence, pending = pending.seq, nil
    end
    if not finished and Spring.GetGameRulesParam("vf_done")==1 and not pending then
        doneTimer = doneTimer or now
        if Spring.DiffTimers(now,doneTimer)>0.5 then
            finished = true
            Log("client_end", {lastScreenshotSequence=lastSequence})
            Spring.SendCommands("quitforce")
        end
    end
end

function widget:GameFrame(frame)
    if configured and frame%300==0 then
        local current, requested, paused = Spring.GetGameSpeed()
        Log("speed", {currentFactor=current,userFactor=requested,paused=paused,
                       wallSeconds=Spring.DiffTimers(Spring.GetTimer(),timer)})
    end
end
