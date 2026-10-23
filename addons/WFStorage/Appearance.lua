local _, ns = ...
-- Independent presentation preferences. Never migrate or rewrite observations.
ns.ViewChoices = {
    view={"Grid","List"}, theme={"Slate","Warm","Midnight","Classic"}, opacity={0.85,0.95,1},
    iconSize={32,40,48}, columns={6,8,10}, order={"Slots","Name","Count","Category"}, category={"All","Equipment","Materials","Consumables","Other","Unknown"},
    windowScale={0.85,1,1.15}, fontSize={12,14,16},
}
local defaults={view="Grid",theme="Classic",opacity=0.95,iconSize=40,columns=8,
    category="All",order="Category",windowScale=1,fontSize=14}
ns.OptionHelp={showBagSlots="Show equipment slots for bags, built-in storage and locked bank expansions.",category="Filter this inventory window by item category. Missing metadata stays Unknown.",
    favoritesFirst="Show favorites first within the selected display order. Never moves items.",view="Choose an icon grid or a named item list.",theme="Choose the theme for all Storage windows.",
    opacity="Change the background opacity; item icons stay opaque.",iconSize="Size of inventory grid icons.",
    columns="Number of icons in each grid row.",fontSize="Size of item labels and counts.",
    windowScale="Scale the whole window; limited to fit your screen.",order="Display order only; does not move items.",
    showUnknown="Show unresolved slot observations for diagnostics.",showDetails="Show scan coverage details.",
    dimPoor="Dim poor-quality icons in Bags and Bank. This does not sell anything.",lockWindow="Prevent dragging inventory windows.",
    bindB="Use B to toggle Forever inventory. Your saved keybindings are preserved.",
    nativeUI="Show or hide native bags and bank for purchases, trading and special actions."}
function ns.SetTooltip(frame,message)
    frame:SetScript("OnEnter",function()
        if GameTooltip then GameTooltip:SetOwner(frame,"ANCHOR_CURSOR"); GameTooltip:SetText(message,1,.82,0,1,true); GameTooltip:Show() end
    end)
    frame:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
end
-- Bags retain legacy keys. Bank gets a one-time copy, never a live fallback.
function ns.BankViewSettings()
    if not ns.db then return {} end
    local saved=ns.db.settings
    if saved.storageBankView==nil then
        local bank={}
        for key in pairs(ns.ViewChoices) do bank[key]=saved[key] end
        for _,key in ipairs({"dimPoor","lockWindow","favoritesFirst","largeText"}) do bank[key]=saved[key] end
        saved.storageBankView=bank
    end
    return type(saved.storageBankView)=="table" and saved.storageBankView or {}
end
function ns.SetViewOption(key,value,target)
    if not ns.db then return end
    if key=="opacity" or key=="windowScale" then
        local low,high=key=="opacity" and 0.5 or 0.7,key=="opacity" and 1 or 1.3
        if type(value)~="number" or value~=value or value<low or value>high then return end
    elseif ns.ViewChoices[key] then
        local found=false; for _,v in ipairs(ns.ViewChoices[key]) do if v==value then found=true end end
        if not found then return end
    elseif type(ns.ViewOptions()[key])~="boolean" or type(value)~="boolean" then return end
    local bank=ns.BankViewSettings()
    if key=="theme" or key=="dimPoor" then target="main" end
    if target=="bank" and type(ns.db.settings.storageBankView)~="table" then return end
    local saved=target=="guild" and ns.GuildViewSettings() or target=="bank" and bank or ns.db.settings
    saved[key]=value
    if key=="bindB" and ns.UpdateInventoryBinding then ns.UpdateInventoryBinding() end
    ns.RefreshUI()
    if ns.RefreshBankUI then ns.RefreshBankUI() end
    if ns.RefreshGuildVault then ns.RefreshGuildVault() end
