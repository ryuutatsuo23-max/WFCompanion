-- SPDX-License-Identifier: GPL-3.0-only
-- Session-only name enrichment. Never writes journal/probe observations.
-- Forever packaged UI evidence (70245): C_Item.GetItemInfo may return nothing;
-- GET_ITEM_INFO_RECEIVED(itemID, success). Actual 70532 behavior remains to test.
local _,ns=...
local core=ns.core
local cache,count={},0
local function validName(value)
    return type(value)=="string" and #value>0 and #value<=120 and not value:find("[%c|]")
end
ns.ItemNameAdapter={Read=function(id)
    local api,state=core.Field(_G,"C_Item")
    if state~="ok" then return nil,state end
    -- Core.Field intentionally rejects function values; invoke inside guarded Read.
    return core.Read(function() return api.GetItemInfo(id) end)
end}
local function lookup(id,entry)
    entry.loading=true
    local ok,value,status=pcall(ns.ItemNameAdapter.Read,id)
    entry.loading=false
    if ok and status=="ok" and validName(value) then
        entry.name={status="known",value=value}
    else
        entry.name={status="unknown"}
    end
end
function ns.ResolveItemName(id)
    if not core.Integer(id,1,2147483647) then return {status="unknown"} end
    local entry=cache[id]
    if not entry then
        -- One target capture has at most 16 slots x 8 choices. Bound session work.
        if count>=128 then return {status="unknown"} end
        count=count+1; entry={name={status="unknown"},retried=false}; cache[id]=entry
        lookup(id,entry)
    end
    return ns.Copy(entry.name)
end
core.On("GET_ITEM_INFO_RECEIVED",function(id,success)
    if not core.Access(id) or not core.Access(success) then return end
    if not core.Integer(id,1,2147483647) or success~=true then return end
    local entry=cache[id]
    -- Ignore unrelated, recursive or repeated events; no timers or polling.
    if not entry or entry.loading or entry.retried or entry.name.status=="known" then return end
    entry.retried=true
    lookup(id,entry)
    if entry.name.status=="known" and ns.window and ns.window:IsShown() then ns.Refresh() end
end)
