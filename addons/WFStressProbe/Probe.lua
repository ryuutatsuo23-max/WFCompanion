local _, ns = ...

-- Original diagnostic code. Never store or stringify raw API returns in reports.
-- Guard absence fails closed: pcall alone does not make secret values usable.
local function accessible(value, tableValue)
    if type(issecretvalue) ~= "function" or type(canaccessvalue) ~= "function" then
        return "Guard unavailable"
    end
    local ok, secret = pcall(issecretvalue, value)
    if not ok then return "Guard error" end
    if secret then return "Restricted", "Secret value (issecretvalue)" end
    local allowed
    ok, allowed = pcall(canaccessvalue, value)
    if not ok then return "Guard error" end
    if not allowed then return "Restricted", "Value access denied (canaccessvalue)" end
    if tableValue then
        if type(canaccesstable) ~= "function" then return "Guard unavailable" end
        ok, allowed = pcall(canaccesstable, value)
        if not ok then return "Guard error" end
        if not allowed then return "Restricted", "Table access denied (canaccesstable)" end
    end
    return "OK"
end

local function scalar(value)
    local status, detail = accessible(value)
    if status ~= "OK" then return status, nil, detail end
    if value == nil then return "Unknown (nil)" end
    local kind = type(value)
    if kind == "number" then
        if value ~= value or value == math.huge or value == -math.huge then
            return "Invalid number"
        end
        return "OK", value
    elseif kind == "boolean" then
        return "OK", value
    elseif kind == "string" then
        -- Strip control codes and WoW markup introducers before display/copy.
        return "OK", value:gsub("[%c|]", " "):sub(1, 100)
    end
    return "Unexpected type"
end

local function invoke(fn, ...)
    if type(fn) ~= "function" then return "Missing API" end
    local ok, value = pcall(fn, ...)
    -- Do not serialize errors: they can contain values originating in game state.
    if not ok then return "API error" end
    return "OK", value
end

local function read(fn, ...)
    local status, value = invoke(fn, ...)
    if status ~= "OK" then return status end
    return scalar(value)
end
ns.Read = read

local function record(fn, ...)
    local status, value = invoke(fn, ...)
    if status ~= "OK" then return status end
    local detail
    status, detail = accessible(value)
    if status ~= "OK" then return status, nil, detail end
    if value == nil then return "Unknown (nil)" end
    if type(value) ~= "table" then return "Unexpected type" end
    status, detail = accessible(value, true)
    if status ~= "OK" then return status, nil, detail end
    return "OK", value
end

local function field(value, key)
    -- Only reached after the entire record has passed both guards.
    local ok, result = pcall(function() return value[key] end)
    if not ok then return "API error" end
    return scalar(result)
end

ns.ReadRecord = record
ns.ReadField = field

function ns.ParseSpell(text)
    if text == nil or text:match("^%s*$") then return nil end
    local digits = text:match("^%s*(%d+)%s*$")
    local value = digits and tonumber(digits)
    if not value or value < 1 or value > 2147483647 then return nil, "Enter a positive spell ID, or leave it blank." end
    return value
end

