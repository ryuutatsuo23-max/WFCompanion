local _, ns = ...
local module = {bankOpen=false, jobs={}, serial=0, current={}}
ns.Register("WFStorage", module)
function module.Notify()
    if ns.ReconcileActionFeedback then ns.ReconcileActionFeedback() end
    if ns.RefreshUI then ns.RefreshUI() end
    if ns.RefreshBankUI then ns.RefreshBankUI() end
end
ns.inventory = module
local function declarations(scope)
    local ids, seen, complete = {}, {}, true
    local function add(id)
        if ns.Integer(id, -2, 100) and not seen[id] then seen[id]=true; ids[#ids+1]=id end
    end
    if scope == "bags" then
        local count = ns.Read(function() return NUM_TOTAL_EQUIPPED_BAG_SLOTS end)
        if ns.Integer(count, 0, 10) then for id=0,count do add(id) end
        else complete=false; for id=0,4 do add(id) end end
        -- Forever declares Keyring=-1 (not the legacy bank index). Require the
        -- matching enum before classifying the extra container as carried storage.
        local keyring=ns.Read(function() return KEYRING_CONTAINER end)
        local declaredKeyring=ns.Read(function() return Enum.BagIndex.Keyring end)
        if ns.Integer(keyring,-2,-1) and keyring==declaredKeyring then add(keyring)
        else complete=false end
    else
        -- Forever's character tabs are separate from account/guild storage.
        local bank=ns.Read(function() return BANK_CONTAINER end)
        if bank~=nil and bank~=6 then complete=false end
        for i=1,9 do
            local id=ns.Read(function() return Enum.BagIndex["CharacterBankTab_"..i] end)
            if id==i+5 then add(id) else complete=false end
        end
    end
    return ids, complete
end
local function allowed(scope)
    return ns.inWorld and ns.character and (scope ~= "bank" or module.bankOpen)
end
-- Scope declarations shared with direct actions; no snapshot or saved-data writes.
function module.ActionContainers(scope)
    if scope~="bags" and scope~="bank" then return {} end
    local ids=declarations(scope)
    return ids
end
function module.Cancel(scope,reason)
    local job = module.jobs[scope]
    if job then
        job.coverage="partial"; job.reason=reason or "interrupted"
        job.scanStatus=reason and "failed" or "interrupted"
        job.completed=false
        job.emptySlots=0; job.observedSlots=0; job.unknownSlots=0
        for _,row in ipairs(job.slots) do
            row.emptyCandidate=nil
            if row.state=="empty" then job.emptySlots=job.emptySlots+1
            elseif row.state=="observed" then job.observedSlots=job.observedSlots+1
            else job.unknownSlots=job.unknownSlots+1 end
        end
        for _,c in ipairs(job.containers) do
            c.firstRow=nil; c.emptyCandidates=nil; c.coverage="partial"
            c.scannedSlots=0; c.observedSlots=0; c.emptySlots=0; c.unknownSlots=0
            for _,row in ipairs(job.slots) do
                if row.bag==c.id then
                    c.scannedSlots=c.scannedSlots+1
                    if row.state=="observed" then c.observedSlots=c.observedSlots+1
                    elseif row.state=="empty" then c.emptySlots=c.emptySlots+1
                    else c.unknownSlots=c.unknownSlots+1 end
                end
            end
        end
        job.finishedAt=ns.Stamp()
        module.jobs[scope]=nil
    end
    module.current[scope]=nil
end
function module.Scan(scope)
    if not allowed(scope) then return end
    module.Cancel(scope)
    local ids, declared = declarations(scope)
    local character, owner = ns.character, ns.owner
    local location = character.locations[scope]
    if type(location) ~= "table" then location={}; character.locations[scope]=location end
    -- Preserve original schema-1 observations verbatim before any new attempt.
    if location.legacyV1==nil and ((location.latest and location.latest.schema==1)
        or (location.attempt and location.attempt.schema==1)) then
        location.legacyV1={latest=location.latest,attempt=location.attempt}
    end
    local job = {schema=2, addonVersion=ns.version, owner=owner, scope=scope,
        client=character.client, identity=character.identity,
        startedAt=ns.Stamp(), accessible=true, coverage="partial", reason="scanning",
        scanStatus="scanning",completed=false,consistency="event-invalidated-sequential",
        emptyEvidence="HasContainerItem-false-twice+nil-records+free-slot-crosscheck",
        expectedContainers=ids,containers={}, slots={}, unknownSlots=0, emptySlots=0,
        observedSlots=0,expectedSlots=0,expectedSlotsKnown=false,scannedSlots=0,declared=declared}
    location.attempt=job
    module.jobs[scope]=job
    local bagIndex, slot, size, container = 1, 1, nil, nil
    local allSizesKnown=true
    local function finishContainer(api,bag)
        local finalSize=ns.Read(api.GetContainerNumSlots,bag)
        local free=ns.Read(api.GetContainerNumFreeSlots,bag)
        container.sizeStable=container.readable and finalSize==size
        container.freeSlotsEnd=ns.Integer(free,0,size) and free or nil
        container.freeStable=container.freeSlots~=nil and container.freeSlots==container.freeSlotsEnd
        local corroborated=container.sizeStable and container.freeStable and container.freeSlots==container.emptyCandidates
        container.emptySlots=0; container.observedSlots=0; container.unknownSlots=0
        for i=container.firstRow,#job.slots do
            local row=job.slots[i]
            if row.emptyCandidate then
                if corroborated then row.state="empty"; row.reason=nil
                else row.reason="empty evidence not corroborated" end
                row.emptyCandidate=nil
            end
            if row.state=="empty" then container.emptySlots=container.emptySlots+1
            elseif row.state=="observed" then container.observedSlots=container.observedSlots+1
            else container.unknownSlots=container.unknownSlots+1 end
        end
        container.scannedSlots=container.emptySlots+container.observedSlots+container.unknownSlots
        container.coverage=container.sizeStable and container.freeStable and container.unknownSlots==0
            and container.emptySlots==container.freeSlots and container.scannedSlots==size and "complete" or "partial"
        container.firstRow=nil; container.emptyCandidates=nil
        job.emptySlots=job.emptySlots+container.emptySlots
        job.observedSlots=job.observedSlots+container.observedSlots
        job.unknownSlots=job.unknownSlots+container.unknownSlots
        if container.coverage~="complete" then declared=false end
    end
    local function step()
        if module.jobs[scope] ~= job then return end
        if not allowed(scope) or owner ~= ns.owner then module.Cancel(scope); return end
        local api = C_Container or {}
        for _=1,24 do
            local bag=ids[bagIndex]
            if bag == nil then
                job.finishedAt=ns.Stamp()
                job.expectedSlotsKnown=allSizesKnown
                job.scanStatus="completed"; job.completed=true
                local timestamps=ns.Integer(job.startedAt,0,9999999999) and ns.Integer(job.finishedAt,job.startedAt,9999999999)
                job.coverage=declared and timestamps and job.expectedSlots>0 and "complete" or "partial"
                job.reason=job.coverage=="complete" and "finished" or "coverage or timestamp unavailable"
                -- An unresolved/failed attempt never erases the prior snapshot.
                if job.coverage=="complete" then
                    location.latest=job; location.attempt=nil; module.current[scope]=job
                end
                module.jobs[scope]=nil
                ns.Notify(); return
            end
            if size == nil then
                size=ns.Read(api.GetContainerNumSlots,bag)
                local readable=ns.Integer(size,0,200)
                if not readable then size=0; declared=false; allSizesKnown=false end
                local free=ns.Read(api.GetContainerNumFreeSlots,bag)
                container={id=bag,slots=readable and size or nil,readable=readable,
                    freeSlots=readable and ns.Integer(free,0,size) and free or nil,
                    firstRow=#job.slots+1,emptyCandidates=0}
                job.containers[#job.containers+1]=container
                if readable then job.expectedSlots=job.expectedSlots+size end
            end
            if slot > size then finishContainer(api,bag); bagIndex=bagIndex+1; slot=1; size=nil
            else
                local row={bag=bag, slot=slot, state="unknown"}
                local presence,presenceStatus=ns.Read(api.HasContainerItem,bag,slot)
                local item,itemStatus=ns.Read(api.GetContainerItemInfo,bag,slot)
                local id,idStatus=ns.Read(api.GetContainerItemID,bag,slot)
                local after,afterStatus=ns.Read(api.HasContainerItem,bag,slot)
                row.presence=type(presence)=="boolean" and presence or nil
                if presence==false then row.presence=false end
                row.presenceStatus=presenceStatus; row.presenceAfter=type(after)=="boolean" and after or nil
                if after==false then row.presenceAfter=false end
                row.presenceAfterStatus=afterStatus; row.itemStatus=itemStatus; row.idStatus=idStatus
                if type(item) == "table" then
                    local other=ns.Field(item,"itemID")
                    local qty=ns.Field(item,"stackCount")
                    if ns.Integer(id,1,2147483647) and other == id and ns.Integer(qty,1,2147483647)
                        and presence~=false and after~=false then
                        row.itemID=id; row.count=qty; row.state="observed"
                        local locked=ns.Field(item,"isLocked")
                        if type(locked)=="boolean" then row.locked=locked end
                        local name=ns.Read(function() return C_Item.GetItemNameByID(id) end)
                        if type(name)=="string" then row.name=name end
                        local icon=ns.Field(item,"iconFileID")
                        if ns.Integer(icon,1,2147483647) then row.icon=icon end
                        local quality=ns.Field(item,"quality")
                        if ns.Integer(quality,0,8) then row.quality=quality end
                    end
                end
                -- Only explicit readable false on both sides is an empty candidate.
                -- Nil alone, restrictions, errors and contradictory records stay unknown.
                if row.state=="unknown" and presence==false and after==false
                    and item==nil and itemStatus=="unknown" and id==nil and idStatus=="unknown" then
                    row.emptyCandidate=true; container.emptyCandidates=container.emptyCandidates+1
                end
                if row.state=="unknown" then row.reason="unresolved or conflicting API evidence" end
                job.slots[#job.slots+1]=row; job.scannedSlots=job.scannedSlots+1; slot=slot+1
            end
        end
        if C_Timer and type(C_Timer.After) == "function" then
            C_Timer.After(0.05,function()
                if not pcall(step) then module.Cancel(scope,"read failed"); ns.notice="Inventory read failed"; ns.Notify() end
            end)
        else module.Cancel(scope,"timer unavailable"); ns.notice="Timer unavailable" end
    end
    if not pcall(step) then module.Cancel(scope,"read failed"); ns.notice="Inventory read failed" end
end
local pending={}
function module.Request(scope)
    module.Cancel(scope)
    if pending[scope] or not allowed(scope) then return end
    if not C_Timer or type(C_Timer.After) ~= "function" then ns.notice="Timer unavailable"; return end
    pending[scope]=true
    C_Timer.After(0.2,function()
        pending[scope]=nil
        if not pcall(module.Scan,scope) then ns.notice="Inventory scan unavailable" end
    end)
end
-- A user action can discover an invalidated view between event-driven scans.
-- Recover collection without cancelling a scan already in progress or replaying
-- the action. Presentation never promotes an incomplete attempt to latest.
function module.EnsureFresh(scope)
    if not allowed(scope) then return end
    if not module.current[scope] and not pending[scope] and not module.jobs[scope] then module.Request(scope) end
end
function module.Start() module.Request("bags") end
ns.On("BANKFRAME_OPENED",function() module.bankOpen=true; module.Request("bank") end)
ns.On("BANKFRAME_CLOSED",function() module.bankOpen=false; module.Cancel("bank"); ns.Notify() end)
for _,event in ipairs({"BAG_UPDATE","BAG_UPDATE_DELAYED","PLAYERBANKSLOTS_CHANGED","PLAYERBANKBAGSLOTS_CHANGED"}) do
    ns.On(event,function() module.Request("bags"); if module.bankOpen then module.Request("bank") end end)
end
ns.On("PLAYER_LEAVING_WORLD",function()
    module.bankOpen=false; module.Cancel("bags"); module.Cancel("bank"); ns.Notify()
end)
ns.On("PLAYER_LOGOUT",function()
    module.bankOpen=false
    module.Cancel("bags"); module.Cancel("bank")
end)
