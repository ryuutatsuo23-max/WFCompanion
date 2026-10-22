local addonName, ns = ...
local context = { events = {}, eventOrder = {}, unsupportedEvents = {}, inWorld = false }
ns.context = context
ns.report = "Automatic snapshots start after entering the world. /reload saves the addon report."
local database, session, pending = nil, nil, false
local MAX_SESSIONS, MAX_SNAPSHOTS = 3, 60
local MAX_TOTAL_SESSIONS = 30

-- Only the logged-in player's identity is collected, for local ownership labels.
-- Never infer the owner of historical sessions or use another unit's identity.
local function characterIdentity()
    local s,key = ns.Read(UnitGUID,"player")
    if s ~= "OK" or type(key) ~= "string" or not key:match("^Player%-%d+%-%x+$") then
        return {status="Unknown - player identity unavailable"}
    end
    local result={status="Known",key=key}
    local n,name=ns.Read(UnitName,"player")
    if n=="OK" and type(name)=="string" then result.name=name; result.firstName=name end
    -- Forever returns the surname as UnitName's second result, not a realm.
    local ls,last=ns.Read(function() return select(2,UnitName("player")) end)
    result.lastNameStatus=ls
    if ls=="OK" and type(last)=="string" and last~="" then
        result.lastName=last
        if result.firstName then result.name=(result.firstName.." "..last):sub(1,100) end
    end
    local r,realm=ns.Read(GetRealmName)
    if r=="OK" and type(realm)=="string" then result.realm=realm end
    return result
end
local function cleanCharacter(value)
    if type(value)~="table" or type(value.key)~="string" or #value.key>100
        or not value.key:match("^Player%-%d+%-%x+$") then
        return {status="Unknown - historical/unavailable identity"}
    end
    return {status="Known",key=value.key,
        name=type(value.name)=="string" and value.name:gsub("[%c|]"," "):sub(1,100) or nil,
        firstName=type(value.firstName)=="string" and value.firstName:gsub("[%c|]"," "):sub(1,100) or nil,
        lastName=type(value.lastName)=="string" and value.lastName:gsub("[%c|]"," "):sub(1,100) or nil,
        lastNameStatus=type(value.lastNameStatus)=="string" and value.lastNameStatus:sub(1,100) or nil,
        realm=type(value.realm)=="string" and value.realm:gsub("[%c|]"," "):sub(1,100) or nil}
end

