local _, ns = ...
local window, search, heading, status, footer, previous, nextPage, settingsPanel, empty
local sellJunkButton,guildButton
local rows, tabs, controls, settingsRows = {}, {}, {}, {}
local page, scope, settingsPage = 1, "bags", "Appearance"
local hideReason, lastInteraction
local viewedGUID, favoritesOnly = nil, false
local characterPanel, characterHeading, characterButtons, characterPage = nil, nil, {}, 1
local refreshButton, normalButton, favoriteButton, characterButton, currentButton
local optionPanel,optionKey
local settingsSliders={}
local lockButton
local sliderKeys={opacity=true,windowScale=true,fontSize=true,columns=true,iconSize=true}
local optionButtons={}
local categoryHeaders={}
local collapsedCategories={}
local filterLabel,clearFilters
local settingsTarget,settingsTitle="bags",nil
local mainSettingsButton,settingsHelp
local settingsTabs={}
local backdrop={bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1}
local qualityColors={[0]={0.45,0.45,0.45},[1]={0.65,0.65,0.65},[2]={0.2,0.8,0.3},
    [3]={0.2,0.5,1},[4]={0.7,0.3,0.95},[5]={1,0.55,0.12}}
local function label(parent,size)
    local text=parent:CreateFontString(nil,"OVERLAY","GameFontNormal")
    text:SetFont("Fonts\\FRIZQT__.TTF",size); text:SetJustifyH("LEFT")
    return text
