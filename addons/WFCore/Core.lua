local addon, ns = ...
-- Public addon namespace for future optional modules with a WFCore dependency.
WFCore = ns
ns.version, ns.modules, ns.events = "0.7.0", {}, {}
ns.apiVersion = 1
ns.notice = "Waiting for character"
-- Private, bounded runtime history. Never retain error objects, event arguments,
-- character data or references to modules; diagnostics are not SavedVariables.
local diagnostics, diagnosticLimit = {}, 32
local function diagnosticLabel(value)
    if type(value)~="string" then return "unknown" end
    return (value:sub(1,80):gsub("[%c|]"," "))
end
local function diagnose(kind, name, hook, callbackIndex)
    if #diagnostics==diagnosticLimit then table.remove(diagnostics,1) end
    local row={kind=kind, hook=hook}
    if kind=="module" then row.module=diagnosticLabel(name)
    else row.event=diagnosticLabel(name); row.callbackIndex=callbackIndex end
    diagnostics[#diagnostics+1]=row
end
-- Oldest to newest; callers receive detached records and cannot alter history.
function ns.GetDiagnostics()
    local result={}
    for i,row in ipairs(diagnostics) do
        local copy={}
        for key,value in pairs(row) do copy[key]=value end
        result[i]=copy
    end
    return result
end
-- Each addon keeps its own state. Shared identity/storage is resolved dynamically.
-- Do not copy db/character/owner/inWorld: these change across login/logout.
local sharedFields = {db=true, character=true, owner=true, inWorld=true}
function ns.AttachNamespace(target)
    assert(type(target)=="table" and target~=ns and getmetatable(target)==nil,"Invalid module namespace")
    for key in pairs(sharedFields) do
        assert(rawget(target,key)==nil,"Module namespace shadows shared state")
    end
    -- Normal assignments cannot hide shared state, including false/nil writes.
    -- This is an accidental-write guard, not a sandbox against rawset/debug APIs.
    setmetatable(target,{__index=ns, __metatable="Forever module namespace",
        __newindex=function(t,key,value)
            assert(not sharedFields[key],"Module namespace cannot shadow shared state")
            rawset(t,key,value)
        end})
end

-- All API results pass access guards before comparison, indexing or formatting.
function ns.Access(value, record)
    if type(issecretvalue) ~= "function" or type(canaccessvalue) ~= "function" then return false end
    local ok, secret = pcall(issecretvalue, value)
    if not ok or secret then return false end
    local allowed
    ok, allowed = pcall(canaccessvalue, value)
    if not ok or not allowed then return false end
    if record then
        if type(canaccesstable) ~= "function" then return false end
        ok, allowed = pcall(canaccesstable, value)
        if not ok or not allowed then return false end
    end
    return true
end
function ns.Read(fn, ...)
    if type(fn) ~= "function" then return nil, "unavailable" end
    local ok, value = pcall(fn, ...)
    if not ok then return nil, "error" end
    if not ns.Access(value) then return nil, "restricted" end
    if value == nil then return nil, "unknown" end
    if type(value) == "table" then
        if ns.Access(value, true) then return value, "ok" end
        return nil, "restricted"
    end
    if type(value) == "string" then return value:gsub("[%c|]", " "):sub(1, 160), "ok" end
    if type(value) == "boolean" then return value, "ok" end
    if type(value) == "number" and value == value and math.abs(value) < math.huge then return value, "ok" end
    return nil, "invalid"
end
function ns.Field(record, key)
    if type(record) ~= "table" then return nil, "error" end
    if not ns.Access(record, true) then return nil, "restricted" end
    return ns.Read(function() return record[key] end)
end
function ns.Integer(v, low, high)
    return type(v) == "number" and v >= low and v <= high and v == math.floor(v)
end
function ns.Stamp() return ns.Read(GetServerTime) end
function ns.Register(name, module)
    assert(type(name)=="string" and name:find("%S") and not name:find("%c"),"Invalid Forever module name")
    assert(type(module)=="table" and getmetatable(module)==nil,"Invalid Forever module")
    for _,key in ipairs({"Start","Notify"}) do
        assert(module[key]==nil or type(module[key])=="function","Invalid Forever module callback")
    end
    assert(not ns.modules[name], "Duplicate Forever module")
    ns.modules[name] = module
end
-- Modules may define hooks after Register (Storage does this). Guard both lookup
-- and invocation so a later malformed hook/metatable cannot stop other modules.
local function invoke(module, key)
    local callback = module[key]
    if callback~=nil then
        assert(type(callback)=="function","Invalid Forever module callback")
        callback()
    end
end
local notifying = false
function ns.Notify()
    -- Nested refresh requests are discarded, not queued for another pass.
    if notifying then return end
    notifying = true
    for name,module in pairs(ns.modules) do
        if not pcall(invoke,module,"Notify") then
            ns.notice="Module notification unavailable"
            diagnose("module",name,"Notify")
        end
    end
    notifying = false
end
local frame = CreateFrame("Frame")
function ns.On(event, callback)
    if type(event)~="string" or not event:match("^[A-Z][A-Z0-9_]*$")
        or type(callback)~="function" then return false end
    if not ns.events[event] then
        if not pcall(frame.RegisterEvent, frame, event) then
            diagnose("event",event,"RegisterEvent")
            return false
        end
        ns.events[event] = {}
    end
    table.insert(ns.events[event], callback)
    return true
end
local function initialize()
    ns.db=nil
    if WFCoreDB == nil then WFCoreDB = {schema=1, producer="WFCore", characters={}, settings={}} end
    local db = WFCoreDB
    -- Unknown/corrupt versions remain untouched; no automatic destructive migration.
    if type(db) ~= "table" or db.schema ~= 1 or db.producer ~= "WFCore"
        or type(db.characters) ~= "table" or type(db.settings) ~= "table"
        or (db.inventorySchema~=nil and db.inventorySchema~=2) then
        ns.notice = "Unsupported saved data; storage disabled"
        return
    end
    ns.db = db
    -- Envelope/settings stay schema 1; new inventory snapshots use schema 2.
    db.inventorySchema=2
end
local function identify()
    ns.character, ns.owner = nil, nil
    if not ns.db then return end
    local guid = ns.Read(UnitGUID, "player")
    if type(guid) ~= "string" or not guid:match("^Player%-%d+%-%x+$") then
        ns.notice = "Character identity unavailable"; return
    end
    local first = ns.Read(UnitName, "player")
    local last = ns.Read(function() return select(2, UnitName("player")) end)
    local realm = ns.Read(GetRealmName)
    local version = ns.Read(GetBuildInfo)
    local build = ns.Read(function() return select(2, GetBuildInfo()) end)
    local interface = ns.Read(function() return select(4, GetBuildInfo()) end)
    if version ~= "1.60.1" or interface ~= 16001 then
        ns.notice = "Unsupported client; collection disabled"; return
    end
    local character = ns.db.characters[guid]
    if character == nil then
        local count = 0; for _ in pairs(ns.db.characters) do count = count + 1 end
        if count >= 50 then ns.notice = "Character storage full; existing data preserved"; return end
        character = {locations={}}
        ns.db.characters[guid] = character
    end
    if type(character) ~= "table" or type(character.locations) ~= "table" then
        ns.notice = "Invalid character save; existing data preserved"; return
    end
    character.identity = {guid=guid, firstName=first, lastName=last, realm=realm}
    character.client = {version=version, build=build, interface=interface, locale=ns.Read(GetLocale)}
    ns.character, ns.owner = character, guid
    ns.notice = "Ready"
end
-- Optional schema-1 header observation, independent of inventory snapshots.
-- Never use a retained character reference without rechecking the current GUID.
local function observeDetails(levelEvent, newLevel)
    local character, owner = ns.character, ns.owner
    if not ns.db or not character or not owner or ns.db.characters[owner]~=character then return end
    local guid=ns.Read(UnitGUID,"player")
    if guid~=owner then return end
    if character.details~=nil and (type(character.details)~="table" or character.details.schema~=1) then
        return -- Preserve unknown future or malformed detail records without migration.
    end
    local row={schema=1,status={}}
    local function field(key,value,valid)
        if valid then row[key]=value; row.status[key]="ok"
        else row.status[key]="unknown" end
    end
    -- Read all returns from one call, then guard each before inspecting it.
    local ok,name,token,id=false
    if type(UnitClass)=="function" then ok,name,token,id=pcall(UnitClass,"player") end
    if ok then
        name=ns.Read(function() return name end)
        token=ns.Read(function() return token end)
        id=ns.Read(function() return id end)
    else name,token,id=nil,nil,nil end
    field("className",name,type(name)=="string" and name:find("%S")~=nil)
    field("classToken",token,type(token)=="string" and token:match("^[A-Z]+$")~=nil)
    field("classID",id,ns.Integer(id,1,255))
    local level
    if levelEvent then
        -- UnitLevel may still report the old level during PLAYER_LEVEL_UP.
        level=ns.Read(function() return newLevel end)
    else level=ns.Read(UnitLevel,"player") end
    field("level",level,ns.Integer(level,1,1000))
    local stamp=ns.Stamp()
    field("observedAt",stamp,ns.Integer(stamp,1,9007199254740991))
    -- A successful identity check permits an Unknown observation, never stale
    -- values presented with a fresh timestamp. Other GUID records stay untouched.
    character.details=row
end
ns.On("ADDON_LOADED", function(name) if name == addon then initialize() end end)
ns.On("PLAYER_ENTERING_WORLD", function()
    ns.inWorld = true; identify(); observeDetails()
    for name, module in pairs(ns.modules) do
        if not pcall(invoke,module,"Start") then
            ns.notice="Module startup unavailable"
            diagnose("module",name,"Start")
        end
    end
    ns.Notify()
end)
ns.On("PLAYER_LEAVING_WORLD", function() ns.inWorld = false end)
ns.On("PLAYER_LEVEL_UP", function(level)
    if ns.inWorld then observeDetails(true,level) end
end)
ns.On("PLAYER_LOGOUT", function()
    -- Normal logout/reload save boundary; leaving-world may already have fired.
    observeDetails()
    ns.inWorld = false
end)
frame:SetScript("OnEvent", function(_, event, ...)
    local callbacks = ns.events[event] or {}
    -- On may append during a callback; only the initial list length participates.
    local count = #callbacks
    for index = 1, count do
        local ok = pcall(callbacks[index], ...)
        if not ok then
            ns.notice = "Module error; observation unavailable"
            diagnose("event",event,"OnEvent",index)
        end
    end
end)
