local _, ns = ...
-- Passive, bounded profession snapshots. Never select recipes, clear filters, or craft.
-- Cache survives window closure in memory; existing session reports persist it on reload.
local cached = "[Recipe ingredients]\nNot tested - open a profession window."
local generation, opened, pending = 0, false, false
local finishInterrupted
local function token(status, value)
    return status == "OK" and tostring(value) or status
end
local function field(t, key) return token(ns.ReadField(t, key)) end
local function child(t, key)
    return ns.ReadRecord(function() return t[key] end)
end
local function integer(status, value)
    return status == "OK" and type(value) == "number" and value > 0
        and value < 2147483648 and value == math.floor(value)
end
function ns.RecipeReport() return cached end
local function scan()
    pending = false
    if not opened then return end
    generation = generation + 1
    local current = generation
    local api = C_TradeSkillUI or {}
    if finishInterrupted then finishInterrupted("Partial - superseded by a fresh profession scan") end
    local lines, bytes, pages = {}, 0, {}
    local header, profession
    local function page()
        if #lines > 0 then pages[#pages + 1] = table.concat(lines, "\n") end
        lines, bytes = {}, 0
    end
    local function emit(text)
        lines[#lines + 1] = text; bytes = bytes + #text + 1
    end
    local function publish(state)
        finishInterrupted = nil
        page()
        cached = header .. "\nCoverage: " .. state .. "\nRecipe pages saved: " .. #pages
        if #pages == 1 and #pages[1] < 10500 then cached = cached .. "\n" .. pages[1] end
        if ns.SaveRecipePages then ns.SaveRecipePages(profession, header, state, pages) end
        if ns.Capture then ns.Capture("Profession recipe sample") end
    end
    local ps, prof = ns.ReadRecord(api.GetBaseProfessionInfo)
    profession = ps == "OK" and field(prof, "professionName") or ps
    header = "[Recipe ingredients - revision 2]\nCapture time (client local): "
        .. token(ns.Read(date, "%Y-%m-%d %H:%M:%S")) .. "\nProfession: " .. profession
        .. "\nObserved current profession only. Slot alternatives are choices, not cumulative ingredients. Unknown is not zero."
    finishInterrupted = publish
    local status, ids = ns.ReadRecord(api.GetAllRecipeIDs)
    if status ~= "OK" then emit("Recipe list: " .. status); publish("Unavailable"); return end
    local index = 1
    local function step()
        if current ~= generation or not opened then return end
        for _ = 1, 4 do
            local s, id = ns.ReadField(ids, index)
            if s == "Unknown (nil)" then publish("Returned list exhausted; unresolved fields remain Unknown"); return end
            if bytes >= 6000 then page() end
            if index > 2000 or #pages >= 40 then publish("Partial - safety limit"); return end
            index = index + 1
            if integer(s, id) then
                local rs, info = ns.ReadRecord(api.GetRecipeInfo, id)
                emit("Recipe " .. id .. " learned=" .. (rs == "OK" and field(info, "learned") or rs))
                local ss, schematic = ns.ReadRecord(api.GetRecipeSchematic, id, false)
                if ss == "OK" then
                    emit("  name=" .. field(schematic, "name") .. " output=" .. field(schematic, "outputItemID")
                        .. " min=" .. field(schematic, "quantityMin") .. " max=" .. field(schematic, "quantityMax"))
                    local ts, slots = child(schematic, "reagentSlotSchematics")
                    if ts ~= "OK" then emit("  Ingredients: " .. ts) else
                        for slot = 1, 17 do
                            local vs, row = child(slots, slot)
                            if vs == "Unknown (nil)" then break end
                            if slot == 17 then emit("  Partial - slot limit"); break end
                            if vs ~= "OK" then emit("  Slot " .. slot .. ": " .. vs) else
                                emit("  Slot " .. slot .. " qty=" .. field(row, "quantityRequired") .. " required=" .. field(row, "required"))
                                local as, alternatives = child(row, "reagents")
                                if as ~= "OK" then emit("    Alternatives: " .. as) else
                                    for choice = 1, 9 do
                                        local cs, reagent = child(alternatives, choice)
                                        if cs == "Unknown (nil)" then break end
                                        if choice == 9 then emit("    Partial - alternatives limit"); break end
                                        emit("    item=" .. (cs == "OK" and field(reagent, "itemID") or cs))
                                    end
                                end
                            end
                        end
                    end
                else emit("  Schematic: " .. ss) end
            else emit("Recipe ID: " .. token(s, id)) end
        end
        cached = header .. "\nCoverage: Partial - scan in progress; keep the profession open"
        if C_Timer and type(C_Timer.After) == "function" then C_Timer.After(0.1, function()
            local ok = pcall(step)
            if not ok then publish("Partial - API error; no raw error payload saved") end
        end)
        else publish("Partial - timer unavailable") end
    end
    step()
end
local frame = CreateFrame("Frame")
for _, event in ipairs({"TRADE_SKILL_SHOW", "TRADE_SKILL_LIST_UPDATE", "TRADE_SKILL_DATA_SOURCE_CHANGED", "TRADE_SKILL_CLOSE", "PLAYER_LEAVING_WORLD"}) do
    pcall(frame.RegisterEvent, frame, event)
end
frame:SetScript("OnEvent", function(_, event)
    if event == "TRADE_SKILL_CLOSE" or event == "PLAYER_LEAVING_WORLD" then
        opened = false; generation = generation + 1
        if finishInterrupted then pcall(finishInterrupted, "Partial - window closed before scan finished") end
        return
    end
    if event == "TRADE_SKILL_SHOW" then opened = true end
    if not opened or pending then return end
    pending = true
    if C_Timer and type(C_Timer.After) == "function" then
        C_Timer.After(0.5, function()
            local ok = pcall(scan)
            if not ok then pending = false; cached = "[Recipe ingredients]\nAPI error - no raw error payload saved." end
        end)
    else scan() end
end)