end
local function button(parent,text,x,y,width,callback)
    local b=CreateFrame("Button",nil,parent,"BackdropTemplate")
    b:SetSize(width,26); b:SetPoint("TOPLEFT",x,y); b:SetBackdrop(backdrop)
    b.caption=label(b,12); b.caption:SetPoint("CENTER"); b.caption:SetJustifyH("CENTER")
    b.caption:SetSize(width-8,22)
    function b:SetText(value) self.caption:SetText(value); self.text=value end
    b:SetText(text); b:SetScript("OnClick",callback)
    b:SetScript("OnEnter",function() b:SetBackdropBorderColor(0.8,0.85,0.9,1) end)
    b:SetScript("OnLeave",function() ns.RefreshUI() end)
    controls[#controls+1]=b
    return b
end
local function close(reason) hideReason=reason; window:Hide() end
function ns.CloseInventoryWindows()
    if window then close("escape") end
    if ns.HideBankUI then ns.HideBankUI() end
    if ns.inventory.bankOpen and ns.InteractionReady() and C_Bank and type(C_Bank.CloseBankFrame)=="function" then
        C_Bank.CloseBankFrame()
    end
end
local function shortLabel(value,limit)
    value=tostring(value)
    return #value>limit and value:sub(1,limit-3).."..." or value
end
-- Viewing saved alts never changes the collector's owner or current snapshots.
function ns.ViewedCharacter()
    if viewedGUID and ns.db then return ns.db.characters[viewedGUID], viewedGUID end
    return ns.character, ns.owner
end
function ns.SelectCharacter(guid)
    if guid and guid~=ns.owner then
        local c=ns.db and ns.db.characters[guid]
        if type(c)~="table" or type(c.locations)~="table" or type(c.identity)~="table" then return false end
    end
    viewedGUID=guid~=ns.owner and guid or nil; page=1
    if characterPanel then characterPanel:Hide() end
    ns.RefreshUI(); return true
end
function ns.SnapshotAge(at)
    local now=ns.Stamp()
    if not ns.Integer(at,0,9999999999) or not ns.Integer(now,0,9999999999) then return "age unknown" end
    local age=now-at
    if age<0 then return "clock mismatch" end
    if age<60 then return "just now" end
    if age<3600 then return math.floor(age/60).."m ago" end
    if age<86400 then return math.floor(age/3600).."h ago" end
    return math.floor(age/86400).."d ago"
end
function ns.IsFavorite(guid,id)
    local all=ns.db and ns.db.settings.favorites
    local owned=type(all)=="table" and all[guid]
    return type(owned)=="table" and owned[tostring(id)]==true or false
end
function ns.ToggleFavorite(guid,id)
    if not ns.db or not guid or not ns.db.characters[guid] or not ns.Integer(id,1,2147483647) then return false end
    local saved=ns.db.settings
    if saved.favorites~=nil and type(saved.favorites)~="table" then return false end
    saved.favorites=saved.favorites or {}
    if saved.favorites[guid]~=nil and type(saved.favorites[guid])~="table" then return false end
    saved.favorites[guid]=saved.favorites[guid] or {}
    saved.favorites[guid][tostring(id)]=not ns.IsFavorite(guid,id) or nil
    ns.RefreshUI(); return true
end
function ns.SavedCharacters()
    local result={}
    for guid,c in pairs(ns.db and ns.db.characters or {}) do
        if type(guid)=="string" and type(c)=="table" and type(c.identity)=="table" and type(c.locations)=="table" then
            result[#result+1]={guid=guid,label=ns.CharacterLabel(c.identity),realm=c.identity.realm or "Unknown realm"}
        end
    end
    table.sort(result,function(a,b)
        if a.label~=b.label then return a.label<b.label end
        return a.guid<b.guid
    end)
    return result
end
function ns.InventoryRows(filter, query, includeUnknown, currentOnly)
    local result, notes={},{}
    local character,guid=ns.ViewedCharacter()
    if currentOnly then character,guid=ns.character,ns.owner end
    query=(query or ""):lower()
    for _,locationName in ipairs({"bags","bank"}) do
        if filter == "all" or filter == locationName then
            local location=character and character.locations[locationName]
            local snapshot=type(location)=="table" and location.latest
            local attempt=type(location)=="table" and location.attempt
            if not snapshot and type(attempt)=="table" then snapshot=attempt end
            local current=guid==ns.owner and snapshot and ns.inventory.current[locationName] == snapshot
            local freshness=current and "this session" or "historical"
            if locationName == "bank" and (guid~=ns.owner or not ns.inventory.bankOpen) then freshness="cached" end
            if type(attempt)=="table" then freshness=snapshot==attempt and "partial attempt" or "previous; scan incomplete" end
            if type(snapshot) == "table" and type(snapshot.slots) == "table" then
                notes[#notes+1]=locationName..": "..freshness..", "..ns.SnapshotAge(snapshot.finishedAt)..", "..ns.CapacityText(snapshot).." / "..tostring(snapshot.coverage)
                    .." / "..tostring(snapshot.unknownSlots or "?").." unresolved"
                for _,item in ipairs(snapshot.slots) do
                    if type(item)=="table" and (item.state=="observed" or (includeUnknown and item.state=="unknown")) then
                        local name=type(item.name)=="string" and item.name or (item.itemID and "Item "..item.itemID or "Unknown slot")
                        local category=ns.ItemCategory(item)
                        local selected=ns.ViewOptions(currentOnly and "bank" or "bags").category
                        if (selected=="All" or selected==category) and (name.." "..tostring(item.itemID or "")):lower():find(query,1,true) then
                            result[#result+1]={item=item,name=name,scope=locationName,at=snapshot.finishedAt,
                                category=category,owner=guid,snapshot=snapshot,favorite=ns.IsFavorite(guid,item.itemID)}
                        end
                    end
                end
            else notes[#notes+1]=locationName..": unobserved" end
        end
    end
    return result, table.concat(notes,"\n")
end
function ns.CharacterLabel(identity)
    local first=identity.firstName or "Unknown character"
    return first..(type(identity.lastName)=="string" and identity.lastName~="" and " "..identity.lastName or "")
end

local settingsDefs={
    Main={{"theme","Theme"},{"dimPoor","Dim poor quality"},{"nativeUI","Native UI"}},
    Organize={{"category","Category filter"},{"order","Display order"},{"favoritesFirst","Favorites first"},
        {"showUnknown","Unresolved slots"},{"showDetails","Scan details"},{"bindB","B shortcut"}},
    Appearance={{"view","View"},{"opacity","Background"},{"iconSize","Icon size"},
        {"columns","Grid columns"},{"fontSize","Text size"},{"windowScale","Window scale"}},
}
local function optionText(key,value)
    if type(value)=="boolean" then return value and "On" or "Off" end
    if key=="opacity" or key=="windowScale" then return math.floor(value*100+0.5).."%" end
    return tostring(value)
end
local function openOptions(key,anchor)
    if key=="nativeUI" then if optionPanel then optionPanel:Hide() end; ns.ToggleNativeUI(); return end
    if optionPanel and optionPanel:IsShown() and optionKey==key then optionPanel:Hide(); return end
    if not optionPanel then
        optionPanel=CreateFrame("Frame",nil,settingsPanel,"BackdropTemplate")
        optionPanel:SetBackdrop(backdrop); optionPanel:SetClampedToScreen(true); optionPanel:EnableMouse(true)
        optionPanel:SetFrameStrata("TOOLTIP")
        for i=1,6 do
            local b
            b=button(optionPanel,"",4,-4-(i-1)*28,270,function()
                ns.SetViewOption(optionKey,b.value,settingsTarget); optionPanel:Hide()
            end)
            optionButtons[i]=b
        end
    end
    local o=ns.ViewOptions(settingsTarget); local t=ns.Themes[o.theme]
    ns.ApplyPanelTheme(optionPanel,t)
    local values=ns.ViewChoices[key] or {true,false}
    optionPanel:ClearAllPoints(); optionPanel:SetPoint("TOPLEFT",anchor,"BOTTOMLEFT",0,-2)
    optionPanel:SetSize(278,8+#values*28)
    for i,b in ipairs(optionButtons) do
        if values[i]~=nil then
            b.value=values[i]; b:SetText(optionText(key,b.value)..(b.value==o[key] and "  *" or "")); b:Show()
            ns.SetTooltip(b,ns.OptionHelp[key])
        else b:Hide() end
    end
    optionKey=key; optionPanel:Show(); ns.RefreshUI()
end
local function updateSettings(o,t)
    o=ns.ViewOptions(settingsTarget); t=ns.Themes[o.theme]
    -- Settings can refresh while Bags is hidden, including first use and dropdowns.
    for _,b in ipairs(controls) do
        if b:GetParent()==settingsPanel or (optionPanel and b:GetParent()==optionPanel) then
            ns.ApplyControlTheme(b,t)
        end
    end
    local isMain=settingsPage=="Main"
    local windowName=settingsTarget=="guild" and "Guild" or settingsTarget=="bank" and "Bank" or "Bags"
    settingsTitle:SetText(isMain and "Main settings" or windowName.." settings")
    mainSettingsButton:SetText(isMain and "Back to "..windowName.." settings" or "Main settings (all windows)")
    settingsHelp:SetText(isMain and "Shared theme and quality dimming." or settingsTarget=="guild" and "Guild layout only. Logs and Info are read-only." or "Drag sliders or choose from dropdowns.\nAlt+left-click an item to toggle its favorite.")
    for key,b in pairs(settingsTabs) do
        b:SetText(key)
        if key==settingsPage then
            b:SetBackdropBorderColor(unpack(t.accent)); b.caption:SetTextColor(unpack(t.accent))
        end
        if isMain then b:Hide() else b:Show() end
    end
    local defs={}
    for _,def in ipairs(settingsDefs[settingsPage]) do
        local key=def[1]
        local hiddenGuild=settingsTarget=="guild" and (key=="showUnknown" or key=="showDetails" or key=="bindB" or key=="favoritesFirst")
        if not hiddenGuild and (settingsTarget~="bank" or (key~="view" and key~="showUnknown" and key~="showDetails" and key~="bindB")) then defs[#defs+1]=def end
    end
    local y=isMain and 86 or 120
    for i,b in ipairs(settingsRows) do
        local def=defs[i]; local slider=settingsSliders[i]
        b.key=def and def[1] or nil
        if def then
            local key=def[1]
            if sliderKeys[key] then
                b:Hide(); b.key=nil
                local sameControl=slider.key==key and slider.settingsTarget==settingsTarget and slider:IsShown()
                -- Hiding/reanchoring a slider in its value callback releases the
                -- native drag. Keep the active control stable across refreshes.
                if not sameControl then
                    slider:ClearAllPoints(); slider:SetPoint("TOPLEFT",24,-y-24)
                end
                slider.caption:ClearAllPoints(); slider.caption:SetPoint("TOPLEFT",settingsPanel,"TOPLEFT",16,-y)
                slider.caption:SetText(def[2]..": "..optionText(key,o[key])); slider.caption:SetTextColor(unpack(t.text))
                slider.sliderAccent=t.classic and t.accent or {.25,.75,.95}
                slider:SetBackdropColor(t.bg[1]+.055,t.bg[2]+.055,t.bg[3]+.055,1)
                slider:SetBackdropBorderColor(unpack(t.classic and t.accent or {.3,.4,.5}))
                local thumb=slider:GetThumbTexture()
                if thumb then thumb:SetVertexColor(unpack(t.classic and t.accent or {1,1,1})) end
                slider.syncing=true
                if not slider.userChanging then
                    if key=="opacity" or key=="windowScale" then
                        slider:SetMinMaxValues(key=="opacity" and 50 or 70,key=="opacity" and 100 or 130)
                        slider:SetValue(o[key]*100)
                    else
                        slider:SetMinMaxValues(1,#ns.ViewChoices[key])
                        for index,value in ipairs(ns.ViewChoices[key]) do if value==o[key] then slider:SetValue(index) end end
                    end
                end
                slider.syncing=false; slider.key=key; slider.settingsTarget=settingsTarget; slider:Show(); slider.caption:Show()
                ns.SetTooltip(slider,ns.OptionHelp[key]); y=y+56
            else
                slider.key=nil; slider:Hide(); slider.caption:Hide()
                b:ClearAllPoints(); b:SetPoint("TOPLEFT",16,-y)
                b:SetText(key=="nativeUI" and "Native UI: show / hide" or def[2]..": "..optionText(key,o[key]).."  v")
                ns.SetTooltip(b,ns.OptionHelp[key]); b:Show(); y=y+34
            end
        else b:Hide(); slider.key=nil; slider:Hide(); slider.caption:Hide() end
    end
    local height=y+60
    local scale=math.min(1,UIParent:GetHeight()/(height+24),UIParent:GetWidth()/330)
    -- Keep the title and navigation still while pages grow downward. Preserve
    -- existing center-based saved positions; screen clamping remains authoritative.
    if settingsPanel:IsShown() and (height~=settingsPanel:GetHeight() or scale~=settingsPanel:GetScale()) then
        local x,y=settingsPanel:GetCenter(); local px,py=UIParent:GetCenter()
        local oldScale=settingsPanel:GetScale()
        if type(x)=="number" and type(y)=="number" and type(px)=="number" and type(py)=="number" then
            local left=(x-settingsPanel:GetWidth()/2)*oldScale
            local top=(y+settingsPanel:GetHeight()/2)*oldScale
            settingsPanel:ClearAllPoints()
            settingsPanel:SetPoint("TOPLEFT",UIParent,"CENTER",(left-px)/scale,(top-py)/scale)
        end
    end
    settingsPanel:SetHeight(height); settingsPanel:SetScale(scale)
    ns.ApplyPanelTheme(settingsPanel,t)
end
function ns.ApplyWindowScale()
    if not window then return end
    local o=ns.ViewOptions()
    window:SetScale(math.min(o.windowScale,UIParent:GetHeight()/math.max(window:GetHeight()+24,370),
        UIParent:GetWidth()/(window:GetWidth()+24)))
end
function ns.RefreshUI()
    if not window or not window:IsShown() then
        if settingsPanel and settingsPanel:IsShown() then updateSettings() end
        return
    end
    local o=ns.ViewOptions(); local t=ns.Themes[o.theme]
    local items,notes=ns.InventoryRows(scope,search:GetText(),o.showUnknown)
    local character,guid=ns.ViewedCharacter()
    local historical=guid~=ns.owner
    local notice=ns.StatusNotice()
    local location=character and character.locations.bags
    local liveBags=scope=="bags" and not historical and location and not location.attempt
        and location.latest and location.latest==ns.inventory.current.bags
        and location.latest.coverage=="complete"
    local compactBags=liveBags and not o.showDetails and notice=="Ready"
    local freeText=liveBags and ns.CapacityText(location.latest) or nil
    if favoritesOnly then
        local filtered={}; for _,entry in ipairs(items) do if entry.favorite then filtered[#filtered+1]=entry end end
        items=filtered
    end
    ns.SortInventory(items,o.order)
    local initial=ns.InventoryLayout(o,#items)
    local pages=math.max(1,math.ceil(#items/initial.capacity)); if o.order~="Category" then page=math.min(page,pages) end
    local layout=ns.InventoryLayout(o,math.max(0,#items-(page-1)*initial.capacity))
    local section
    if o.order=="Category" then
        local sections=ns.CategoryPages(items,initial.columns,initial.step,initial.step*(initial.grid and 4 or 10)+96,initial.capacity,collapsedCategories)
        pages=#sections; page=math.min(page,pages); section=sections[page]
        layout.bottom=layout.top+math.max(initial.step,section.height)+8
        layout.height=layout.bottom+74
    end
    if compactBags then
        layout.top=layout.top-32; layout.bottom=layout.bottom-32; layout.height=layout.height-32
    end
    local filterSummary=ns.FilterSummary(search:GetText(),o.category,favoritesOnly)
    if filterSummary then
        filterLabel:SetText(filterSummary); filterLabel:SetTextColor(unpack(t.accent))
        filterLabel:ClearAllPoints(); filterLabel:SetPoint("TOPLEFT",16,-layout.top-3)
        filterLabel:SetSize(layout.width-146,22); filterLabel:Show()
        clearFilters:ClearAllPoints(); clearFilters:SetPoint("TOPRIGHT",-16,-layout.top); clearFilters:Show()
        layout.top=layout.top+32; layout.bottom=layout.bottom+32; layout.height=layout.height+32
    else filterLabel:Hide(); clearFilters:Hide() end
    for _,header in ipairs(categoryHeaders) do header:Hide() end
    for i,group in ipairs(section and section.headers or {}) do
        local header=categoryHeaders[i]
        if not header then
            header=ns.CreateCategoryHeader(window,function(key)
                collapsedCategories[key]=not collapsedCategories[key]; page=1; ns.RefreshUI()
            end); categoryHeaders[i]=header
        end
        header:ClearAllPoints(); header:SetPoint("TOPLEFT",16,-layout.top-group.y)
        header.categoryKey=group.key; header:SetSize(layout.width-32,22)
        header.caption:SetSize(layout.width-32,22); header.caption:SetText(group.text); header.caption:SetTextColor(unpack(t.accent)); header:Show()
    end
    window:SetSize(layout.width,layout.height)
    ns.ApplyPanelTheme(window,t,o.opacity)
    heading:SetText(ns.CharacterLabel(character and character.identity or {})..(historical and " (saved)" or ""))
    heading:SetTextColor(unpack(t.text)); heading:SetWidth(layout.width-180)
    if o.showDetails then status:SetText(notice.."\n"..notes)
    else
        -- Keep freshness visible while hiding diagnostic terminology by default.
        local compact={}
        for line in notes:gmatch("[^\n]+") do
            local basic=line:match("^(.-) / ") or line
            compact[#compact+1]=basic
        end
        status:SetText(notice~="Ready" and notice or table.concat(compact,"\n"))
    end
    status:SetTextColor(0.65,0.73,0.8); status:SetSize(layout.width-32,o.showDetails and 60 or 28)
    if compactBags then status:Hide() else status:Show() end
    search:SetWidth(layout.width-118)
    for _,b in ipairs(controls) do
        ns.ApplyControlTheme(b,t)
    end
    for name,b in pairs(tabs) do
        if name==scope then b:SetBackdropBorderColor(unpack(t.accent)); b.caption:SetTextColor(unpack(t.accent)) end
    end
    ns.RefreshLockButton(lockButton,"bags")
    refreshButton:SetText(historical and "View age" or "Refresh")
    favoriteButton:SetText(favoritesOnly and "Favorites *" or "Favorites")
    if sellJunkButton then
        if ns.vendor and ns.vendor.open and not historical then sellJunkButton:Show() else sellJunkButton:Hide() end
        ns.SetTooltip(sellJunkButton,ns.vendor and ns.vendor.status or "Sell gray items; favorites are kept")
    end
    if guildButton then
        if ns.guildVault and ns.guildVault.open then guildButton:Show() else guildButton:Hide() end
    end
    for i,row in ipairs(rows) do
        local placement=section and section.entries[i]
        local entry=section and (placement and placement.entry) or (not section and i<=layout.capacity and items[(page-1)*layout.capacity+i] or nil)
        row.entry=entry
        if entry then
            local item=entry.item
            local column=(i-1)%layout.columns; local line=math.floor((i-1)/layout.columns)
            row:ClearAllPoints(); row:SetPoint("TOPLEFT",16+(placement and placement.x or column*layout.step),-layout.top-(placement and placement.y or line*layout.step))
            local size=layout.grid and o.iconSize or layout.step-4
            row:SetSize(layout.grid and size or layout.width-32,size)
            row:SetBackdropColor(0.015,0.02,0.03,0.85)
            local border=qualityColors[item.quality] or {0.25,0.30,0.36}
            row:SetBackdropBorderColor(unpack(border))
            row.icon:ClearAllPoints(); row.icon:SetPoint("TOPLEFT",3,-3); row.icon:SetSize(size-6,size-6)
            row.icon:SetTexture(type(item.icon)=="number" and item.icon or "Interface\\Icons\\INV_Misc_QuestionMark")
            row.icon:SetDesaturated(o.dimPoor and item.quality==0)
            row.icon:SetAlpha(o.dimPoor and item.quality==0 and 0.5 or 1)
            row.count:SetText(item.count and tostring(item.count) or "?")
            row.count:SetFont("Fonts\\FRIZQT__.TTF",o.fontSize,"OUTLINE")
            row.count:ClearAllPoints(); row.count:SetPoint("BOTTOMRIGHT",-3,2)
            row.count:SetTextColor(1,1,1)
            row.text:SetFont("Fonts\\FRIZQT__.TTF",o.fontSize)
            row.text:SetText(entry.name); row.text:SetTextColor(unpack(t.text))
            row.text:ClearAllPoints(); row.text:SetPoint("LEFT",size+8,0); row.text:SetSize(layout.width-size-100,size)
            row.badge:SetText(entry.scope=="bank" and "K" or "B")
            row.badge:SetTextColor(unpack(t.accent))
            row.star:SetText(entry.favorite and "*" or "")
            if layout.grid then row.text:Hide(); row.badge:Show() else row.text:Show(); row.badge:Hide() end
            row:Show()
        else row:Hide() end
    end
    empty:SetText(#items==0 and (favoritesOnly and "No favorites here. Alt+left-click an item to mark it."
        or filterSummary and "No matching items - clear filters to show more" or "No observed items in this view") or "")
    empty:ClearAllPoints(); empty:SetPoint("TOPLEFT",18,-layout.top-8); empty:SetTextColor(unpack(t.text))
    previous:ClearAllPoints(); previous:SetPoint("TOPLEFT",16,-layout.bottom)
    nextPage:ClearAllPoints(); nextPage:SetPoint("TOPLEFT",100,-layout.bottom)
    characterButton:ClearAllPoints(); characterButton:SetPoint("TOPLEFT",184,-layout.bottom)
    currentButton:ClearAllPoints(); currentButton:SetPoint("TOPLEFT",280,-layout.bottom)
    favoriteButton:ClearAllPoints(); favoriteButton:SetPoint("TOPLEFT",364,-layout.bottom)
    footer:ClearAllPoints(); footer:SetPoint("TOPLEFT",16,-layout.bottom-32)
    footer:SetSize(layout.width-32,36); footer:SetTextColor(0.65,0.73,0.8)
    footer:SetText(#items..(o.order=="Category" and " matching  |  Page " or " shown  |  Page ")..page.." / "..pages.."  |  "..(freeText or o.order.." / "..o.category).."\nAlt+left: favorite  |  "..
        (historical and "Saved view: read-only" or scope=="bank" and not ns.inventory.bankOpen and "Cached bank: read-only" or "Right-click to use / equip / bank"))
    if characterPanel and characterPanel:IsShown() then
        local choices=ns.SavedCharacters()
        characterPage=math.max(1,math.min(characterPage,math.max(1,math.ceil(#choices/6))))
        characterHeading:SetText("Characters  |  "..characterPage.." / "..math.max(1,math.ceil(#choices/6)))
        for i,b in ipairs(characterButtons) do
            local entry=choices[(characterPage-1)*6+i]
            b.guid=entry and entry.guid
            b.characterEntry=entry
            if entry then
                b:SetText(shortLabel(entry.label,32)..(entry.guid==ns.owner and " (current)" or "").."\n"..shortLabel(entry.realm,42))
                b:Show()
            else b:Hide() end
        end
        ns.ApplyPanelTheme(characterPanel,t)
    end
    updateSettings(o,t); ns.ApplyWindowScale()
    if ns.RefreshBankUI then ns.RefreshBankUI() end
end
local function create()
    window=CreateFrame("Frame",nil,UIParent,"BackdropTemplate")
    -- Settings may be the first caller; only ShowInventory should open Bags.
    window:Hide()
    window:SetSize(480,310); window:SetPoint("CENTER"); window:SetClampedToScreen(true)
    window:SetFrameStrata("DIALOG"); window:EnableMouse(true); window:SetMovable(true); window:SetBackdrop(backdrop)
    local saved=ns.db and ns.db.settings.position
    if type(saved)=="table" and type(saved.x)=="number" and type(saved.y)=="number"
        and math.abs(saved.x)<10000 and math.abs(saved.y)<10000 then
        window:ClearAllPoints(); window:SetPoint("CENTER",UIParent,"CENTER",saved.x,saved.y)
    end
    ns.EnableEscapeClose(window,ns.CloseInventoryWindows)
    window:RegisterForDrag("LeftButton")
    window:SetScript("OnReceiveDrag",function() ns.DropInFreeSlot("bags") end)
    window:SetScript("OnMouseUp",function(_,mouse) if mouse=="LeftButton" then ns.DropInFreeSlot("bags") end end)
    window:SetScript("OnDragStart",function() if not ns.ViewOptions().lockWindow then window:StartMoving() end end)
    window:SetScript("OnDragStop",function()
        window:StopMovingOrSizing()
        -- Anchor against UIParent's center in the frame's own scaled coordinates.
        local x,y=window:GetCenter(); local px,py=UIParent:GetCenter()
        local scale=window:GetScale()
        if ns.db and type(x)=="number" and type(y)=="number" and type(px)=="number" and type(py)=="number" and type(scale)=="number" and scale>0 then
            ns.db.settings.position={x=x-px/scale,y=y-py/scale}
        end
    end)
    heading=label(window,16); heading:SetPoint("TOPLEFT",16,-16); heading:SetSize(340,22)
    local subtitle=label(window,10); subtitle:SetPoint("TOPLEFT",16,-38); subtitle:SetText("FOREVER STORAGE")
    subtitle:SetTextColor(0.55,0.65,0.72)
    local exitButton=button(window,"X",0,0,26,function() close("close button") end)
    exitButton:ClearAllPoints(); exitButton:SetPoint("TOPRIGHT",-12,-12)
    local cog=button(window,"",0,0,26,function()
        characterPanel:Hide()
        ns.ToggleSettings("bags")
    end)
    cog:ClearAllPoints(); cog:SetPoint("TOPRIGHT",-44,-12)
    cog:SetNormalTexture("Interface\\Buttons\\UI-OptionsButton")
    ns.SetTooltip(cog,"Settings")
    local sortButton=button(window,"Sort",0,0,46,function() ns.SortLiveInventory("bags") end)
    sortButton:ClearAllPoints(); sortButton:SetPoint("TOPRIGHT",-112,-12)
    lockButton=ns.CreateLockButton(window,"bags"); lockButton:SetPoint("TOPRIGHT",-78,-12)
    ns.SetTooltip(sortButton,"Sort your bags using WoW's sort rules. Moves items; unavailable in combat or saved-character views.")
    for i,value in ipairs({"bags","bank","all"}) do
        local selected=value
        tabs[value]=button(window,value:sub(1,1):upper()..value:sub(2),16+(i-1)*64,-58,58,function()
            scope=selected; page=1; ns.RefreshUI()
        end)
    end
    refreshButton=button(window,"Refresh",212,-58,76,function()
        if not viewedGUID then ns.inventory.Request("bags"); ns.inventory.Request("bank") end
        ns.RefreshUI()
    end)
    sellJunkButton=button(window,"Sell junk",296,-58,90,function() if ns.RequestJunkSale then ns.RequestJunkSale() end end)
    guildButton=button(window,"Guild",394,-58,70,function() if ns.ShowGuildVault then ns.ShowGuildVault() end end)
    local searchLabel=label(window,12); searchLabel:SetPoint("TOPLEFT",16,-98); searchLabel:SetText("Search")
    searchLabel:SetTextColor(0.65,0.73,0.8)
    search=CreateFrame("EditBox",nil,window,"InputBoxTemplate")
    search:SetSize(362,24); search:SetPoint("TOPLEFT",96,-91); search:SetAutoFocus(false); search:SetMaxLetters(80)
    search:SetScript("OnTextChanged",function() page=1; ns.RefreshUI() end)
    search:SetScript("OnEscapePressed",function() search:ClearFocus(); ns.CloseInventoryWindows() end)
    search:SetScript("OnEnterPressed",function() search:ClearFocus() end)
    filterLabel=label(window,11)
    clearFilters=button(window,"Clear filters",0,0,112,function()
        favoritesOnly=false; page=1
        ns.SetViewOption("category","All","bags")
        search:SetText(""); search:ClearFocus(); ns.RefreshUI()
    end)
    ns.SetTooltip(clearFilters,"Clear this window's search and Favorites filter. Reset this window's category filter. Saved favorites and display order stay unchanged.")
    status=label(window,11); status:SetPoint("TOPLEFT",16,-122); status:SetSize(448,28)
    empty=label(window,13)
    for i=1,40 do
        local row=CreateFrame("Button",nil,window,"BackdropTemplate,InsecureActionButtonTemplate"); row:SetBackdrop(backdrop)
        row.icon=row:CreateTexture(nil,"ARTWORK"); row.icon:SetTexCoord(0.06,0.94,0.06,0.94)
        row.text=label(row,14); row.count=label(row,14); row.count:SetJustifyH("RIGHT")
        row.badge=label(row,9); row.badge:SetPoint("TOPLEFT",3,-3)
        row.star=label(row,15); row.star:SetPoint("TOPRIGHT",-3,-1); row.star:SetTextColor(1,0.8,0.25)
        row:RegisterForClicks("LeftButtonUp","RightButtonUp")
        ns.EnableItemDrag(row)
        ns.ConfigureItemButton(row)
        row:SetScript("OnEnter",function()
            if not row.entry or not GameTooltip then return end
            local e=row.entry
            GameTooltip:SetOwner(row,"ANCHOR_RIGHT"); GameTooltip:SetText(e.name)
            if e.item.itemID and type(GameTooltip.SetItemByID)=="function" then pcall(GameTooltip.SetItemByID,GameTooltip,e.item.itemID) end
            GameTooltip:AddLine(e.scope.." / container "..e.item.bag.." / slot "..e.item.slot,0.7,0.8,0.9)
            GameTooltip:AddLine("Category: "..e.category,0.7,0.8,0.9)
            GameTooltip:AddLine("Observed count: "..tostring(e.item.count or "Unknown"),1,1,1)
            local when=type(e.at)=="number" and ns.Read(date,"%Y-%m-%d %H:%M:%S",e.at) or nil
            GameTooltip:AddLine("Recorded: "..tostring(when or "Unknown"),0.7,0.8,0.9)
            GameTooltip:AddLine("Last seen: "..ns.SnapshotAge(e.at),0.7,0.8,0.9)
            GameTooltip:AddLine("Alt+left-click: toggle favorite",1,0.8,0.25)
            GameTooltip:AddLine(ns.ActionHint(e),0.7,0.8,0.9)
            GameTooltip:AddLine("Snapshot only; counts may have changed.",1,1,1); GameTooltip:Show()
        end)
        row:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
        rows[i]=row
    end
    previous=button(window,"Previous",16,-222,76,function() page=math.max(1,page-1); ns.RefreshUI() end)
    nextPage=button(window,"Next",100,-222,76,function() page=page+1; ns.RefreshUI() end)
    characterButton=button(window,"Characters",184,-222,88,function()
        if characterPanel:IsShown() then characterPanel:Hide()
        else settingsPanel:Hide(); characterPanel:Show(); ns.RefreshUI() end
    end)
    currentButton=button(window,"Current",280,-222,76,function() ns.SelectCharacter(nil) end)
    favoriteButton=button(window,"Favorites",364,-222,100,function() favoritesOnly=not favoritesOnly; page=1; ns.RefreshUI() end)
    footer=label(window,11)
    characterPanel=CreateFrame("Frame",nil,UIParent,"BackdropTemplate")
    ns.EnableEscapeClose(characterPanel,ns.CloseInventoryWindows)
    characterPanel:SetSize(380,358); characterPanel:SetPoint("CENTER"); characterPanel:SetClampedToScreen(true)
    characterPanel:SetFrameStrata("FULLSCREEN_DIALOG"); characterPanel:EnableMouse(true); characterPanel:SetBackdrop(backdrop)
    characterPanel:SetScale(math.min(1,UIParent:GetHeight()/382,UIParent:GetWidth()/404))
    characterHeading=label(characterPanel,16); characterHeading:SetPoint("TOPLEFT",16,-16)
    button(characterPanel,"X",340,-12,26,function() characterPanel:Hide() end)
    for i=1,6 do
        local b
        b=button(characterPanel,"",16,-48-(i-1)*43,348,function() if b.guid then ns.SelectCharacter(b.guid) end end)
        b:SetHeight(38); b.caption:SetHeight(36); characterButtons[i]=b
        b:SetScript("OnEnter",function()
            local e=b.characterEntry
            if not e or not GameTooltip then return end
            GameTooltip:SetOwner(b,"ANCHOR_RIGHT"); GameTooltip:SetText(e.label)
            GameTooltip:AddLine(e.realm,0.7,0.8,0.9); GameTooltip:AddLine(e.guid,0.7,0.8,0.9); GameTooltip:Show()
        end)
        b:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
    end
    button(characterPanel,"Previous",16,-316,100,function() characterPage=math.max(1,characterPage-1); ns.RefreshUI() end)
    button(characterPanel,"Next",124,-316,100,function() characterPage=characterPage+1; ns.RefreshUI() end)
    characterPanel:Hide()
    -- Independent, clamped settings panel stays reachable even beside a small grid.
    settingsPanel=CreateFrame("Frame",nil,UIParent,"BackdropTemplate")
    settingsPanel:SetSize(310,390); settingsPanel:SetPoint("CENTER"); settingsPanel:SetClampedToScreen(true)
    settingsPanel:SetFrameStrata("FULLSCREEN_DIALOG"); settingsPanel:EnableMouse(true); settingsPanel:SetBackdrop(backdrop)
    settingsPanel:SetScale(math.min(1,UIParent:GetHeight()/410,UIParent:GetWidth()/330))
    ns.EnableEscapeClose(settingsPanel,ns.CloseInventoryWindows)
    settingsPanel:SetMovable(true); settingsPanel:RegisterForDrag("LeftButton")
    local settingsPosition=ns.db and ns.db.settings.settingsPosition
    if type(settingsPosition)=="table" and type(settingsPosition.x)=="number" and type(settingsPosition.y)=="number"
        and math.abs(settingsPosition.x)<10000 and math.abs(settingsPosition.y)<10000 then
        settingsPanel:ClearAllPoints(); settingsPanel:SetPoint("CENTER",UIParent,"CENTER",settingsPosition.x,settingsPosition.y)
    end
    settingsPanel:SetScript("OnDragStart",function() settingsPanel:StartMoving() end)
    settingsPanel:SetScript("OnDragStop",function()
        settingsPanel:StopMovingOrSizing()
        local x,y=settingsPanel:GetCenter(); local px,py=UIParent:GetCenter()
        local scale=settingsPanel:GetScale()
        if ns.db and type(x)=="number" and type(y)=="number" and type(px)=="number" and type(py)=="number" and type(scale)=="number" and scale>0 then
            ns.db.settings.settingsPosition={x=x-px/scale,y=y-py/scale}
        end
    end)
    settingsTitle=label(settingsPanel,16); settingsTitle:SetPoint("TOPLEFT",16,-16); settingsTitle:SetText("Bags settings")
    button(settingsPanel,"X",268,-12,26,function() settingsPanel:Hide() end)
    mainSettingsButton=button(settingsPanel,"Main settings (both windows)",16,-48,278,function()
        if optionPanel then optionPanel:Hide() end
        settingsPage=settingsPage=="Main" and "Appearance" or "Main"; ns.RefreshUI()
    end)
    for i,name in ipairs({"Appearance","Organize"}) do
        local selected=name
        settingsTabs[name]=button(settingsPanel,name,16+(i-1)*142,-82,136,function() if optionPanel then optionPanel:Hide() end; settingsPage=selected; ns.RefreshUI() end)
    end
    for i=1,7 do
        local b
        b=button(settingsPanel,"",16,-86-(i-1)*34,278,function()
            if not b.key then return end
            page=1; openOptions(b.key,b)
        end)
        settingsRows[i]=b
        local slider=CreateFrame("Slider",nil,settingsPanel,"BackdropTemplate")
        slider:SetSize(260,20); slider:SetOrientation("HORIZONTAL"); slider:SetBackdrop(backdrop)
        slider:SetBackdropColor(.2,.25,.3,1); slider:SetThumbTexture("Interface\\Buttons\\UI-SliderBar-Button-Horizontal")
        slider:SetValueStep(1); slider:SetObeyStepOnDrag(true)
        slider.caption=label(settingsPanel,12); slider.caption:SetSize(278,22)
        slider:SetScript("OnValueChanged",function(_,value)
            if slider.syncing or not slider.key then return end
            if optionPanel then optionPanel:Hide() end
            local rounded=math.floor(value+.5); local key=slider.key
            local selected=(key=="opacity" or key=="windowScale") and rounded/100 or ns.ViewChoices[key][rounded]
            if selected~=nil then
                slider.userChanging=true
                ns.SetViewOption(key,selected,settingsTarget)
                slider.userChanging=false
            end
        end)
        settingsSliders[i]=slider
    end
    settingsHelp=label(settingsPanel,11); settingsHelp:SetPoint("BOTTOMLEFT",16,16); settingsHelp:SetSize(278,40)
    settingsHelp:SetText("Drag sliders or choose from dropdowns.\nAlt+left-click an item to toggle its favorite.")
    settingsPanel:SetScript("OnHide",function() if optionPanel then optionPanel:Hide() end end)
    settingsPanel:Hide()
    window:SetScript("OnShow",ns.RefreshUI)
    window:SetScript("OnHide",function()
        ns.CloseItemSplit(window)
        settingsPanel:Hide()
        characterPanel:Hide()
        if ns.db then ns.db.settings.lastWindowHide={reason=hideReason or "external or parent hidden",at=ns.Stamp(),lastInteraction=lastInteraction} end
        hideReason=nil; if GameTooltip then GameTooltip:Hide() end
    end)
end
ns.On("PLAYER_ENTERING_WORLD",function() viewedGUID=nil; page=1; ns.RefreshUI() end)
for _,event in ipairs({"GOSSIP_SHOW","QUEST_GREETING","QUEST_DETAIL","MERCHANT_SHOW","BANKFRAME_OPENED"}) do
    local name=event; ns.On(name,function() lastInteraction={event=name,at=ns.Stamp()} end)
end
SLASH_WFSTORAGE1="/wfstorage"
SLASH_WFSTORAGE2="/wfbags"
SLASH_WFSTORAGE3="/wf"
function ns.ToggleSettings(target)
    if not window then create() end
    target=target=="guild" and "guild" or target=="bank" and "bank" or "bags"
    if settingsPanel:IsShown() and settingsTarget==target then settingsPanel:Hide(); return end
    if optionPanel then optionPanel:Hide() end
    characterPanel:Hide(); settingsTarget=target; settingsPage="Appearance"
    settingsPanel:Show(); updateSettings()
end
function ns.ShowInventory(selectedScope)
    if not window then create() end
    if ns.inventory.bankOpen and not (ns.db and ns.db.settings.position) then
        window:ClearAllPoints(); window:SetPoint("CENTER",UIParent,"CENTER",250,0)
    end
    viewedGUID=nil; scope=selectedScope or "bags"; page=1
    ns.inventory.EnsureFresh("bags")
    if ns.inventory.bankOpen then ns.inventory.EnsureFresh("bank") end
    window:Show(); ns.RefreshUI()
end
SlashCmdList.WFSTORAGE=function(message)
    if type(message)=="string" and message:lower():match("^%s*guild%s*$") and ns.ShowGuildVault then
        ns.ShowGuildVault();return
    end
    if window and window:IsShown() then close("slash toggle")
    else ns.ShowInventory("bags") end
end

-- Compatibility for existing integrations; slash ownership belongs to Storage.
SlashCmdList.WFCORE=SlashCmdList.WFSTORAGE
