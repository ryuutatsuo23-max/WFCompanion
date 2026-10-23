local _,ns=...
-- Actions are hardware-click initiated, never queued/replayed after combat.
function ns.InteractionReady()
    local combat,status=ns.Read(InCombatLockdown)
    return status=="ok" and not combat and ns.inWorld and ns.character~=nil
end
-- Returns a specific explanation without performing or scheduling an action.
function ns.ItemActionReason(entry)
    if not entry then return "No item selected" end
    if entry.owner~=ns.owner then return "Saved character: switch to Current to use items" end
    if entry.scope=="bank" and not ns.inventory.bankOpen then return "Cached bank: visit a banker to use these items" end
    local combat,status=ns.Read(InCombatLockdown)
    if status~="ok" then return "Combat state unavailable: use Native UI" end
    if combat then return "In combat: try again after combat" end
    if not ns.inWorld or not ns.character then return "Character unavailable: wait until login completes" end
    local item=entry.item
    if not item or item.state~="observed" then return "Unresolved slot: refresh when item data is available" end
    if entry.scope~="bags" and entry.scope~="bank" then return "Unknown storage location" end
    local declared=false
    for _,bag in ipairs(ns.inventory.ActionContainers(entry.scope)) do
        if bag==item.bag then declared=true; break end
    end
    if not declared or not ns.Integer(item.slot,1,200) then return "Slot unavailable" end
    local api=C_Container or {}
    local size=ns.Read(api.GetContainerNumSlots,item.bag)
    if not ns.Integer(size,item.slot,200) then return "Slot unavailable" end
    local record=ns.Read(api.GetContainerItemInfo,item.bag,item.slot)
    if type(record)~="table" then return "Item data unavailable: refresh or use Native UI" end
    if ns.Read(api.GetContainerItemID,item.bag,item.slot)~=item.itemID
        or ns.Field(record,"itemID")~=item.itemID then
        return "Item changed: refresh this view"
    end
    local count=ns.Field(record,"stackCount")
    if not ns.Integer(count,1,1000000) then return "Item quantity unavailable" end
    local locked=ns.Field(record,"isLocked")
    if locked==true then return "Item locked: wait for its current action to finish" end
    if locked~=false then return "Item lock state unknown: use Native UI" end
    return nil,count
end
function ns.LiveEntry(entry) return ns.ItemActionReason(entry)==nil end
local function specialInteraction()
    for _,frame in ipairs({MerchantFrame or false,TradeFrame or false,MailFrame or false,AuctionHouseFrame or false,GuildBankFrame or false}) do
        if frame and frame:IsShown() then return "Use Main settings > Native UI here" end
    end
end
function ns.ActionHint(entry)
    return ns.ItemActionReason(entry) or specialInteraction() or
        (entry.scope=="bank" and "Right-click: withdraw. Shift+left: split." or "Right-click: use / equip / bank. Shift+left: split.")
end
-- Action feedback is session-only and cannot overwrite collection errors.
local actionFeedback
function ns.StatusNotice()
    if ns.notice~="Ready" then return ns.notice end
    return actionFeedback and actionFeedback.message or "Ready"
end
function ns.ClearActionFeedback() actionFeedback=nil end
function ns.ReconcileActionFeedback()
    local feedback=actionFeedback
    if not feedback or not feedback.entry then return end
    local entry=feedback.entry
    if entry.owner~=ns.owner then return end
    local snapshot=ns.inventory.current[entry.scope]
    if not snapshot or snapshot==feedback.snapshot or snapshot.coverage~="complete"
        or not ns.InteractionReady() or specialInteraction() then return end
    if entry.scope=="bank" and not ns.inventory.bankOpen then return end
    for _,item in ipairs(snapshot.slots or {}) do
        if item.bag==entry.item.bag and item.slot==entry.item.slot then
            if item.state=="empty" or (item.state=="observed" and not ns.ItemActionReason({
                owner=entry.owner,scope=entry.scope,snapshot=snapshot,item=item})) then
                actionFeedback=nil
            end
            return
        end
    end
end
local function unavailable(message,entry)
    actionFeedback={message=message,entry=entry,snapshot=entry and ns.inventory.current[entry.scope]}
    ns.Notify()