end
function ns.GuildViewSettings()
    if not ns.db then return {} end
    if ns.db.settings.storageGuildView==nil then ns.db.settings.storageGuildView={} end
    return type(ns.db.settings.storageGuildView)=="table" and ns.db.settings.storageGuildView or {}
end
ns.Themes={
    Slate={bg={0.055,0.075,0.10},accent={0.40,0.75,0.90},text={0.91,0.94,0.97}},
    Warm={bg={0.10,0.075,0.05},accent={0.94,0.73,0.38},text={0.97,0.93,0.85}},
    Midnight={bg={0.035,0.035,0.055},accent={0.70,0.58,0.94},text={0.93,0.91,0.98}},
    Classic={bg={0.11,0.075,0.04},accent={0.82,0.65,0.34},text={1,0.87,0.55},classic=true},
}
-- Client-owned textures are referenced, never bundled. These dialog assets
-- are also used by our Forever probe. Preview renders a color approximation.
local plainPanel={bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1}
-- The client dialog background has intrinsic transparency. A solid fill makes
-- opacity=1 genuinely opaque while preserving the Classic client border.
local classicPanel={bgFile="Interface\\Buttons\\WHITE8X8",
    edgeFile="Interface\\DialogFrame\\UI-DialogBox-Border",tile=true,tileSize=32,edgeSize=20,
    insets={left=5,right=5,top=5,bottom=5}}
function ns.ApplyPanelTheme(frame,theme,opacity)
    frame:SetBackdrop(theme.classic and classicPanel or plainPanel)
    frame:SetBackdropColor(theme.bg[1],theme.bg[2],theme.bg[3],opacity or 1)
    frame:SetBackdropBorderColor(unpack(theme.accent))
end
function ns.ApplyControlTheme(button,theme)
    local bg=theme.classic and {.22,.065,.035} or {theme.bg[1]+.055,theme.bg[2]+.055,theme.bg[3]+.055}
    button:SetBackdropColor(unpack(bg))
    button:SetBackdropBorderColor(unpack(theme.classic and {.43,.32,.16} or {.24,.28,.33}))
    if type(button.caption)=="table" or type(button.caption)=="userdata" then button.caption:SetTextColor(unpack(theme.text)) end
end
function ns.ViewOptions(target)
    local saved=target=="guild" and ns.GuildViewSettings() or target=="bank" and ns.BankViewSettings() or (ns.db and ns.db.settings or {})
    local result={}
    for key,values in pairs(ns.ViewChoices) do
        result[key]=defaults[key]
        for _,value in ipairs(values) do if saved[key]==value then result[key]=value end end
    end
    if saved.fontSize==nil and saved.largeText==true then result.fontSize=16 end
    for _,key in ipairs({"opacity","windowScale"}) do
        local low,high=key=="opacity" and 0.5 or 0.7,key=="opacity" and 1 or 1.3
        if type(saved[key])=="number" and saved[key]>=low and saved[key]<=high then result[key]=saved[key] end
    end
    for _,key in ipairs({"showUnknown","showDetails","lockWindow","dimPoor","favoritesFirst"}) do result[key]=saved[key]==true end
    -- Main preferences retain the original root keys. Legacy bank overrides are
    -- kept for preservation, but no longer determine these two shared options.
    local main=ns.db and ns.db.settings or {}
    result.theme=defaults.theme
    for _,value in ipairs(ns.ViewChoices.theme) do if main.theme==value then result.theme=value end end
    result.dimPoor=main.dimPoor~=false
    result.showBagSlots=saved.showBagSlots~=false
    result.bindB=saved.bindB~=false
    return result
