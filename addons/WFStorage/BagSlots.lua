local _,ns=...
-- Forever 70245 Camelot bankframe.lua and shared mainmenubarbagbuttons.lua.
-- Equipment state is live/session-only: never merge it into inventory snapshots.
local strips={}
local messages={}
local pendingPurchase
local function readGlobal(name) return ns.Read(function() return _G[name] end) end
local function bankType() return ns.Read(function() return Enum.BankType.Character end) end
local function refresh()
    if ns.RefreshUI then ns.RefreshUI() end
    if ns.RefreshBankUI then ns.RefreshBankUI() end
end
local function report(scope,message) messages[scope]=message; refresh() end
local function money(value)
    return math.floor(value/10000).."g "..math.floor(value/100)%100 .."s "..value%100 .."c"
end
local function bankState()
    if not ns.inventory.bankOpen then return nil end
    local api=C_Bank or {}; local kind=bankType()
    if kind==nil or ns.Read(api.ShouldUsePlayerBagsInBank)~=true then return nil end
    local count=ns.Read(api.FetchNumPurchasedBankTabs,kind)
    local maximum=ns.Read(api.FetchMaxNumBankTabs,kind)
    if not ns.Integer(maximum,1,9) or not ns.Integer(count,1,maximum) then return nil end
    local nextTab=ns.Read(api.FetchNextPurchasableBankTabData,kind)
    local cost=ns.Field(nextTab,"tabCost")
    return {count=count,maximum=maximum,kind=kind,cost=ns.Integer(cost,0,2147483647) and cost or nil,
        affordable=ns.Field(nextTab,"canAfford")==true,canBuy=ns.Read(api.CanPurchaseBankTab,kind)==true}
end
local function bagState(id)
    local size=ns.Read(C_Container and C_Container.GetContainerNumSlots,id)
    if ns.Integer(size,1,200) then return "Equipped",size end
    if size==0 then return "Empty",0 end
    return "Unknown",nil