end
local splitOwner,splitStrata,splitLevel
local function restoreSplitLayer()
    if StackSplitFrame then
        if splitStrata then StackSplitFrame:SetFrameStrata(splitStrata) end
        if splitLevel then StackSplitFrame:SetFrameLevel(splitLevel) end
    end
    splitOwner=nil; splitStrata=nil; splitLevel=nil
end
function ns.CloseItemSplit(parent)
    if splitOwner and (not parent or splitOwner:GetParent()==parent) then
        StackSplitFrame:Hide(); restoreSplitLayer()
    end
end
function ns.MoveItem(entry)
    local reason=ns.ItemActionReason(entry) or specialInteraction()
    if reason then unavailable(reason,entry); return end
    local api=C_Container or {}
    if type(api.PickupContainerItem)~="function" then unavailable("Item movement unavailable"); return end
    if not pcall(api.PickupContainerItem,entry.item.bag,entry.item.slot) then unavailable("Item movement blocked"); return end
    ns.ClearActionFeedback(); ns.inventory.Request(entry.scope)
end
function ns.DropInFreeSlot(scope)
    if ns.Read(GetCursorInfo)~="item" then return end
    local _,owner=ns.ViewedCharacter()
    if owner~=ns.owner or not ns.InteractionReady() or specialInteraction()
        or (scope=="bank" and not ns.inventory.bankOpen) then return end
    if scope~="bags" and scope~="bank" then return end
    local api=C_Container or {}
    if type(api.PickupContainerItem)~="function" then unavailable("Item placement unavailable"); return end
    -- Hardware-triggered bounded search; no saved snapshot is read or changed.
    for _,bag in ipairs(ns.inventory.ActionContainers(scope)) do
        local size=ns.Read(api.GetContainerNumSlots,bag)
        if ns.Integer(size,0,200) then
            for slot=1,size do
                local occupied,status=ns.Read(api.HasContainerItem,bag,slot)
                local record,recordStatus=ns.Read(api.GetContainerItemInfo,bag,slot)
                local id,idStatus=ns.Read(api.GetContainerItemID,bag,slot)
                local after,afterStatus=ns.Read(api.HasContainerItem,bag,slot)
                if status=="ok" and occupied==false and afterStatus=="ok" and after==false
                    and recordStatus=="unknown" and record==nil and idStatus=="unknown" and id==nil then
                    if not pcall(api.PickupContainerItem,bag,slot) then unavailable("Item placement blocked"); return end
                    ns.ClearActionFeedback(); ns.inventory.Request(scope); return
                end
            end
        end
    end
    unavailable("No confirmed free slot; use Native UI for special bags")
end
function ns.EnableItemDrag(button)
    button:RegisterForDrag("LeftButton")
    button:SetScript("OnDragStart",function() ns.MoveItem(button.entry) end)
    button:SetScript("OnReceiveDrag",function()
        if ns.Read(GetCursorInfo)=="item" then ns.MoveItem(button.entry) end
    end)
end
-- Preserve the template's Blizzard OnClick. Unlike a direct Lua API call,
-- InsecureActionButtonTemplate dispatches item use through the secure handler
-- outside combat, without making the inventory's layout protected in combat.
function ns.ConfigureItemButton(button)
    button:SetAttribute("useOnKeyDown",false)
    button:SetScript("PreClick",function(self,mouse)
        self:SetAttribute("type2",nil); self:SetAttribute("item2",nil)
        self.storageUse=false
        if mouse=="RightButton" and not ns.inventory.bankOpen then
            local reason=ns.ItemActionReason(self.entry) or specialInteraction()
            self.storageUse=true
            if reason then unavailable(reason,self.entry); return end
            self:SetAttribute("item2",self.entry.item.bag.." "..self.entry.item.slot)
            self:SetAttribute("type2","item")
        else
            ns.ItemClick(self.entry,mouse,self)
        end
    end)
    button:SetScript("PostClick",function(self)
        if self.storageUse and self:GetAttribute("type2")=="item" then
            ns.ClearActionFeedback(); ns.inventory.Request("bags")
        end
        self:SetAttribute("type2",nil); self:SetAttribute("item2",nil)
    end)