end
function ns.CycleViewOption(key)
    if not ns.db then return end
    local values=ns.ViewChoices[key]
    local current=ns.ViewOptions()[key]
    if values then
        for i,value in ipairs(values) do
            if value==current then ns.SetViewOption(key,values[i % #values+1]); return end
        end
    elseif key=="showUnknown" or key=="showDetails" or key=="lockWindow" or key=="dimPoor" or key=="bindB" then
        ns.SetViewOption(key,not current)
    end
end
function ns.InventoryLayout(options,count)
    local grid=options.view=="Grid"
    local columns=grid and options.columns or 1
    local capacity=grid and columns*4 or 10
    local step=grid and options.iconSize+8 or math.max(30,options.fontSize+14)
    local width=grid and math.max(480,32+columns*step) or 540
    local visible=math.min(count,capacity)
    local lines=grid and math.max(1,math.ceil(visible/columns)) or math.max(1,visible)
    local top=options.showDetails and 190 or 154
    return {width=width,height=top+lines*step+82,top=top,step=step,columns=columns,
        capacity=capacity,grid=grid,bottom=top+lines*step+8}
end
function ns.SortInventory(rows,order,target)
    -- Stable tie-break by original location/slot order; this moves no game items.
    for i,row in ipairs(rows) do row.ordinal=i end
    local favoritesFirst=ns.ViewOptions(target).favoritesFirst
    if order=="Slots" and not favoritesFirst then return end
    table.sort(rows,function(a,b)
        if favoritesFirst and a.favorite~=b.favorite then return a.favorite==true end
        if order=="Category" and a.category~=b.category then return (a.category or "Unknown")<(b.category or "Unknown") end
        if order=="Name" and a.name:lower()~=b.name:lower() then return a.name:lower()<b.name:lower() end
        if order=="Count" and (a.item.count or -1)~=(b.item.count or -1) then return (a.item.count or -1)>(b.item.count or -1) end
        return a.ordinal<b.ordinal
    end)
end

-- Do not use UISpecialFrames: this client closes those during NPC interactions.
-- Keyboard propagation keeps ordinary keys available to the game.
function ns.EnableEscapeClose(frame, callback)
    if type(frame.EnableKeyboard)~="function" or type(frame.SetPropagateKeyboardInput)~="function" then return end
    frame:EnableKeyboard(true)
    frame:SetPropagateKeyboardInput(true)
    frame:SetScript("OnKeyDown",function(self,key)
        local combat,status=ns.Read(InCombatLockdown)
        if status=="ok" and not combat then self:SetPropagateKeyboardInput(key~="ESCAPE") end
        if key=="ESCAPE" then callback() end
    end)
end

-- Presentation metadata is never written back into saved observations.
ns.QualityColors={[0]={.45,.45,.45},[1]={.65,.65,.65},[2]={.2,.8,.3},
    [3]={.2,.5,1},[4]={.7,.3,.95},[5]={1,.55,.12},[6]={.9,.8,.5},[7]={.4,.8,1},[8]={.4,.8,1}}
function ns.ItemCategory(item)
    if item.state~="observed" or not item.itemID then return "Unknown" end
    local class=ns.Read(function() return select(6,C_Item.GetItemInfoInstant(item.itemID)) end)
    local classes=Enum and Enum.ItemClass
    if not ns.Integer(class,0,100) or type(classes)~="table" then return "Unknown" end
    if class==classes.Weapon or class==classes.Armor then return "Equipment" end
    if class==classes.Tradegoods or class==classes.Reagent then return "Materials" end
    if class==classes.Consumable then return "Consumables" end
    return "Other"
end
function ns.CapacityText(snapshot)
    if type(snapshot)~="table" then return "capacity unobserved" end
    if snapshot.coverage~="complete" or not ns.Integer(snapshot.expectedSlots,0,100000)
        or not ns.Integer(snapshot.emptySlots,0,snapshot.expectedSlots) then return "capacity incomplete" end
    return snapshot.emptySlots.."/"..snapshot.expectedSlots.." free"
end

-- Layout-only sections. Headers consume space; every page repeats its first
-- category so a continuation is understandable without the previous page.
function ns.CategoryPages(items,columns,step,budget,capacity,collapsed,target)
    collapsed=collapsed or {}
    local pages={}; local current; local key; local column=0; local y=0
    local counts={}
    local function category(entry)
        return (ns.ViewOptions(target).favoritesFirst and entry.favorite and "Favorites / " or "")..(entry.category or "Unknown")
    end
    for _,entry in ipairs(items) do local k=category(entry); counts[k]=(counts[k] or 0)+1 end
    local function begin()
        current={entries={},headers={},height=0}; pages[#pages+1]=current
        key=nil; column=0; y=0
    end
    begin()
    for _,entry in ipairs(items) do
        local group=category(entry); local folded=collapsed[group]==true
        if not folded or group~=key then
            local newGroup=group~=key; local nextY=y
            if newGroup and column>0 then nextY=nextY+step end
            if not newGroup and column==columns then nextY=nextY+step end
            local needed=nextY+(newGroup and 24 or 0)+(folded and 0 or step)
            if (not folded and #current.entries>=capacity) or needed>budget then begin(); newGroup=true; nextY=0 end
            if newGroup then
                y=nextY; current.headers[#current.headers+1]={key=group,count=counts[group],collapsed=folded,
                    text=(folded and "+ " or "- ")..group.." ("..counts[group]..(counts[group]==1 and " stack)" or " stacks)"),y=y}
                y=y+24; column=0; key=group; current.height=y
            elseif column==columns then y=nextY; column=0 end
            if not folded then
                current.entries[#current.entries+1]={entry=entry,x=column*step,y=y}
                column=column+1; current.height=y+step
            end
        end
    end
    return pages
end
function ns.CreateCategoryHeader(parent,callback)
    local header=CreateFrame("Button",nil,parent)
    local caption=header:CreateFontString(nil,"OVERLAY","GameFontNormal")
    caption:SetFont("Fonts\\FRIZQT__.TTF",12); caption:SetJustifyH("LEFT")
    caption:SetPoint("TOPLEFT",0,0)
    header.caption=caption
    header:SetScript("OnClick",function() callback(header.categoryKey) end)
    ns.SetTooltip(header,"Click to expand or collapse")
    return header
end

function ns.FilterSummary(query,category,favorites)
    local filters={}
    if query and query~="" then filters[#filters+1]="Search" end
    if category and category~="All" then filters[#filters+1]=category end
    if favorites then filters[#filters+1]="Favorites" end
    return #filters>0 and "Filters: "..table.concat(filters," / ") or nil
end

-- Original geometric lock glyph; no bundled artwork or font symbols required.
function ns.RefreshLockButton(button,target)
    local locked=ns.ViewOptions(target).lockWindow
    local theme=ns.Themes[ns.ViewOptions(target).theme]
    ns.ApplyControlTheme(button,theme)
    local tint=theme.classic and (locked and theme.text or theme.accent) or (locked and {.95,.72,.3} or {.45,.8,.95})
    for _,part in ipairs(button.parts) do part:SetBackdropColor(unpack(tint)) end
    if locked then button.parts[4]:Show() else button.parts[4]:Hide() end
    ns.SetTooltip(button,(locked and "Unlock " or "Lock ")..(target=="guild" and "guild" or target=="bank" and "bank" or "bags").." window position")
end
function ns.CreateLockButton(parent,target)
    local button=CreateFrame("Button",nil,parent,"BackdropTemplate")
    button:SetSize(26,26); button:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1})
    button:SetBackdropColor(.1,.13,.17,1); button:SetBackdropBorderColor(.3,.4,.5,1)
    button.lockTarget=target; button.parts={}
    for _,rect in ipairs({{6,12,14,10},{8,5,10,2},{8,5,2,8},{16,5,2,8}}) do
        local part=CreateFrame("Frame",nil,button,"BackdropTemplate")
        part:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8"}); part:SetPoint("TOPLEFT",rect[1],-rect[2]); part:SetSize(rect[3],rect[4])
        button.parts[#button.parts+1]=part
    end
    button:SetScript("OnClick",function() ns.SetViewOption("lockWindow",not ns.ViewOptions(target).lockWindow,target) end)
    ns.RefreshLockButton(button,target); return button
end
