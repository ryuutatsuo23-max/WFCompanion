local _, ns = ...
-- Read offers only: never select services, change filters, or purchase training.
local opened, pending, generation, interrupt = false, false, 0, nil
local summary = "[Trainer offers]\nNot tested - open a trainer window."
function ns.TrainerReport() return summary end
local function read(fn, resultIndex, ...)
    if type(fn) ~= "function" then return "Missing API" end
    local args = {...}
    return ns.Read(function() return select(resultIndex, fn(unpack(args))) end)
end
local function value(fn, resultIndex, ...)
    local status, result = read(fn, resultIndex, ...)
    return status == "OK" and tostring(result) or status
end
local function scan()
    pending = false
    if not opened then return end
    if interrupt then interrupt("Partial - trainer list changed during scan") end
    generation = generation + 1
    local ownGeneration = generation
    local trainer = value(UnitName, 1, "npc")
    local header = "[Trainer offers - revision 1]\nTrainer NPC: " .. trainer
        .. "\nCapture time (client local): " .. value(date, 1, "%Y-%m-%d %H:%M:%S")
        .. "\nObserved offers only; current filters are not changed. Service indices are not spell IDs."
    for _, filter in ipairs({"available", "unavailable", "used"}) do
        header = header .. "\nFilter " .. filter .. ": " .. value(GetTrainerServiceTypeFilter, 1, filter)
    end
    local pages, lines, bytes, index = {}, {}, 0, 1
    local function page()
        if #lines > 0 then pages[#pages+1] = table.concat(lines, "\n") end
        lines, bytes = {}, 0
    end
    local function emit(line) lines[#lines+1] = line; bytes = bytes + #line + 1 end
    local function finish(state)
        interrupt = nil
        page()
        summary = header .. "\nCoverage: " .. state .. "\nTrainer pages saved: " .. #pages
        if ns.SaveTrainerPages then ns.SaveTrainerPages(trainer, header, state, pages) end
        if ns.Capture then ns.Capture("Trainer offers sample") end
    end
    interrupt = finish
    local status, count = read(GetNumTrainerServices, 1)
    if status ~= "OK" or type(count) ~= "number" or count < 0 or count ~= math.floor(count) then
        finish("Unknown - service count " .. status); return
    end
    local function step()
        if not opened or generation ~= ownGeneration then return end
        for _ = 1, 8 do
            if index > count then finish("All " .. count .. " returned offers attempted; Unknown fields remain unresolved"); return end
            if bytes >= 6000 then page() end
            if index > 2000 or #pages >= 40 then finish("Partial - safety limit"); return end
            emit("Offer " .. index .. " name=" .. value(GetTrainerServiceInfo, 1, index)
                .. " status=" .. value(GetTrainerServiceInfo, 2, index))
            emit("  requiredLevel=" .. value(GetTrainerServiceInfo, 4, index)
                .. " subText=" .. value(GetTrainerServiceInfo, 5, index))
            -- Blizzard uses the cost as pet training points for pet services, not copper.
            local costUnit = "Unknown (service currency not confirmed)"
            local currencyStatus, trainerType = read(C_Trainer and C_Trainer.GetTrainerType, 1)
            local enumStatus, petType = ns.Read(function() return Enum.TrainerType.Pet end)
            if currencyStatus == "OK" and enumStatus == "OK" and type(trainerType) == "number" and type(petType) == "number" then
                costUnit = trainerType == petType and "pet training points" or "copper"
            end
            emit("  cost=" .. value(GetTrainerServiceCost, 1, index) .. " costUnit=" .. costUnit
                .. " professionTraining=" .. value(GetTrainerServiceCost, 2, index))
            emit("  skill=" .. value(GetTrainerServiceSkillReq, 1, index)
                .. " rank=" .. value(GetTrainerServiceSkillReq, 2, index)
                .. " skillMet=" .. value(GetTrainerServiceSkillReq, 3, index))
            local as, abilities = read(GetTrainerServiceNumAbilityReq, 1, index)
            if as == "OK" and type(abilities) == "number" and abilities >= 0 and abilities == math.floor(abilities) then
                emit("  abilityRequirements=" .. abilities)
                for a = 1, math.min(abilities,16) do
                    emit("    ability=" .. value(GetTrainerServiceAbilityReq,1,index,a)
                        .. " met=" .. value(GetTrainerServiceAbilityReq,2,index,a))
                end
                if abilities > 16 then emit("  Partial - ability requirement limit") end
            else emit("  abilityRequirements=" .. as) end
            index = index + 1
        end
        summary = header .. "\nCoverage: Partial - scan in progress"
        if C_Timer and type(C_Timer.After) == "function" then
            C_Timer.After(0.05,function()
                local ok = pcall(step)
                if not ok then finish("Partial - API error; raw error not stored") end
            end)
        else finish("Partial - timer unavailable") end
    end
    step()
end
-- Diagnostics may retry when the real trainer frame is visible, never on gossip alone.
function ns.CheckVisibleTrainer()
    local status, shown = ns.Read(function() return ClassTrainerFrame:IsShown() end)
    if status ~= "OK" or shown ~= true or interrupt or pending then return end
    opened = true
    local ok = pcall(scan)
    if not ok then summary = "[Trainer offers]\nAPI error - raw error not stored." end
end
local frame = CreateFrame("Frame")
for _, event in ipairs({"TRAINER_SHOW", "TRAINER_UPDATE", "TRAINER_CLOSED", "PLAYER_LEAVING_WORLD"}) do
    pcall(frame.RegisterEvent,frame,event)
end
frame:SetScript("OnEvent",function(_,event)
    if event == "TRAINER_CLOSED" or event == "PLAYER_LEAVING_WORLD" then
        opened = false; generation = generation + 1
        if interrupt then pcall(interrupt,"Partial - trainer closed before completion") end
        return
    end
    if event == "TRAINER_SHOW" then opened = true end
    if not opened or pending then return end
    pending = true
    local function guarded()
        local ok = pcall(scan)
        if not ok then pending = false; summary = "[Trainer offers]\nAPI error - raw error not stored." end
    end
    if C_Timer and type(C_Timer.After) == "function" then C_Timer.After(0.15,guarded) else guarded() end
end)