function ns.Run(spellID, context)
    context = context or {}
    local lines = { "FOREVER API PROBE 0.1.0", "Bounded read-only snapshot; addon-only SavedVariables. /reload saves to disk.",
        "OK means readable now, not universal compatibility. Unknown is not zero.",
        "Own character identity is saved locally for report ownership. No other player identities, chat or item links are collected." }
    local details = {}
    local function add(label, status, value, detail)
        local suffix = status == "OK" and (" = " .. tostring(value)) or ""
        lines[#lines + 1] = label .. ": " .. status .. suffix
        if detail then details[#details + 1] = label .. ": " .. detail end
    end
    local function sample(label, fn, ...)
        local status, value, detail = read(fn, ...)
        add(label, status, value, detail)
        return status, value
    end
    local function section(title) lines[#lines + 1] = ""; lines[#lines + 1] = "[" .. title .. "]" end
    local function fields(prefix, value, names)
        for _, name in ipairs(names) do add(prefix .. "." .. name, field(value, name)) end
    end

    section("Build and context")
    if type(GetBuildInfo) == "function" then
        local ok, version, build, date, interface = pcall(GetBuildInfo)
        if ok then
            add("Version", scalar(version)); add("Build", scalar(build))
            add("Build date", scalar(date)); add("Interface", scalar(interface))
        else add("GetBuildInfo", "API error") end
    else add("GetBuildInfo", "Missing API") end
    add("Project ID", scalar(WOW_PROJECT_ID))
    sample("Locale", GetLocale)
    sample("Session time (seconds)", GetTime)
    local glueStatus, glue = sample("Glue screen", C_Glue and C_Glue.IsOnGlueScreen)
    local loginStatus, loggedIn = sample("Logged in", IsLoggedIn)
    local unitStatus, exists = sample("Player exists", UnitExists, "player")
    sample("In combat", InCombatLockdown)
    local ready = loginStatus == "OK" and loggedIn == true and unitStatus == "OK" and exists == true
        and context.inWorld ~= false and glueStatus == "OK" and glue == false

    section("Event observations since addon load")
    for _, event in ipairs(context.eventOrder or {}) do
        local count = (context.events or {})[event]
        add(event, "OK", count or 0)
    end
    for _, event in ipairs(context.unsupportedEvents or {}) do add(event, "Registration unavailable") end
    lines[#lines + 1] = "Event counts cover all units; payloads are not read. Zero does not mean unsupported."
    if not ready then
        section("Character checks")
        lines[#lines + 1] = "Unavailable: login/world/player context is not confirmed. No character reads attempted."
        return table.concat(lines, "\n")
    end

    -- Additive diagnostics retain the schema-1 / 0.1.0 report contract for the existing reader.
    section("Restriction checks - diagnostic revision 1")
    local secrets = C_Secrets or {}
    for _, name in ipairs({ "HasSecretRestrictions", "ShouldAurasBeSecret", "ShouldCooldownsBeSecret" }) do
        sample("C_Secrets." .. name, secrets[name])
    end
    sample("C_Secrets.ShouldUnitPowerBeSecret (mana)", secrets.ShouldUnitPowerBeSecret, "player", 0)
    sample("C_Secrets.ShouldUnitPowerMaxBeSecret (mana)", secrets.ShouldUnitPowerMaxBeSecret, "player", 0)
    sample("C_Secrets.ShouldUnitHealthMaxBeSecret", secrets.ShouldUnitHealthMaxBeSecret, "player")
    sample("C_Secrets.ShouldUnitAuraIndexBeSecret (helpful 1)", secrets.ShouldUnitAuraIndexBeSecret, "player", 1, "HELPFUL")
    lines[#lines + 1] = "Restriction predicates are observations, not proof of the cause of an API error."

    section("HP, active power, mana, XP")
    sample("Player class ID", type(UnitClass) == "function" and function()
        local _, _, id = UnitClass("player"); return id
    end or nil)
    sample("HP", UnitHealth, "player"); sample("HP maximum", UnitHealthMax, "player")
    sample("Active power type ID", UnitPowerType, "player")
    sample("Active power", UnitPower, "player"); sample("Active power maximum", UnitPowerMax, "player")
    -- Explicit mana power type 0, independently of rage/energy/etc.
    sample("Mana", UnitPower, "player", 0); sample("Mana maximum", UnitPowerMax, "player", 0)
    sample("XP", UnitXP, "player"); sample("XP maximum", UnitXPMax, "player")
    lines[#lines + 1] = "Zero mana capacity can be valid for a class/form. XP maximum zero may be a level cap."

    section("Helpful buffs: player only, first 8 indices")
    local auraFn = C_UnitAuras and C_UnitAuras.GetAuraDataByIndex
    for index = 1, 8 do
        local status, value, detail = record(auraFn, "player", index, "HELPFUL")
        if status ~= "OK" then
            add("Aura index " .. index, status, nil, detail)
            if status == "Unknown (nil)" then
                lines[#lines + 1] = "No record at this index; this alone cannot prove all buffs are absent."
            end
            break
        end
        fields("Aura " .. index, value, { "spellId", "applications", "duration", "expirationTime" })
        if index == 8 then lines[#lines + 1] = "Sample limit reached; additional buffs were not checked." end
    end

    section("Cooldowns: selected spell or first 4 known spells in action slots 1-12")
    local spells, seen = {}, {}
    if spellID and (type(spellID) ~= "number" or spellID < 1 or spellID > 2147483647 or spellID ~= math.floor(spellID)) then
        lines[#lines + 1] = "Invalid spell ID; no cooldown call attempted."
    elseif spellID then
        spells[1] = spellID
    else
        for slot = 1, 12 do
            if #spells >= 4 then break end
            local ok, kind, id = false, nil, nil
            if type(GetActionInfo) == "function" then ok, kind, id = pcall(GetActionInfo, slot) end
            if ok then
                local kindStatus, safeKind = scalar(kind)
                local idStatus, safeID = scalar(id)
                if kindStatus == "OK" and safeKind == "spell" and idStatus == "OK" and type(safeID) == "number"
                    and safeID > 0 and safeID <= 2147483647 and safeID == math.floor(safeID) and not seen[safeID] then
                    local status, known = read(C_SpellBook and C_SpellBook.IsSpellKnown, safeID)
                    if status == "OK" and known == true then
                        spells[#spells + 1] = safeID; seen[safeID] = true
                    end
                elseif kindStatus ~= "Unknown (nil)" and kindStatus ~= "OK" then add("Action slot " .. slot, kindStatus) end
            else
                add("Action lookup", type(GetActionInfo) == "function" and "API error" or "Missing API")
                break
            end
        end
        if #spells == 0 then lines[#lines + 1] = "No readable known spell found. Macros/items are not resolved; optional spell ID can be entered later." end
    end
    add("C_Spell.GetSpellCooldown", type(C_Spell and C_Spell.GetSpellCooldown) == "function" and "Present" or "Missing API")
    add("C_SpellBook.IsSpellKnown", type(C_SpellBook and C_SpellBook.IsSpellKnown) == "function" and "Present" or "Missing API")
    for _, id in ipairs(spells) do
        add("Spell ID", "OK", id)
        local knownStatus, known = sample("Spell known", C_SpellBook and C_SpellBook.IsSpellKnown, id)
        if knownStatus == "OK" and known == true then
            local status, value, detail = record(C_Spell and C_Spell.GetSpellCooldown, id)
            if status == "OK" then
                fields("Cooldown", value, { "startTime", "duration", "isEnabled", "modRate" })
            else add("Cooldown", status, nil, detail) end
            lines[#lines + 1] = "Raw readable cooldown fields only; no castability or ready-to-cast claim."
        else
            lines[#lines + 1] = "Cooldown skipped: spell ownership is not confirmed. Try the learned rank's ID."
        end
    end

    section("Inventory: bags 0-4, at most 4 slots per bag")
    lines[#lines + 1] = "Partial API sample, not an inventory total. Bank, equipment and extra bags are unobserved."
    local containers = C_Container or {}
    for bag = 0, 4 do
        local status, slots = sample("Bag " .. bag .. " slot count", containers.GetContainerNumSlots, bag)
        if status == "OK" and type(slots) == "number" and slots >= 0 and slots <= 1000 and slots == math.floor(slots) then
            for slot = 1, math.min(slots, 4) do
                local prefix = "Bag " .. bag .. " slot " .. slot
                sample(prefix .. " item ID", containers.GetContainerItemID, bag, slot)
                local itemStatus, item = record(containers.GetContainerItemInfo, bag, slot)
                if itemStatus == "OK" then
                    fields(prefix, item, { "itemID", "stackCount", "isLocked" })
                else add(prefix .. " record", itemStatus) end
            end
        elseif status == "OK" then add("Bag " .. bag, "Unexpected slot count") end
    end
    lines[#lines + 1] = "Nil item records stay Unknown (empty or inaccessible); no zero ownership is inferred."
    section("Spell restriction checks")
    for _, id in ipairs(spells) do
        sample("Spell " .. id .. " cooldown secrecy", secrets.ShouldSpellCooldownBeSecret, id)
    end
    section("Access failure details")
    for _, detail in ipairs(details) do lines[#lines + 1] = detail end
    if #details == 0 then lines[#lines + 1] = "No classified access failures in this snapshot." end
    local base = table.concat(lines, "\n")
    local recipes = ns.RecipeReport and ns.RecipeReport() or ""
    if ns.TrainerReport then recipes = recipes .. "\n" .. ns.TrainerReport() end
    if ns.TrainerDiagnosticReport then recipes = recipes .. "\n" .. ns.TrainerDiagnosticReport() end
    if ns.BankReport then recipes = recipes .. "\n" .. ns.BankReport() end
    if ns.PartyReport then recipes = recipes .. "\n" .. ns.PartyReport() end
    if ns.AuctionReport then recipes = recipes .. "\n" .. ns.AuctionReport() end
    if ns.VendorReport then recipes = recipes .. "\n" .. ns.VendorReport() end
    if ns.FullInventory then
        base = base .. "\n" .. ns.FullInventory(math.max(0, 31500 - #base - #recipes - 2))
    end
    return base .. (#recipes > 0 and ("\n" .. recipes) or "")
end