-- Separate bounded recipe pages avoid truncating ordinary 32 KB diagnostic reports.
-- Keep the latest capture per profession, without consuming snapshot history slots.
local function cleanRecipeSets(sets, limit)
    local result = {}
    if type(sets) ~= "table" then return result end
    for i = 1, math.min(#sets, limit or 10) do
        local set = sets[i]
        if type(set) == "table" and type(set.profession) == "string" and type(set.pages) == "table" then
            local copy = {profession=set.profession:sub(1,100), header=type(set.header)=="string" and set.header:sub(1,1000) or "Unknown",
                coverage=type(set.coverage)=="string" and set.coverage:sub(1,200) or "Unknown", pages={}}
            for j = 1, math.min(#set.pages, 40) do
                if type(set.pages[j]) == "string" and #set.pages[j] <= 24000 then
                    copy.pages[j] = set.pages[j]
                else copy.coverage = "Partial - invalid saved page"; break end
            end
            result[#result+1] = copy
        end
    end
    return result
end

local function say(text)
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("WF Probe: " .. text) end
end

local function stamp()
    local status, value = ns.Read(date, "%Y-%m-%d %H:%M:%S")
    return status == "OK" and value or "Time unavailable"
end

local function boundedText(value, limit)
    return type(value) == "string" and value:sub(1, limit) or nil
end

local function initialize()
    if database then return end
    -- This is our sole saved-variable namespace. Never read another addon's DB.
    local old = WFStressProbeDB
    if type(old) == "table" and old.schema ~= nil and old.schema ~= 1 then
        database = { schema = 1, sessions = {} }
        ns.storageNotice = "Unknown saved schema: memory-only; existing disk data preserved."
        return
    end
    database = { schema = 1, sessions = {} }
    -- Validate bounded plain saved data; rebuild instead of retaining unknown fields.
    if type(old) == "table" and type(old.sessions) == "table" then
        local total = math.min(#old.sessions, 100)
        for i = math.max(1, total - MAX_TOTAL_SESSIONS + 1), total do
            local previous = old.sessions[i]
            if type(previous) == "table" and type(previous.snapshots) == "table" then
                local cleaned = { started = boundedText(previous.started, 64), ended = boundedText(previous.ended, 64), snapshots = {} }
                cleaned.character = cleanCharacter(previous.character)
                cleaned.recipeSets = cleanRecipeSets(previous.recipeSets)
                cleaned.trainerSets = cleanRecipeSets(previous.trainerSets, 100)
                cleaned.trainerDiagnosticSets = cleanRecipeSets(previous.trainerDiagnosticSets, 100)
                cleaned.bankSets = cleanRecipeSets(previous.bankSets)
                cleaned.vendorSets = cleanRecipeSets(previous.vendorSets, 100)
                cleaned.auctionSets = cleanRecipeSets(previous.auctionSets, 50)
                cleaned.auctionDiagnosticSets = cleanRecipeSets(previous.auctionDiagnosticSets)
                for j = 1, math.min(#previous.snapshots, MAX_SNAPSHOTS) do
                    local snapshot = previous.snapshots[j]
                    if type(snapshot) == "table" and type(snapshot.report) == "string" then
                        cleaned.snapshots[#cleaned.snapshots + 1] = { at = boundedText(snapshot.at, 64), reason = boundedText(snapshot.reason, 64), report = boundedText(snapshot.report, 32000) }
                    end
                end
                database.sessions[#database.sessions + 1] = cleaned
            end
        end
    end
    WFStressProbeDB = database
    ns.storageNotice = "Automatic reports enabled. /reload or normal logout saves to disk."
end

local function startSession()
    initialize()
    if session then return end
    session = { started = stamp(), snapshots = {}, captures = 0, character=characterIdentity() }
    database.sessions[#database.sessions + 1] = session
    -- Retain three sessions per known owner. Alt reloads do not evict another
    -- character's sessions. Unknown historical owners are not assigned to an alt.
    local owner=session.character.key
    if owner then
        local count=0
        for i=#database.sessions,1,-1 do
            local c=database.sessions[i].character
            if c and c.key==owner then
                count=count+1
                if count>MAX_SESSIONS then table.remove(database.sessions,i) end
            end
        end
    end
    while #database.sessions > MAX_TOTAL_SESSIONS do table.remove(database.sessions, 1) end
end

local function savePages(key, profession, header, coverage, pages)
    startSession()
    session[key] = session[key] or {}
    local replacement = cleanRecipeSets({{profession=profession,header=header,coverage=coverage,pages=pages}})[1]
    if not replacement then return end
    for i, previous in ipairs(session[key]) do
        if previous.profession == profession then session[key][i] = replacement; return end
    end
    local limit = (key=="trainerSets" or key=="vendorSets" or key=="trainerDiagnosticSets") and 100 or 10
    if key == "auctionSets" then limit = 50 end
    if #session[key] >= limit then table.remove(session[key],1) end
    session[key][#session[key]+1] = replacement
end
function ns.SaveRecipePages(...) return savePages("recipeSets", ...) end
function ns.SaveTrainerPages(...) return savePages("trainerSets", ...) end
function ns.SaveTrainerDiagnosticPages(...) return savePages("trainerDiagnosticSets", ...) end
function ns.SaveBankPages(...) return savePages("bankSets", ...) end
function ns.SaveAuctionDiagnostics(...) return savePages("auctionDiagnosticSets", ...) end
function ns.SaveAuctionPages(...) return savePages("auctionSets", ...) end
function ns.SaveVendorPages(...) return savePages("vendorSets", ...) end

function ns.Capture(reason, spellID)
    startSession()
    local ok, text = pcall(ns.Run, spellID, context)
    if not ok or type(text) ~= "string" then
        text = "Probe internal error. No raw error payload was stored; next capture may recover."
    end
    local c=session.character
    text=text.."\n[Report owner]\n"..(c.key and ((c.name or "Name unavailable").." - "..(c.realm or "Realm unavailable")) or c.status)
    text = text:sub(1, 32000)
    ns.report = text
    session.captures = math.min(session.captures + 1, 999999)
    session.snapshots[#session.snapshots + 1] = { at = stamp(), reason = reason, report = text }
    -- Preserve the first baseline and the most recent 59 snapshots of each session.
    if #session.snapshots > MAX_SNAPSHOTS then table.remove(session.snapshots, 2) end
    if ns.OnSnapshot then pcall(ns.OnSnapshot) end
    return text
end

local function queue(delay)
    if pending or not context.inWorld then return end
    if not C_Timer or type(C_Timer.After) ~= "function" then
        ns.timerNotice = "Timer unavailable: initial/manual/logout captures only."
        return
    end
    pending = true
    C_Timer.After(delay, function()
        pending = false
        if context.inWorld then
            local ok = pcall(ns.Capture, "Automatic event sample")
            if not ok then ns.report = "Automatic capture failed; retry is allowed on the next event." end
        end
    end)
end

local frame = CreateFrame("Frame")
for _, event in ipairs({ "ADDON_LOADED", "PLAYER_LOGIN", "PLAYER_ENTERING_WORLD", "PLAYER_LEAVING_WORLD", "PLAYER_LOGOUT",
    "UNIT_HEALTH", "UNIT_POWER_UPDATE", "PLAYER_XP_UPDATE", "UNIT_AURA", "SPELL_UPDATE_COOLDOWN", "BAG_UPDATE_DELAYED", "PLAYER_EQUIPMENT_CHANGED", "ACTIONBAR_SLOT_CHANGED",
    "GROUP_ROSTER_UPDATE", "UNIT_CONNECTION", "UNIT_FLAGS" }) do
    local ok = pcall(frame.RegisterEvent, frame, event)
    if ok then
        context.eventOrder[#context.eventOrder + 1] = event; context.events[event] = 0
    else context.unsupportedEvents[#context.unsupportedEvents + 1] = event end
end
local function onEvent(_, event, name)
    -- The addon name for ADDON_LOADED is public. All other payloads are ignored.
    if event == "ADDON_LOADED" then
        if name == addonName then initialize() end
        return
    end
    if context.events[event] then context.events[event] = math.min(context.events[event] + 1, 99999) end
    if event == "PLAYER_LOGIN" then
        startSession(); say(ns.storageNotice)
    elseif event == "PLAYER_ENTERING_WORLD" then
        context.inWorld = true
        if C_Timer and type(C_Timer.After) == "function" then queue(2) else ns.Capture("World entry (no timer)") end
    elseif event == "PLAYER_LEAVING_WORLD" then
        context.inWorld = false
    elseif event == "PLAYER_LOGOUT" then
        if context.inWorld then ns.Capture("Logout/reload") end
        if session then session.ended = stamp() end
        context.inWorld = false
    else queue(10) end
end
frame:SetScript("OnEvent", function(...)
    local ok = pcall(onEvent, ...)
    if not ok then ns.report = "Probe event handler failed; no raw error payload was stored." end
end)
