local _,ns=...
-- Actions are hardware-click initiated, never queued/replayed after combat.
function ns.InteractionReady()
    local combat,status=ns.Read(InCombatLockdown)
    return status=="ok" and not combat and ns.inWorld and ns.character~=nil
end
function ns.LiveEntry(entry)
    if not ns.InteractionReady() or not entry or entry.owner~=ns.owner
        or entry.snapshot~=ns.inventory.current[entry.scope]
        or (entry.scope=="bank" and not ns.inventory.bankOpen) then return false end
    local item=entry.item
    local api=C_Container or {}
    local record=ns.Read(api.GetContainerItemInfo,item.bag,item.slot)
    return type(record)=="table" and ns.Read(api.GetContainerItemID,item.bag,item.slot)==item.itemID
        and ns.Field(record,"itemID")==item.itemID and ns.Field(record,"stackCount")==item.count
        and ns.Field(record,"isLocked")==false
end
local function unavailable(message)
    ns.notice=message; ns.Notify()
end
function ns.ItemClick(entry,mouse,button)
    if mouse=="LeftButton" and ns.Read(IsAltKeyDown)==true then
        if entry then ns.ToggleFavorite(entry.owner,entry.item.itemID) end
        return
    end
    if not ns.LiveEntry(entry) then unavailable("Item changed or view is read-only; refresh first"); return end
    -- Preserve native vendor/trade confirmations via the explicit native fallback.
    for _,frame in ipairs({MerchantFrame or false,TradeFrame or false,MailFrame or false,AuctionHouseFrame or false}) do
        if frame and frame:IsShown() then unavailable("Use Settings > Native UI for this interaction"); return end
    end
    local api=C_Container or {}; local item=entry.item
    if mouse=="RightButton" then
        local bankType=ns.inventory.bankOpen and ns.Read(function() return Enum.BankType.Character end) or nil
        if ns.inventory.bankOpen and bankType==nil then unavailable("Bank action unavailable"); return end
        if type(api.UseContainerItem)~="function" then unavailable("Item action unavailable"); return end
        local ok=pcall(api.UseContainerItem,item.bag,item.slot,nil,bankType,false)
        if not ok then unavailable("Item action blocked; use Native UI"); return end
    elseif mouse=="LeftButton" then
        if ns.Read(IsShiftKeyDown)==true then
            if not StackSplitFrame or type(StackSplitFrame.OpenStackSplitFrame)~="function" or item.count<2 then return end
            button.SplitStack=function(_,count)
                if ns.LiveEntry(entry) and ns.Integer(count,1,item.count-1) and type(api.SplitContainerItem)=="function" then
                    pcall(api.SplitContainerItem,item.bag,item.slot,count)
                end
            end
            StackSplitFrame:OpenStackSplitFrame(item.count,button,"BOTTOMLEFT","TOPLEFT")
            return
        end
        if type(api.PickupContainerItem)~="function" then unavailable("Item movement unavailable"); return end
        if not pcall(api.PickupContainerItem,item.bag,item.slot) then unavailable("Item movement blocked"); return end
    else return end
    ns.notice="Ready"
    ns.inventory.Request("bags"); if ns.inventory.bankOpen then ns.inventory.Request("bank") end
end
function ns.SortLiveInventory(scope)
    if not ns.InteractionReady() then unavailable("Sorting unavailable in combat"); return end
    local _,owner=ns.ViewedCharacter()
    if scope=="bags" and owner~=ns.owner then unavailable("Saved characters cannot be sorted"); return end
    local api=C_Container or {}
    local fn=scope=="bank" and api.SortBank or api.SortBags
    local bankType=ns.Read(function() return Enum.BankType.Character end)
    if scope=="bank" and (not ns.inventory.bankOpen or bankType==nil) then unavailable("Open the bank to sort it"); return end
    if type(fn)~="function" then unavailable("Native sorting unavailable"); return end
    local ok
    if scope=="bank" then ok=pcall(fn,bankType) else ok=pcall(fn) end
    if not ok then unavailable("Sorting blocked; use Native UI"); return end
    ns.inventory.Request(scope)
end

local masked={}
local nativeShown=false
local function restore()
    for frame,state in pairs(masked) do
        if state.alpha~=nil then frame:SetAlpha(state.alpha) end
        if state.mouse~=nil then frame:EnableMouse(state.mouse) end
        if state.wheel~=nil then frame:EnableMouseWheel(state.wheel) end
    end
    masked={}
end
local function mask(frame,root)
    if not frame then return end
    if not masked[frame] then
        masked[frame]={alpha=root and frame:GetAlpha() or nil,mouse=frame:IsMouseEnabled()}
        if type(frame.IsMouseWheelEnabled)=="function" then masked[frame].wheel=frame:IsMouseWheelEnabled() end
    end
    if root then frame:SetAlpha(0) end
    frame:EnableMouse(false)
    if type(frame.EnableMouseWheel)=="function" then frame:EnableMouseWheel(false) end
    if type(frame.ClearFocus)=="function" then frame:ClearFocus() end
    for _,child in ipairs({frame:GetChildren()}) do mask(child,false) end
end
function ns.ReplaceNativeBank()
    if not ns.inventory.bankOpen or nativeShown or not ns.InteractionReady() then return end
    if BankFrame and type(BankFrame.GetChildren)=="function" then mask(BankFrame,true) end
    if type(CloseAllBags)=="function" then pcall(CloseAllBags) end
end
function ns.ToggleNativeUI()
    if not ns.InteractionReady() then unavailable("Native UI toggle unavailable in combat"); return end
    nativeShown=not nativeShown
    if nativeShown then
        restore(); if type(OpenAllBags)=="function" then pcall(OpenAllBags) end
    else
        if type(CloseAllBags)=="function" then pcall(CloseAllBags) end
        ns.ReplaceNativeBank()
    end
end
local hooked=false
local function installHooks()
    if hooked or type(hooksecurefunc)~="function" then return end
    hooked=true
    for _,name in ipairs({"OpenAllBags","OpenBackpack","ToggleAllBags"}) do
        if type(_G[name])=="function" then
            hooksecurefunc(name,function()
                if ns.inventory.bankOpen and not nativeShown then ns.ReplaceNativeBank() end
            end)
        end
    end
end
ns.On("PLAYER_ENTERING_WORLD",installHooks)
ns.On("BANKFRAME_OPENED",function()
    nativeShown=false
    if not ns.InteractionReady() then return end
    ns.ShowInventory("bags"); ns.ShowBankUI()
    if C_Timer and C_Timer.After then C_Timer.After(0,ns.ReplaceNativeBank) end
end)
ns.On("BANKFRAME_CLOSED",function() restore(); nativeShown=false; ns.HideBankUI() end)
ns.On("BANK_TABS_CHANGED",function()
    if ns.inventory.bankOpen and C_Timer and C_Timer.After then C_Timer.After(0,ns.ReplaceNativeBank) end
end)
ns.On("PLAYER_REGEN_DISABLED",function() restore() end)
ns.On("PLAYER_REGEN_ENABLED",function()
    if ns.inventory.bankOpen then ns.ShowInventory("bags"); ns.ShowBankUI(); ns.ReplaceNativeBank() end
end)
ns.On("PLAYER_LEAVING_WORLD",function() restore(); nativeShown=false end)
