-- SPDX-License-Identifier: GPL-3.0-only
-- Copyright (C) 2026 Steve Vanhamel and WFCompanion contributors.
local _, ns = ...
ns.version = "0.1.4"
local states = {known=true, unknown=true, unavailable=true, restricted=true}
local function integer(v, low, high)
    return type(v)=="number" and v==v and v>=low and v<=high and v==math.floor(v)
end
local function label(v)
    return type(v)=="string" and #v>0 and #v<=120 and not v:find("[%c|]")
end
local function record(v) return type(v)=="table" and getmetatable(v)==nil end
local function array(v, limit)
    if not record(v) then return false end
    local count=0
    for k in pairs(v) do
        if not integer(k,1,limit) then return false end
        count=count+1
    end
    if count>limit then return false end
    for i=1,count do if v[i]==nil then return false end end
    return true
end
local function field(v, predicate)
    return record(v) and states[v.status]==true and
        ((v.status=="known" and predicate(v.value)) or (v.status~="known" and v.value==nil))
end
local function numberField(v) return field(v,function(x) return integer(x,0,2147483647) end) end
local function id(v) return integer(v,1,2147483647) end
local function copy(v)
    if type(v)~="table" then return v end
    local result={}; for k,x in pairs(v) do result[k]=copy(x) end; return result
end
-- Reject cycles, excessive depth/size, functions and nonfinite values before copying.
local function plain(v, seen, budget, depth)
    budget.n=budget.n+1
    if budget.n>100000 or depth>16 then return false end
    if type(v)=="table" then
        if not record(v) or seen[v] then return false end
        seen[v]=true
        for k,x in pairs(v) do
            if (type(k)~="string" and type(k)~="number") or
                not plain(k,seen,budget,depth+1) or not plain(x,seen,budget,depth+1) then return false end
        end
        seen[v]=nil; return true
    end
    return type(v)=="boolean" or (type(v)=="string" and #v<=160 and not v:find("[%c|]"))
        or (type(v)=="number" and v==v and math.abs(v)<math.huge)
end
function ns.ValidateSnapshot(s)
    if not plain(s,{}, {n=0},0) or not record(s) or not integer(s.recordedAt,1,2147483647)
        or s.provenance~="synthetic" or s.coverage~="observed-list"
        or not record(s.client) or s.client.version~="1.60.1" or s.client.interface~=16001
        or not label(s.client.build) or not array(s.professions,20) then return false end
    local professions={}
    for _,p in ipairs(s.professions) do
        if not record(p) or not id(p.skillLineID) or professions[p.skillLineID] or not label(p.name)
            or not numberField(p.skill) or not numberField(p.maxSkill) or not array(p.recipes,2000) then return false end
        professions[p.skillLineID]=true
        if p.skill.status=="known" and p.maxSkill.status=="known" and p.skill.value>p.maxSkill.value then return false end
        local recipes={}
        for _,r in ipairs(p.recipes) do
            if not record(r) or not id(r.recipeID) or recipes[r.recipeID] or not label(r.name)
                or not field(r.learned,function(v) return type(v)=="boolean" end)
                or not field(r.outputItemID,id) or not numberField(r.outputMin) or not numberField(r.outputMax)
                or not states[r.reagentsStatus] or not array(r.slots,16) then return false end
            recipes[r.recipeID]=true
            if r.outputMin.status=="known" and r.outputMax.status=="known" and r.outputMin.value>r.outputMax.value then return false end
            if r.reagentsStatus~="known" and #r.slots>0 then return false end
            for _,slot in ipairs(r.slots) do
                if not record(slot) or not field(slot.required,function(v) return type(v)=="boolean" end)
                    or not numberField(slot.quantity) or not array(slot.alternatives,8)
                    or not states[slot.alternativesStatus] then return false end
                if slot.alternativesStatus~="known" and #slot.alternatives>0 then return false end
                if slot.alternativesStatus=="known" and #slot.alternatives==0 then return false end
                local items={}
                for _,item in ipairs(slot.alternatives) do
                    if not record(item) or not id(item.itemID) or items[item.itemID] or not field(item.name,label) then return false end
                    items[item.itemID]=true
                end
            end
        end
    end
    return true
end
function ns.NewStore() return {schema=1,producer="WFProfessions",addonVersion=ns.version,characters={},settings={}} end
function ns.ValidStore(db)
    if not record(db) or db.schema~=1 or db.producer~="WFProfessions" or not record(db.characters)
        or not record(db.settings) or not plain(db,{}, {n=0},0) then return false end
    local count=0
    for guid,c in pairs(db.characters) do
        count=count+1
        if count>50 or type(guid)~="string" or not guid:match("^Player%-%d+%-%x+$") or not record(c)
            or (c.latest~=nil and not ns.ValidateSnapshot(c.latest)) then return false end
        if c.attempt~=nil and (not record(c.attempt) or not label(c.attempt.status)
            or not integer(c.attempt.at,1,2147483647)) then return false end
    end
    return true
end
ns.Copy=copy
function ns.Display(fieldValue)
    if type(fieldValue)~="table" then return "Unknown" end
    if fieldValue.status=="known" then return tostring(fieldValue.value) end
    return ({unknown="Unknown",unavailable="Unavailable",restricted="Restricted"})[fieldValue.status] or "Unknown"
end