end
function ns.ItemClick(entry,mouse,button)
    if mouse=="LeftButton" and ns.Read(IsAltKeyDown)==true then
        if entry then ns.ToggleFavorite(entry.owner,entry.item.itemID) end
        return
    end
    local reason,liveCount=ns.ItemActionReason(entry)
    reason=reason or specialInteraction()
    if reason then unavailable(reason,entry); return end
    local api=C_Container or {}; local item=entry.item
    if mouse=="RightButton" then
        if not ns.inventory.bankOpen then
            unavailable("Use the item's right-click button",entry); return
        end
        local bankType=ns.inventory.bankOpen and ns.Read(function() return Enum.BankType.Character end) or nil
        if ns.inventory.bankOpen and bankType==nil then unavailable("Bank action unavailable"); return end
        if type(api.UseContainerItem)~="function" then unavailable("Item action unavailable"); return end
        local ok=pcall(api.UseContainerItem,item.bag,item.slot,nil,bankType,false)
        if not ok then unavailable("Item action blocked; use Native UI"); return end
    elseif mouse=="LeftButton" then
        if ns.Read(IsShiftKeyDown)==true then
            if liveCount<2 then unavailable("This stack has only one item"); return end
            if not button or not StackSplitFrame or type(StackSplitFrame.OpenStackSplitFrame)~="function" then
                unavailable("Stack splitting unavailable: use Native UI"); return
            end
            button.SplitStack=function(_,count)
                local blocked,currentCount=ns.ItemActionReason(entry)
                blocked=blocked or specialInteraction()
                if blocked then unavailable(blocked,entry); return end
                if not ns.Integer(count,1,currentCount-1) then unavailable("Choose a smaller valid stack size"); return end
                if type(api.SplitContainerItem)~="function" then unavailable("Stack splitting unavailable: use Native UI"); return end
                if not pcall(api.SplitContainerItem,item.bag,item.slot,count) then unavailable("Stack split blocked: use Native UI"); return end
                ns.ClearActionFeedback(); ns.inventory.Request(entry.scope)
            end
            ns.CloseItemSplit()
            StackSplitFrame:OpenStackSplitFrame(liveCount,button,"BOTTOMLEFT","TOPLEFT")
            splitOwner=button
            if type(StackSplitFrame.GetFrameStrata)=="function" then
                splitStrata=StackSplitFrame:GetFrameStrata()
                splitLevel=StackSplitFrame:GetFrameLevel()
                StackSplitFrame:SetFrameStrata("FULLSCREEN_DIALOG")
                StackSplitFrame:SetFrameLevel(100)
                if not StackSplitFrame.wfStorageLayerHook then
                    StackSplitFrame:HookScript("OnHide",restoreSplitLayer)
                    StackSplitFrame.wfStorageLayerHook=true
                end
            end
            return
        end
        if type(api.PickupContainerItem)~="function" then unavailable("Item movement unavailable"); return end
        if not pcall(api.PickupContainerItem,item.bag,item.slot) then unavailable("Item movement blocked"); return end
    else return end
    ns.ClearActionFeedback()
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
    ns.ClearActionFeedback(); ns.inventory.Request(scope)
end

local masked={}
local nativeShown=false
local merchantOpen=false
function ns.ReplaceNativeMerchantBags()
    if merchantOpen and not nativeShown and ns.InteractionReady() and type(CloseAllBags)=="function" then
        pcall(CloseAllBags)
    end
end
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
                ns.ReplaceNativeMerchantBags()
            end)
        end
    end
end
ns.On("PLAYER_ENTERING_WORLD",installHooks)
ns.On("MERCHANT_SHOW",function()
    merchantOpen=true; nativeShown=false
    if C_Timer and C_Timer.After then C_Timer.After(0,ns.ReplaceNativeMerchantBags) end
end)
ns.On("MERCHANT_CLOSED",function() merchantOpen=false;nativeShown=false end)
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
    ns.ReplaceNativeMerchantBags()
end)
ns.On("PLAYER_LEAVING_WORLD",function() restore(); nativeShown=false;merchantOpen=false end)

ns.On("PLAYER_LEAVING_WORLD",ns.ClearActionFeedback)
ns.On("PLAYER_LEAVING_WORLD",function() ns.CloseItemSplit() end)
