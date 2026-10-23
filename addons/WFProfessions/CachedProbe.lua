-- SPDX-License-Identifier: GPL-3.0-only
-- Read-only presentation projection. Never writes either saved store or calls game APIs.
local _,ns=...
local function known(v,kind)
    if type(v)=="table" and v.status=="known" and type(v.value)==kind then return v.value end
    return nil
end
local function number(v,positive)
    local n=known(v,"number")
    return n and ns.core.Integer(n,positive and 1 or 0,2147483647) and n or nil
end
local function label(v)
    local s=known(v,"string")
    return s and #s>0 and #s<=120 and not s:find("[%c|]") and s or nil
end
local function field(v,kind)
    local value=kind=="number" and number(v,false) or known(v,kind)
    if value~=nil then return {status="known",value=value} end
    return {status=type(v)=="table" and (v.status=="restricted" or v.status=="unavailable") and v.status or "unknown"}
end
local function array(v,limit)
    if type(v)~="table" then return nil end
    local count=0
    for k in pairs(v) do
        if not ns.core.Integer(k,1,limit) then return nil end
        count=count+1
    end
    for i=1,count do if v[i]==nil then return nil end end
    return v
end
local function projectRecipe(r)
    if type(r)~="table" or type(r.info)~="table" then return nil end
    local id=number(r.id,true); local name=label(r.info.name)
    if not id or number(r.info.recipeID,true)~=id or not name then return nil end
    local output=type(r.output)=="table" and r.output or {}
    local recipe={recipeID=id,name=name,learned=field(r.info.learned,"boolean"),
        outputItemID=field(output.outputItemID,"number"),outputMin=field(output.quantityMin,"number"),
        outputMax=field(output.quantityMax,"number"),reagentsStatus="unavailable",slots={}}
    local slots=type(r.slots)=="table" and r.slots.status=="observed" and array(r.slots.rows,16)
    if slots then
        recipe.reagentsStatus="known"
        for _,slot in ipairs(slots) do
            if type(slot)~="table" then return nil end
            local choices=type(slot.choices)=="table" and slot.choices.status=="observed" and array(slot.choices.rows,8)
            local mapped={required=field(slot.required,"boolean"),quantity=field(slot.quantityRequired,"number"),alternativesStatus="unavailable",alternatives={}}
            if choices and #choices>0 then
                mapped.alternativesStatus="known"
                for _,item in ipairs(choices) do
                    local itemID=type(item)=="table" and number(item.itemID,true)
                    if not itemID then mapped.alternativesStatus="unavailable"; mapped.alternatives={}; break end
                    mapped.alternatives[#mapped.alternatives+1]={itemID=itemID,name={status="unknown"},fromProbe=true}
                end
            end
            recipe.slots[#recipe.slots+1]=mapped
        end
    end
    recipe.requirementsStatus="unknown"; recipe.requirements={}
    local req=r.requirements
    local entries=type(req)=="table" and array(req.rows,8)
    if entries and (req.status=="observed" or req.status=="partial") then
        recipe.requirementsStatus=req.status=="observed" and "known" or "partial"
        for _,entry in ipairs(entries) do
            if type(entry)~="table" then recipe.requirementsStatus="unknown"; recipe.requirements={}; break end
            local name=label(entry.name)
            recipe.requirements[#recipe.requirements+1]={name=name and {status="known",value=name} or {status="unknown"},
                met=field(entry.met,"boolean"),type=field(entry.type,"number")}
        end
    elseif r.requirementsStatus=="restricted" then recipe.requirementsStatus="restricted"
    elseif r.requirementsStatus=="unavailable" or r.requirementsStatus=="error" then recipe.requirementsStatus="unavailable" end
    return recipe
end
local function project(c,learned)
    if type(c)~="table" then return nil end
    local key=learned==185 and "learnedCooking" or learned and "learnedTailoring" or "targetRecipe"
    local a=c[key]
    if type(a)~="table" or not ns.core.Integer(a.at,1,2147483647) then return nil end
    if a.provenance~=(ns.syntheticPreview and "synthetic-probe" or "live-probe") then return nil end
    local client=a.client
    if type(client)~="table" or known(client.version,"string")~="1.60.1" or number(client.interface,true)~=16001 then return nil end
    local report=a.report
    if type(report)~="table" or report.status~="observed" or report.windowObserved~=true or type(report.source)~="table" then return nil end
    for _,key in ipairs({"IsTradeSkillLinked","IsTradeSkillGuild","IsTradeSkillGuildMember"}) do
        local v=report.source[key]
        if type(v)~="table" or v.status~="known" or v.value~=false then return nil end
    end
    local sample=report.sample
    local entries=type(sample)=="table" and array(sample.rows,learned and 100 or 1)
    if not entries or (not learned and #entries~=1) then return nil end
    local p=report.profession
    if type(p)~="table" or not label(p.professionName) then return nil end
    local counts
    if learned then
        counts=report.counts
        if number(p.professionID,true)~=learned or report.coverage~="returned-list-only"
            or sample.status~="observed" or sample.coverage~="returned-array-ended"
            or type(counts)~="table" or not ns.core.Integer(counts.scanned,0,2000)
            or not ns.core.Integer(counts.learned,0,100) or not ns.core.Integer(counts.unlearned,0,2000)
            or counts.unknown~=0 or counts.learned~=#entries
            or counts.scanned~=counts.learned+counts.unlearned then return nil end
    end
    local recipes,seen={},{}
    for _,r in ipairs(entries) do
        local mapped=projectRecipe(r)
        if not mapped or seen[mapped.recipeID] or (learned and
            (mapped.learned.status~="known" or mapped.learned.value~=true)) then return nil end
        seen[mapped.recipeID]=true; recipes[#recipes+1]=mapped
    end
    local attempt=c[key.."Attempt"]
    local attemptStatus=type(attempt)=="table" and type(attempt.report)=="table" and attempt.report.status or "unknown"
    if learned and (type(attempt)~="table" or not ns.core.Integer(attempt.at,a.at,2147483647)) then attemptStatus="unknown" end
    local view={probeCache=true,learnedCache=learned~=nil and learned~=false,observedCounts=counts and ns.Copy(counts),
        latest={recordedAt=a.at,professions={{skillLineID=number(p.professionID,true),name=label(p.professionName),
        skill=field(p.skillLevel,"number"),maxSkill=field(p.maxSkillLevel,"number"),recipes=recipes}}},
        attempt={status=attemptStatus=="observed" and "accepted" or
            (attemptStatus=="unavailable" or attemptStatus=="partial") and "unavailable" or "unknown"}}
    view.latest.professions[1].cache={recordedAt=a.at,learnedCache=view.learnedCache,
        observedCounts=counts and ns.Copy(counts),attempt=ns.Copy(view.attempt)}
    return view
end
function ns.CachedProbeCharacter(guid)
    local db=ns.probeStore
    if type(db)~="table" or db.schema~=1 or db.producer~="WFProfessionsProbe" or type(db.characters)~="table" then return nil end
    local function guarded(mode)
        local ok,value=pcall(project,db.characters[guid],mode)
        return ok and value or nil
    end
    local first=guarded(197) or guarded(false)
    local cooking=guarded(185)
    if not first then return cooking end
    if cooking and first.latest.professions[1].skillLineID~=185 then
        first.latest.professions[#first.latest.professions+1]=cooking.latest.professions[1]
    elseif cooking then return cooking end
    return first
end
function ns.ViewCharacter(guid)
    local c=ns.store and ns.store.characters[guid]
    if c and c.latest then return c end
    return ns.CachedProbeCharacter(guid) or c
end
function ns.ViewCharacterKeys()
    local result={}
    for guid in pairs(ns.store and ns.store.characters or {}) do result[guid]=true end
    for guid in pairs(ns.probeStore and ns.probeStore.characters or {}) do
        if ns.CachedProbeCharacter(guid) then result[guid]=true end
    end
    return result
end
