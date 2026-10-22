local _, ns = ...
-- Observe interactions, not dialogue text or selections. Gossip counts may be stale.
local visit, sequence = nil, 0
local summary = "[Trainer window diagnostics]\nNot tested - speak to an NPC."
local events = {"GOSSIP_SHOW", "GOSSIP_CLOSED", "TRAINER_SHOW", "TRAINER_UPDATE",
    "TRAINER_CLOSED", "TRAINER_DESCRIPTION_UPDATE", "TRAINER_SERVICE_INFO_NAME_UPDATE", "PLAYER_LEAVING_WORLD"}
local registered = {}
local function value(fn, ...)
    local s,v=ns.Read(fn,...)
    return s=="OK" and tostring(v) or s
end
local function shown(frame)
    return value(function() if not frame then return nil end; return frame:IsShown() end)
end
function ns.TrainerDiagnosticReport() return summary end
local function save(reason)
    if not visit then return end
    local lines={visit.header,"Trainer count without a visible trainer is context-unconfirmed, possibly stale; not proof of hidden offers."}
    for _,event in ipairs(events) do
        lines[#lines+1]=event.." registered="..tostring(registered[event]).." count="..(visit.counts[event] or 0)
    end
    for _,row in ipairs(visit.rows) do lines[#lines+1]=row end
    summary="[Trainer window diagnostics]\nNPC: "..visit.npc.."\nLatest observation: "..reason
    if ns.SaveTrainerDiagnosticPages then
        ns.SaveTrainerDiagnosticPages(visit.npc,visit.header,reason,{table.concat(lines,"\n")})
    end
    if ns.Capture then ns.Capture("Trainer window diagnostic") end
end
local function observe(label)
    if not visit then return end
    local trainerShown=shown(ClassTrainerFrame)
    local row=value(date,"%Y-%m-%d %H:%M:%S").." "..label
        .." trainerShown="..trainerShown.." gossipShown="..shown(GossipFrame)
        .." offerCount="..value(GetNumTrainerServices)
    for _,filter in ipairs({"available","unavailable","used"}) do
        row=row.." "..filter.."="..value(GetTrainerServiceTypeFilter,filter)
    end
    if #visit.rows>=24 then table.remove(visit.rows,1) end
    visit.rows[#visit.rows+1]=row
    save(label)
    if trainerShown=="true" and ns.CheckVisibleTrainer then ns.CheckVisibleTrainer() end
end
local function begin(event)
    sequence=sequence+1
    local own=sequence
    local npc=value(UnitName,"npc")
    visit={npc=npc,counts={},rows={},header="[Trainer window diagnostics - revision 1]\nNPC: "..npc
        .."\nVisit started: "..value(date,"%Y-%m-%d %H:%M:%S")}
    visit.counts[event]=1
    observe(event)
    if C_Timer and type(C_Timer.After)=="function" then
        for _,delay in ipairs({0.5,2,5,9}) do
            C_Timer.After(delay,function()
                if own~=sequence or not visit then return end
                local ok=pcall(observe,"Delayed "..delay.."s")
                if not ok then save("Diagnostic error - raw payload omitted") end
            end)
        end
    else save("Delayed checks unavailable - missing timer") end
end
local frame=CreateFrame("Frame")
for _,event in ipairs(events) do registered[event]=pcall(frame.RegisterEvent,frame,event) end
frame:SetScript("OnEvent",function(_,event)
    local ok=pcall(function()
        if event=="GOSSIP_SHOW" or event=="TRAINER_SHOW" then
            -- Preserve the transition counts for the same NPC in one interaction.
            local npc=value(UnitName,"npc")
            if visit and visit.npc==npc then
                visit.counts[event]=math.min(9999,(visit.counts[event] or 0)+1)
                observe(event)
            else begin(event) end
            return
        end
        if not visit then return end
        visit.counts[event]=math.min(9999,(visit.counts[event] or 0)+1)
        if event=="GOSSIP_CLOSED" or event=="TRAINER_CLOSED" or event=="PLAYER_LEAVING_WORLD" then
            -- Do not query an old trainer cache after interaction closes.
            save(event.." - interaction closed")
            sequence=sequence+1; visit=nil
        end
    end)
    if not ok then summary="[Trainer window diagnostics]\nDiagnostic error - raw payload omitted." end
end)