end
function ns.BagSlotEntries(scope,owner)
    if owner~=ns.owner or not ns.inWorld then return {},"Saved view: bag equipment unavailable" end
    local out={}
    if scope=="bank" then
        local state=bankState()
        if not state then return {},"Bank bag slots unavailable; visit a banker" end
        out[#out+1]={scope=scope,index=1,label="Bank",state="Fixed",owner=owner}
        for i=2,state.maximum do
            local id=ns.Read(function() return Enum.BagIndex["CharacterBankTab_"..i] end)
            local status,size="Unknown",nil
            if i>state.count then status="Locked" elseif ns.Integer(id,6,14) then status,size=bagState(id) end
            out[#out+1]={scope=scope,index=i,label=tostring(i-1),state=status,size=size,owner=owner,
                next=i==state.count+1,cost=state.cost}
        end
        return out,"Bank bags: click locked slot to purchase; drop a bag to equip"
    end
    out[#out+1]={scope=scope,index=0,label="Pack",state="Fixed",owner=owner}
    local count=readGlobal("NUM_TOTAL_EQUIPPED_BAG_SLOTS")
    local regular=readGlobal("NUM_BAG_SLOTS")
    local reagent=readGlobal("NUM_REAGENTBAG_SLOTS")
    if ns.Integer(count,0,10) then
        for i=1,count do
            local status,size=bagState(i)
            local isReagent=ns.Integer(regular,0,10) and ns.Integer(reagent,0,10)
                and regular+reagent==count and i>regular
            out[#out+1]={scope=scope,index=i,label=isReagent and "Reag" or tostring(i),state=status,size=size,owner=owner}
        end
    end
    local key=readGlobal("KEYRING_CONTAINER")
    if ns.Integer(key,-2,-1) and key==ns.Read(function() return Enum.BagIndex.Keyring end) then
        local size=ns.Read(C_Container and C_Container.GetContainerNumSlots,key)
        out[#out+1]={scope=scope,index=key,label="Keys",state=ns.Integer(size,1,200) and "Available" or "Unknown",
            size=ns.Integer(size,1,200) and size or nil,owner=owner,keyStorage=true}
    end
    return out,"Bag slots: drop a bag to equip; Pack is built-in"
end
local function purchaseData()
    if not ns.InteractionReady() or not ns.inventory.bankOpen then return nil end
    local s=bankState()
    if not s or not s.canBuy or not s.affordable or not s.cost or s.count>=s.maximum then return nil end
    return s
end
function ns.ConfirmBankSlotPurchase(data)
    local expected=pendingPurchase; pendingPurchase=nil
    local now=purchaseData()
    if data~=expected or not data or data.owner~=ns.owner or not now or now.count~=data.count or now.cost~=data.cost then
        report("bank","Purchase changed or unavailable; select the slot again"); return false
    end
    if not C_Bank or type(C_Bank.PurchaseBankTab)~="function" then return false end
    local ok=pcall(C_Bank.PurchaseBankTab,now.kind)
    report("bank",ok and "Purchase requested; waiting for bank update" or "Purchase blocked; use Main settings > Native UI")
    return ok
end
function ns.BagSlotClick(entry)
    if not entry or entry.owner~=ns.owner or not ns.InteractionReady() then return end
    if entry.scope=="bank" and not ns.inventory.bankOpen then return end
    if entry.keyStorage then report(entry.scope,"Key storage: use Native UI to inspect availability"); return end
    if entry.state=="Fixed" then report(entry.scope,"Built-in storage cannot be replaced"); return end
    -- Re-read after every click; never act on an old lock state or character.
    local entries=ns.BagSlotEntries(entry.scope,entry.owner); local current
    for _,row in ipairs(entries) do if row.index==entry.index then current=row end end
    if not current then return end
    if current.state=="Locked" then
        local data=purchaseData()
        if not current.next or not data then report("bank","Next slot unavailable or insufficient money"); return end
        if type(StaticPopupDialogs)~="table" or type(StaticPopup_Show)~="function" then report("bank","Purchase confirmation unavailable"); return end
        StaticPopupDialogs.WFSTORAGE_BUY_BANK_SLOT={text="Unlock the next bank bag slot for %s?",button1="Purchase",button2="Cancel",
            timeout=0,whileDead=false,hideOnEscape=true,preferredIndex=3,
            OnAccept=function(_,request) ns.ConfirmBankSlotPurchase(request) end,
            OnCancel=function() pendingPurchase=nil end}
        pendingPurchase={owner=ns.owner,count=data.count,cost=data.cost}
        StaticPopup_Show("WFSTORAGE_BUY_BANK_SLOT",money(data.cost),nil,pendingPurchase)
        return
    end
    if current.state=="Unknown" then report(entry.scope,"Bag slot unreadable; try again after refresh"); return end
    if ns.Read(GetCursorInfo)~="item" then report(entry.scope,"Pick up a bag, then click or drop it here"); return end
    local cursorID=ns.Read(function() return select(2,GetCursorInfo()) end)
    local equip=ns.Read(function() return select(4,C_Item.GetItemInfoInstant(cursorID)) end)
    if equip~="INVTYPE_BAG" and equip~="INVTYPE_QUIVER" then report(entry.scope,"Only a readable bag can be placed here"); return end
    local ok=false
    if entry.scope=="bank" then
        local container=ns.Read(function() return Enum.BagIndex.Characterbanktab end)
        if ns.Integer(container,-10,100) and C_Container and type(C_Container.PickupContainerItem)=="function" then
            ok=pcall(C_Container.PickupContainerItem,container,entry.index)
        end
    else
        local slot=ns.Read(C_Container and C_Container.ContainerIDToInventoryID,entry.index)
        if ns.Integer(slot,1,200) and type(PutItemInBag)=="function" then ok=pcall(PutItemInBag,slot) end
    end
    report(entry.scope,ok and "Bag placement requested; waiting for update" or "Bag placement unavailable; use Main settings > Native UI")
end
local backdrop={bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1}
function ns.RefreshBagSlotStrip(parent,scope,owner,y,width)
    local strip=strips[scope]
    if not strip then
        strip={buttons={}}; strips[scope]=strip
        strip.title=parent:CreateFontString(nil,"OVERLAY","GameFontNormal")
        strip.title:SetFont("Fonts\\FRIZQT__.TTF",11); strip.title:SetJustifyH("LEFT")
        strip.toggle=CreateFrame("Button",nil,parent,"BackdropTemplate")
        strip.toggle:SetSize(20,20); strip.toggle:SetBackdrop(backdrop)
        strip.toggle:SetBackdropColor(.08,.1,.14,1); strip.toggle:SetBackdropBorderColor(.35,.65,.8,1)
        strip.toggle.bagSlotToggle=scope
        strip.toggle.caption=strip.toggle:CreateFontString(nil,"OVERLAY","GameFontNormal")
        strip.toggle.caption:SetPoint("CENTER"); strip.toggle.caption:SetFont("Fonts\\FRIZQT__.TTF",14)
        strip.toggle.caption:SetTextColor(.4,.8,1)
        strip.toggle:RegisterForClicks("LeftButtonUp")
        strip.toggle:SetScript("OnClick",function()
            ns.SetViewOption("showBagSlots",not ns.ViewOptions(scope).showBagSlots,scope)
        end)
    end
    strip.title:Hide(); for _,b in ipairs(strip.buttons) do b:Hide() end
    local expanded=ns.ViewOptions(scope).showBagSlots
    local theme=ns.Themes[ns.ViewOptions(scope).theme]
    local accent=theme.classic and theme.accent or {.35,.65,.8}
    ns.ApplyControlTheme(strip.toggle,theme)
    strip.toggle:SetBackdropBorderColor(unpack(accent))
    strip.toggle.caption:SetTextColor(unpack(accent))
    strip.toggle:ClearAllPoints(); strip.toggle:SetPoint("TOPLEFT",16,-y); strip.toggle:Show()
    strip.toggle.caption:SetText(expanded and "-" or "+")
    ns.SetTooltip(strip.toggle,(expanded and "Hide " or "Show ")..(scope=="bank" and "bank bag slots" or "bag slots"))
    strip.title:ClearAllPoints(); strip.title:SetPoint("TOPLEFT",42,-y); strip.title:SetSize(width-58,28)
    strip.title:SetTextColor(.65,.73,.8); strip.title:Show()
    if not expanded then
        strip.title:SetText(scope=="bank" and "Bank bag slots" or "Bag slots")
        return 28
    end
    local entries,hint=ns.BagSlotEntries(scope,owner)
    strip.title:SetText(messages[scope] or hint)
    local columns=math.max(1,math.floor((width-32)/44))
    for i,entry in ipairs(entries) do
        local b=strip.buttons[i]
        if not b then
            b=CreateFrame("Button",nil,parent,"BackdropTemplate"); b:SetBackdrop(backdrop); b:SetSize(40,32)
            b.caption=b:CreateFontString(nil,"OVERLAY","GameFontNormal"); b.caption:SetFont("Fonts\\FRIZQT__.TTF",10)
            b.caption:SetPoint("CENTER"); b.caption:SetSize(38,30); b.caption:SetJustifyH("CENTER")
            b:RegisterForClicks("LeftButtonUp"); b:SetScript("OnClick",function() ns.BagSlotClick(b.slotEntry) end)
            b:SetScript("OnReceiveDrag",function() ns.BagSlotClick(b.slotEntry) end)
            strip.buttons[i]=b
        end
        b.slotEntry=entry; b:ClearAllPoints(); b:SetPoint("TOPLEFT",16+((i-1)%columns)*44,-y-28-math.floor((i-1)/columns)*36)
        ns.ApplyControlTheme(b,theme)
        local locked=entry.state=="Locked"
        b:SetBackdropBorderColor(unpack(locked and {.8,.2,.2} or accent))
        b.caption:SetText(entry.label.."\n"..(locked and "Locked" or entry.size and (entry.size==0 and "Empty" or entry.size.." slots") or entry.state))
        b.caption:SetTextColor(unpack(theme.text))
        ns.SetTooltip(b,(scope=="bank" and "Bank bag " or "Bag ")..entry.label..": "..entry.state..
            (locked and entry.next and entry.cost and ("\nNext unlock: "..money(entry.cost)) or ""))
        b:Show()
    end
    return 36+math.ceil(#entries/columns)*36
end
for _,event in ipairs({"BANK_TABS_CHANGED","BAG_CONTAINER_UPDATE","PLAYERBANKBAGSLOTS_CHANGED","PLAYER_EQUIPMENT_CHANGED","PLAYER_MONEY","PLAYER_ENTERING_WORLD","BANKFRAME_CLOSED"}) do
    local name=event
    ns.On(name,function()
        messages={}; pendingPurchase=nil
        if name=="BANK_TABS_CHANGED" and ns.inventory.bankOpen then ns.inventory.Request("bank") end
        refresh()
    end)
end

ns.On("PLAYER_LEAVING_WORLD",function() pendingPurchase=nil; messages={} end)
