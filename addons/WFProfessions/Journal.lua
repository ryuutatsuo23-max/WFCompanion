-- SPDX-License-Identifier: GPL-3.0-only
local addon, ns = ...
local core=WFCore
assert(type(core)=="table" and core.apiVersion==1,"Forever Professions requires WFCore API 1")
ns.core=core
ns.notice="Live collection disabled"
-- This adapter never calls a profession API. No event enables live collection.
ns.LiveAdapter={Collect=function() return nil,"unavailable" end}
local failures={unavailable=true,restricted=true,partial=true,interrupted=true}
local generation=0
local function initialize()
    -- Preview namespace flag is supplied ONLY by the dedicated offline loader.
    -- Synthetic observations never use the SavedVariables global, even if present.
    if ns.syntheticPreview then ns.store=ns.NewStore(); return end
    if WFProfessionsDB==nil then WFProfessionsDB=ns.NewStore() end
    if ns.ValidStore(WFProfessionsDB) then ns.store=WFProfessionsDB
    else ns.store=nil; ns.notice="Unsupported saved data; preserved unchanged" end
end
function ns.Refresh()
    if ns.RefreshUI then ns.RefreshUI() end
end
function ns.Record(adapter)
    if not ns.syntheticPreview then ns.notice="Live collection disabled"; ns.Refresh(); return false end
    local owner=core.owner
    local startedGeneration=generation
    if not ns.store or not core.inWorld or not core.character or not owner then
        ns.notice="Character unavailable"; ns.Refresh(); return false
    end
    local stamp=core.Stamp()
    if not core.Integer(stamp,1,2147483647) then ns.notice="Time unavailable"; ns.Refresh(); return false end
    local ok,snapshot,status=pcall(function() return adapter.Collect() end)
    -- Reject delayed/stale owners even if the adapter changes world state synchronously.
    if generation~=startedGeneration or not core.inWorld or core.owner~=owner or not core.character then
        ns.notice="Interrupted; previous observations preserved"; ns.Refresh(); return false
    end
    local c=ns.store.characters[owner]
    if not c then
        local count=0; for _ in pairs(ns.store.characters) do count=count+1 end
        if count>=50 then ns.notice="Character limit; preserved"; ns.Refresh(); return false end
        c={}; ns.store.characters[owner]=c
    end
    local valid=ok and status=="accepted" and ns.ValidateSnapshot(snapshot)
    if valid then
        c.latest=ns.Copy(snapshot)
        c.attempt={status="accepted",at=stamp}
        ns.notice="Simulated observation recorded"
    else
        c.attempt={status=ok and failures[status] and status or "invalid",at=stamp}
        ns.notice="Attempt "..c.attempt.status.."; previous observations preserved"
    end
    ns.Refresh(); return valid==true
end
core.On("ADDON_LOADED",function(name) if name==addon then initialize() end end)
core.Register(addon,{Start=function() generation=generation+1; ns.viewOwner=core.owner; ns.professionIndex=1; ns.recipeIndex=1; ns.detailPage=1 end,
    Notify=ns.Refresh})
local function leave() generation=generation+1; ns.Refresh() end
core.On("PLAYER_LEAVING_WORLD",leave)
core.On("PLAYER_LOGOUT",leave)
