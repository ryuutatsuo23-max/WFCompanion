-- SPDX-License-Identifier: GPL-3.0-only
local _, ns = ...
local window=CreateFrame("Frame",nil,UIParent,"BackdropTemplate")
-- Fail closed if any later UI initialization raises: never leave a white overlay.
window:Hide()
ns.window=window
window:SetSize(840,500); window:SetPoint("CENTER",UIParent,"CENTER",0,0)
window:SetClampedToScreen(true); window:SetMovable(true); window:EnableMouse(true)
window:RegisterForDrag("LeftButton")
window:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1})
window:SetBackdropColor(.12,.09,.055,.97)
window:SetBackdropBorderColor(.55,.43,.24,1)
local labels,controls={},{}
local function text(x,y,w,h)
    local t=window:CreateFontString(nil,"OVERLAY","GameFontNormal")
    t:SetFont("Fonts\\FRIZQT__.TTF",14,"")
    t:SetPoint("TOPLEFT",window,"TOPLEFT",x,-y); t:SetSize(w,h); t:SetJustifyH("LEFT")
    t:SetTextColor(.95,.87,.68,1); labels[#labels+1]=t; return t
end
local function settings()
    return ns.store and ns.store.settings or {}
end
window:SetScript("OnDragStart",function(self) if not settings().locked then self:StartMoving() end end)
window:SetScript("OnDragStop",function(self) self:StopMovingOrSizing() end)
local function button(caption,x,y,w,callback,help,parent)
    parent=parent or window
    local b=CreateFrame("Button",nil,parent,"BackdropTemplate")
    b:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-y); b:SetSize(w,28)
    b:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1}); b:SetBackdropColor(.21,.18,.13,1)
    local t=b:CreateFontString(nil,"OVERLAY","GameFontNormal")
    t:SetFont("Fonts\\FRIZQT__.TTF",14,""); t:SetPoint("CENTER",b,"CENTER",0,0)
    t:SetSize(w-6,26); t:SetJustifyH("CENTER"); t:SetText(caption); labels[#labels+1]=t
    b:SetScript("OnClick",callback)
    b:SetScript("OnEnter",function() GameTooltip:SetOwner(b,"ANCHOR_CURSOR"); GameTooltip:SetText(help or caption); GameTooltip:Show() end)
    b:SetScript("OnLeave",function() GameTooltip:Hide() end)
    controls[#controls+1]=b
    return b,t
end
-- Synthetic identifiers are color seeds for the offline renderer, never client
-- texture IDs. No icon API, catalogue, save field or live lookup is introduced.
local function placeholder(parent,x,y,size)
    if not ns.syntheticPreview then return nil end
    local icon=parent:CreateTexture(nil,"ARTWORK")
    icon:SetPoint("TOPLEFT",parent,"TOPLEFT",x,-y); icon:SetSize(size,size); icon:Hide()
    return icon
end
local function showPlaceholder(icon,id)
    if not icon then return end
    if id then icon:SetTexture(id); icon:Show() else icon:Hide() end
end
local function materialName(item)
    if item.name.status=="known" then return item.name end
    if item.fromProbe then return ns.ResolveItemName(item.itemID) end
    return item.name
end
local function recipeTooltip(owner,r)
    if not r then return end
    GameTooltip:SetOwner(owner,"ANCHOR_CURSOR")
    GameTooltip:SetText(r.name)
    if settings().advanced then GameTooltip:AddLine("Recipe ID: "..r.recipeID) end
    if settings().advanced then GameTooltip:AddLine("Output item ID: "..ns.Display(r.outputItemID)) end
    GameTooltip:AddLine("Output per craft: "..ns.Display(r.outputMin).." - "..ns.Display(r.outputMax))
    if settings().advanced or r.reagentsStatus~="known" then GameTooltip:AddLine("Materials: "..r.reagentsStatus) end
    for _,slot in ipairs(r.slots) do
        for _,item in ipairs(slot.alternatives) do
            GameTooltip:AddLine(ns.Display(materialName(item))..(settings().advanced and " | Item ID: "..item.itemID or ""))
            GameTooltip:AddLine("Quantity per craft: "..ns.Display(slot.quantity)..(#slot.alternatives>1 and " (choose one)" or ""))
        end
    end
    GameTooltip:Show()
end
local openMenu,closeMenus
local settingsPanel
local title=text(16,10,680,26)
button("X",794,10,30,function() window:Hide() end,"Close journal; /wfprofessions opens it again.")
local lockButton=button("",718,10,30,function()
    settings().locked=not settings().locked; ns.Refresh()
end,"Lock / unlock window position")
local lockParts={}
for _,rect in ipairs({{7,13,16,10},{9,5,12,2},{9,5,2,9},{19,5,2,9}}) do
    local part=CreateFrame("Frame",nil,lockButton,"BackdropTemplate")
    part:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8"})
    part:SetPoint("TOPLEFT",lockButton,"TOPLEFT",rect[1],-rect[2]); part:SetSize(rect[3],rect[4])
    lockParts[#lockParts+1]=part
end
local cog=button("",756,10,30,function()
    ns.ToggleSettings()
end,"Professions settings")
cog:SetNormalTexture("Interface\\Buttons\\UI-OptionsButton")
-- Preview-only display metadata is injected by the offline loader. Identity and
-- saved records still use Core GUIDs; this does not add a live identity contract.
local function characterLabel(guid)
    local names=ns.syntheticPreview and ns.previewCharacterNames
    local name=names and names[guid]
    if type(name)~="string" or name=="" then name=guid or "Unknown" end
    return (guid==ns.core.owner and "[Current] " or "")..name
end
local _,ownerLabel=button("Character: Unknown v",16,44,808,function()
    local entries,seen={},{}
    local current=ns.core.owner
    if current then entries[#entries+1]={label=characterLabel(current),value=current}; seen[current]=true end
    local keys={}
    for guid in pairs(ns.ViewCharacterKeys()) do if not seen[guid] then keys[#keys+1]=guid end end
    table.sort(keys)
    for _,guid in ipairs(keys) do entries[#entries+1]={label=characterLabel(guid),value=guid} end
    openMenu("characters",16,74,entries,function(guid)
        ns.viewOwner=guid; ns.professionIndex=1; ns.recipeIndex=1; ns.recipeOffset=0; ns.detailOffset=0
    end)
end,"Choose current or recorded character; never collects.")
local status=text(16,77,808,36)
local _,profession=button("Profession: Unknown v",16,118,808,function()
    local owner=ns.viewOwner or ns.core.owner
    local c=ns.ViewCharacter(owner)
    local entries={}
    for i,p in ipairs(c and c.latest and c.latest.professions or {}) do
        entries[#entries+1]={label=p.name.."  "..ns.Display(p.skill).." / "..ns.Display(p.maxSkill),value=i}
    end
    openMenu("professions",16,148,entries,function(index)
        ns.professionIndex=index; ns.recipeIndex=1; ns.recipeOffset=0; ns.detailOffset=0
    end)
end,"Choose a recorded profession; missing observations remain Unknown.")
local searchLabel=text(16,154,70,28)
searchLabel:SetText("Search")
local search=CreateFrame("EditBox",nil,window,"BackdropTemplate")
search:SetPoint("TOPLEFT",window,"TOPLEFT",86,-154); search:SetSize(638,28)
search:SetFont("Fonts\\FRIZQT__.TTF",14,""); search:SetAutoFocus(false); search:SetMaxLetters(120)
search:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1})
search:SetText("")
local query=""
search:SetScript("OnTextChanged",function(self)
    query=self:GetText():lower():match("^%s*(.-)%s*$")
    ns.recipeIndex=1; ns.recipeOffset=0; ns.detailOffset=0; ns.Refresh()
end)
search:SetScript("OnEnterPressed",function(self) self:ClearFocus() end)
search:SetScript("OnEscapePressed",function(self) self:ClearFocus(); window:Hide() end)
button("Clear",734,154,90,function() search:SetText(""); search:ClearFocus() end,"Clear recipe-name filter; keeps character and profession.")
local listSummary=text(16,194,300,42)
local recipeIcon=placeholder(window,340,200,32)
local recipe=text(ns.syntheticPreview and 380 or 340,194,ns.syntheticPreview and 444 or 484,46)
local recipeHover=CreateFrame("Frame",nil,window)
recipeHover:SetPoint("TOPLEFT",window,"TOPLEFT",340,-194); recipeHover:SetSize(484,46); recipeHover:EnableMouse(true)
recipeHover:SetScript("OnEnter",function()
    if ns.shownRecipe then
        recipeTooltip(recipeHover,ns.shownRecipe)
    end
end)
recipeHover:SetScript("OnLeave",function() GameTooltip:Hide() end)
-- Bounded recycled rows with independent offsets; scrolling never selects a recipe.
local function scrollArea(x,width,field,visible)
    local area=CreateFrame("Frame",nil,window)
    area:SetPoint("TOPLEFT",window,"TOPLEFT",x,-244); area:SetSize(width,204); area:EnableMouse(true); area:EnableMouseWheel(true)
    local bar=CreateFrame("Slider",nil,window,"BackdropTemplate")
    bar:SetPoint("TOPLEFT",window,"TOPLEFT",x+width-12,-244); bar:SetSize(12,204)
    bar:SetOrientation("VERTICAL"); bar:SetMinMaxValues(0,0); bar:SetValueStep(1); bar:SetObeyStepOnDrag(true)
    bar:SetThumbTexture("Interface\\Buttons\\UI-SliderBar-Button-Vertical")
    bar:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8"})
    local function wheel(_,delta) ns[field]=math.max(0,(ns[field] or 0)-delta); ns.Refresh() end
    area:SetScript("OnMouseWheel",wheel)
    bar:SetScript("OnValueChanged",function(self,value)
        if not self.syncing then ns[field]=math.floor(value+.5); ns.Refresh() end
    end)
    return {area=area,bar=bar,field=field,visible=visible,wheel=wheel}
end
local recipeScroll=scrollArea(16,316,"recipeOffset",6)
local detailScroll=scrollArea(340,484,"detailOffset",5)
local function updateScroll(control,count,theme)
    local maximum=math.max(0,count-control.visible)
    ns[control.field]=math.max(0,math.min(ns[control.field] or 0,maximum))
    local bar=control.bar; bar.syncing=true; bar:SetMinMaxValues(0,maximum); bar:SetValue(ns[control.field]); bar.syncing=false
    bar:SetBackdropColor(theme.bg[1]+.06,theme.bg[2]+.06,theme.bg[3]+.06,1); bar.sliderAccent=theme.accent
    if maximum>0 then bar:Show() else bar:Hide() end
end
-- Six bounded rows keep selection reachable without building a frame per recipe.
local rows={}
for i=1,6 do
    local row={}
    row.button,row.label=button("",16,244+(i-1)*34,300,function()
        if row.index then ns.recipeIndex=row.index; ns.detailOffset=0; ns.Refresh() end
    end)
    -- The wheel-catching frame overlaps every row. Explicitly place selectable
    -- buttons above it; sibling creation order is not a client stacking contract.
    row.button:SetFrameLevel(recipeScroll.area:GetFrameLevel()+1)
    row.button:EnableMouse(true)
    row.button:RegisterForClicks("LeftButtonUp")
    row.label:SetJustifyH("LEFT")
    row.icon=placeholder(row.button,5,3,22)
    if row.icon then
        row.label:ClearAllPoints(); row.label:SetPoint("TOPLEFT",row.button,"TOPLEFT",34,0)
        row.label:SetSize(260,26)
    end
    row.button:SetScript("OnEnter",function()
        if row.recipe then
            recipeTooltip(row.button,row.recipe)
        end
    end)
    row.button:EnableMouseWheel(true); row.button:SetScript("OnMouseWheel",recipeScroll.wheel)
    rows[i]=row
end
local detailLabels,detailIcons,detailHovers={},{},{}
for i=1,5 do
    detailLabels[i]=text(340,248+(i-1)*34,484,36)
    detailIcons[i]=placeholder(window,340,254+(i-1)*34,24)
    local hover=CreateFrame("Frame",nil,window)
    hover:SetPoint("TOPLEFT",window,"TOPLEFT",340,-(248+(i-1)*34)); hover:SetSize(468,34); hover:EnableMouse(true)
    -- Keep material hover targets above the overlapping wheel catcher, but leave
    -- the scrollbar strip uncovered. A frame level tie can swallow OnEnter.
    hover:SetFrameLevel(detailScroll.area:GetFrameLevel()+1)
    hover:SetScript("OnEnter",function()
        local m=hover.material
        if not m then return end
        GameTooltip:SetOwner(hover,"ANCHOR_CURSOR"); GameTooltip:SetText(ns.Display(materialName(m.item)))
        if settings().advanced then GameTooltip:AddLine("Item ID: "..m.item.itemID) end
        GameTooltip:AddLine("Quantity per craft: "..ns.Display(m.slot.quantity))
        if settings().advanced or m.slot.required.status~="known" or not m.slot.required.value then GameTooltip:AddLine("Required: "..ns.Display(m.slot.required)) end
        if #m.slot.alternatives>1 then GameTooltip:AddLine("Choose one material from this slot; do not add alternatives") end
        GameTooltip:Show()
    end)
    hover:SetScript("OnLeave",function() GameTooltip:Hide() end)
    hover:EnableMouseWheel(true); hover:SetScript("OnMouseWheel",detailScroll.wheel)
    hover:Hide(); detailHovers[i]=hover
end
-- Match Storage's palette values without reading its namespace or preferences.
local themes={
    Slate={bg={.055,.075,.10},accent={.40,.75,.90},text={.91,.94,.97}},
    Warm={bg={.10,.075,.05},accent={.94,.73,.38},text={.97,.93,.85}},
    Midnight={bg={.035,.035,.055},accent={.70,.58,.94},text={.93,.91,.98}},
    Classic={bg={.11,.075,.04},accent={.82,.65,.34},text={1,.87,.55}},
}
local function themeName()
    local s=settings()
    if themes[s.theme] then return s.theme end
    return s.slate==true and "Slate" or "Classic"
end
-- Settings and dropdowns are separate, bounded overlays; no observation writes.
settingsPanel=CreateFrame("Frame",nil,UIParent,"BackdropTemplate")
ns.settingsPanel=settingsPanel
settingsPanel:SetPoint("CENTER",UIParent,"CENTER",0,0); settingsPanel:SetSize(324,460)
settingsPanel:SetClampedToScreen(true); settingsPanel:SetMovable(true); settingsPanel:RegisterForDrag("LeftButton")
settingsPanel:SetScript("OnDragStart",function(self) self:StartMoving() end)
settingsPanel:SetScript("OnDragStop",function(self) self:StopMovingOrSizing() end)
settingsPanel:EnableMouse(true); settingsPanel:SetFrameStrata("FULLSCREEN_DIALOG"); settingsPanel:Hide()
local settingsTitle=settingsPanel:CreateFontString(nil,"OVERLAY","GameFontNormal")
settingsTitle:SetPoint("TOPLEFT",settingsPanel,"TOPLEFT",16,-12); settingsTitle:SetSize(256,26)
settingsTitle:SetText("Professions settings"); settingsTitle:SetJustifyH("LEFT"); labels[#labels+1]=settingsTitle
button("X",282,10,30,function() closeMenus() end,"Close settings",settingsPanel)
local _,themeLabel=button("Theme",12,90,300,function()
    local entries={}
    for _,name in ipairs({"Slate","Warm","Midnight","Classic"}) do entries[#entries+1]={label=name,value=name} end
    openMenu("themes",500,166,entries,function(name) settings().theme=name end,true)
end,"Choose the Professions theme",settingsPanel)
local _,modeLabel=button("Mode",12,50,300,function()
    openMenu("mode",500,126,{{label="Easy",value=false},{label="Advanced",value=true}},function(value)
        settings().advanced=value; ns.detailOffset=0
    end,true)
end,"Easy hides technical IDs; Advanced shows diagnostic details",settingsPanel)
local sliderControls={}
local function sliderOption(key,label,y,low,high,values,format)
    local _,caption=button(label,12,y,300,function()
        local entries={}
        for _,value in ipairs(values) do entries[#entries+1]={label=format(value),value=value} end
        openMenu(key,500,44+y+30,entries,function(value) settings()[key]=value end,true)
    end,"Drag the slider or select a value from this dropdown",settingsPanel)
    local slider=CreateFrame("Slider",nil,settingsPanel,"BackdropTemplate")
    slider:SetPoint("TOPLEFT",settingsPanel,"TOPLEFT",20,-(y+32)); slider:SetSize(284,20)
    slider:SetOrientation("HORIZONTAL"); slider:SetMinMaxValues(low,high)
    slider:SetValueStep(1); slider:SetObeyStepOnDrag(true)
    slider:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1})
    slider:SetThumbTexture("Interface\\Buttons\\UI-SliderBar-Button-Horizontal")
    slider:SetScript("OnValueChanged",function(self,value)
        if self.syncing then return end
        local rounded=math.max(low,math.min(high,math.floor(value+.5)))
        settings()[key]=key=="fontSize" and values[rounded] or rounded/100
        ns.Refresh()
    end)
    sliderControls[#sliderControls+1]={slider=slider,caption=caption,key=key,label=label,format=format}
end
sliderOption("opacity","Background",130,50,100,{.5,.65,.8,.95,1},function(v) return math.floor(v*100+.5).."%" end)
sliderOption("fontSize","Text size",198,1,3,{12,14,16},function(v) return tostring(v) end)
sliderOption("scale","Window scale",266,70,130,{.7,.85,1,1.15,1.3},function(v) return math.floor(v*100+.5).."%" end)
button("Refresh age",12,338,300,function() ns.Refresh() end,"Refresh cache age without collection",settingsPanel)
local _,displayLabel=button("Display",12,378,300,function()
    local entries={}
    for _,value in ipairs({"Alongside","Custom","Native UI"}) do entries[#entries+1]={label=value,value=value} end
    openMenu("presentation",500,168,entries,function(value) ns.SetPresentationMode(value) end,true)
end,"Custom shows cached data alone. Open profession temporarily shows the native page for manual Refresh. Native UI keeps the addon loaded.",settingsPanel)
local _,minimapLabel=button("Minimap",12,418,300,function()
    if ns.SetMinimapVisible then ns.SetMinimapVisible(settings().showMinimapButton==false) end
end,"Show the launcher; /wfprofessions minimap show restores it.",settingsPanel)
local menu=CreateFrame("Frame",nil,UIParent,"BackdropTemplate")
menu:SetClampedToScreen(true)
menu:SetSize(500,324); menu:EnableMouse(true); menu:SetFrameStrata("TOOLTIP"); menu:Hide()
local menuKind,menuEntries,menuSelect,menuPage=nil,{},nil,1
local menuRows={}
closeMenus=function() menuKind=nil; menu:Hide(); settingsPanel:Hide(); GameTooltip:Hide() end
local lastCurrentOwner=ns.core.owner
local function renderMenu()
    for i,row in ipairs(menuRows) do
        local entry=menuEntries[(menuPage-1)*8+i]
        row.entry=entry
        row.label:SetText(entry and (#entry.label>48 and entry.label:sub(1,45).."..." or entry.label) or (i==1 and #menuEntries==0 and "Unknown - no observations" or ""))
        if entry or (i==1 and #menuEntries==0) then row.button:Show() else row.button:Hide() end
    end
end
for i=1,8 do
    local row={}
    row.button,row.label=button("",8,8+(i-1)*34,484,function()
        if row.entry then menuSelect(row.entry.value); menuKind=nil; menu:Hide(); ns.Refresh() end
    end,"Select this observation; no collection",menu)
    -- The wheel-catching frame overlaps every row. Explicitly place selectable
    -- buttons above it; sibling creation order is not a client stacking contract.
    row.button:SetFrameLevel(recipeScroll.area:GetFrameLevel()+1)
    row.button:EnableMouse(true)
    row.button:RegisterForClicks("LeftButtonUp")
    row.label:SetJustifyH("LEFT")
    row.button:SetScript("OnEnter",function()
        GameTooltip:SetOwner(row.button,"ANCHOR_CURSOR")
        GameTooltip:SetText(row.entry and row.entry.label or "No profession observations recorded")
        GameTooltip:Show()
    end)
    menuRows[i]=row
end
button("Previous",8,286,155,function() menuPage=math.max(1,menuPage-1); renderMenu() end,"Previous choices",menu)
button("Close",173,286,154,function() menuKind=nil; menu:Hide() end,"Close choices",menu)
button("Next",337,286,155,function() menuPage=math.min(math.max(1,math.ceil(#menuEntries/8)),menuPage+1); renderMenu() end,"More choices",menu)
openMenu=function(kind,x,y,entries,select,keepSettings)
    if menuKind==kind and menu:IsShown() then menuKind=nil; menu:Hide(); return end
    if not keepSettings then settingsPanel:Hide() end
    menuKind=kind; menuEntries=entries; menuSelect=select; menuPage=1
    -- Theme list anchors within the journal even at larger scale.
    menu:ClearAllPoints()
    if keepSettings then menu:SetPoint("TOPLEFT",settingsPanel,"TOPLEFT",0,-80)
    else menu:SetPoint("TOPLEFT",window,"TOPLEFT",math.min(x,324),-math.min(y,168)) end
    renderMenu(); menu:Show(); ns.Refresh()
end
window:SetScript("OnHide",function()
    if not settingsPanel:IsShown() then menuKind=nil; menu:Hide() end
    search:ClearFocus(); GameTooltip:Hide()
end)
settingsPanel:SetScript("OnHide",function() menuKind=nil; menu:Hide(); GameTooltip:Hide() end)
settingsPanel:EnableKeyboard(true); settingsPanel:SetPropagateKeyboardInput(true)
settingsPanel:SetScript("OnKeyDown",function(_,key) if key=="ESCAPE" then closeMenus() end end)
function ns.OpenSettings() menuKind=nil; menu:Hide(); ns.Refresh(); settingsPanel:Show() end
function ns.ToggleSettings()
    if settingsPanel:IsShown() then closeMenus() else ns.OpenSettings() end
end
local footer=text(16,464,502,24)
local refreshResult
button("Open profession",532,462,160,function()
    local owner=ns.viewOwner or ns.core.owner
    local c=ns.ViewCharacter(owner)
    local professions=c and c.latest and c.latest.professions or {}
    local p=professions[ns.professionIndex or 1]
    local _,message=ns.OpenProfession(owner,p and p.skillLineID)
    refreshResult={owner=owner,professionID=p and p.skillLineID,message=message}
    ns.Refresh()
end,"Open the selected current-character profession in the game. Does not refresh recipes or craft.")
button("Refresh",700,462,124,function()
    local owner=ns.viewOwner or ns.core.owner
    local c=ns.ViewCharacter(owner)
    local professions=c and c.latest and c.latest.professions or {}
    local p=professions[ns.professionIndex or 1]
    if type(ns.RefreshLearned)~="function" then return end
    local accepted,message=ns.RefreshLearned(owner,p and p.skillLineID)
    refreshResult={owner=owner,professionID=p and p.skillLineID,message=message}
    if accepted then ns.recipeIndex=1; ns.recipeOffset=0; ns.detailOffset=0 end
    ns.Refresh()
end,"Manually capture learned recipes for the selected current-character profession. Open its game recipe window first. Never crafts.")
local function short(v,n) return #v>n and v:sub(1,n-3).."..." or v end
local function age(snapshot)
    if not snapshot then return "Unknown: no recorded observation" end
    local now=ns.core.Stamp()
    if not ns.core.Integer(now,1,2147483647) then return "Last recorded; age unavailable" end
    if now<snapshot.recordedAt then return "Last recorded; clock mismatch" end
    return "Cached | Last recorded "..math.floor((now-snapshot.recordedAt)/60).."m ago; observed list only"
end
function ns.RefreshUI()
    if lastCurrentOwner~=ns.core.owner then closeMenus(); ns.recipeOffset=0; ns.detailOffset=0; lastCurrentOwner=ns.core.owner end
    GameTooltip:Hide()
    local s=settings()
    local fontSize=(s.fontSize==12 or s.fontSize==14 or s.fontSize==16) and s.fontSize or (s.large and 16 or 14)
    local scale=type(s.scale)=="number" and s.scale>=.7 and s.scale<=1.3 and s.scale or 1
    local opacity=type(s.opacity)=="number" and s.opacity>=.5 and s.opacity<=1 and s.opacity or .95
    for _,t in ipairs(labels) do t:SetFont("Fonts\\FRIZQT__.TTF",fontSize,"") end
    -- Independent panels need their own scale; cap all surfaces to screen bounds.
    local fit=math.min(scale,(UIParent:GetWidth()-24)/840,(UIParent:GetHeight()-24)/500)
    window:SetScale(math.max(.1,fit)); settingsPanel:SetScale(math.max(.1,fit)); menu:SetScale(math.max(.1,fit))
    local name=themeName()
    local theme=themes[name]
    window:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",
        edgeFile=name=="Classic" and "Interface\\DialogFrame\\UI-DialogBox-Border" or "Interface\\Buttons\\WHITE8X8",
        edgeSize=name=="Classic" and 20 or 1})
    window:SetBackdropColor(theme.bg[1],theme.bg[2],theme.bg[3],opacity)
    window:SetBackdropBorderColor(unpack(theme.accent))
    for _,t in ipairs(labels) do t:SetTextColor(unpack(theme.text)) end
    for _,b in ipairs(controls) do
        b:SetBackdropBorderColor(unpack(name=="Classic" and {.43,.32,.16} or {.24,.28,.33}))
        if name=="Classic" then b:SetBackdropColor(.22,.065,.035,1)
        else b:SetBackdropColor(theme.bg[1]+.055,theme.bg[2]+.055,theme.bg[3]+.055,1) end
    end
    search:SetFont("Fonts\\FRIZQT__.TTF",fontSize,"")
    search:SetTextColor(unpack(theme.text))
    search:SetBackdropColor(theme.bg[1],theme.bg[2],theme.bg[3],1)
    search:SetBackdropBorderColor(unpack(theme.accent))
    modeLabel:SetText("Mode: "..(s.advanced and "Advanced" or "Easy").." v")
    for _,control in ipairs(sliderControls) do
        local value=control.key=="fontSize" and fontSize or control.key=="scale" and scale or opacity
        control.caption:SetText(control.label..": "..control.format(value).." v")
        local slider=control.slider
        slider.syncing=true
        slider:SetValue(control.key=="fontSize" and (value-10)/2 or math.floor(value*100+.5))
        slider.syncing=false
        slider:SetBackdropColor(theme.bg[1]+.055,theme.bg[2]+.055,theme.bg[3]+.055,1)
        slider:SetBackdropBorderColor(unpack(theme.accent))
        slider.sliderAccent=theme.accent
    end
    themeLabel:SetText("Theme: "..name.." v")
    minimapLabel:SetText("Minimap button: "..(s.showMinimapButton==false and "Hidden" or "Shown"))
    displayLabel:SetText("Display: "..ns.PresentationMode().." v")
    for _,panel in ipairs({settingsPanel,menu}) do
        panel:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile=name=="Classic" and "Interface\\DialogFrame\\UI-DialogBox-Border" or "Interface\\Buttons\\WHITE8X8",edgeSize=name=="Classic" and 20 or 1})
        panel:SetBackdropColor(theme.bg[1],theme.bg[2],theme.bg[3],1)
        panel:SetBackdropBorderColor(unpack(theme.accent))
    end
    for _,part in ipairs(lockParts) do part:SetBackdropColor(unpack(s.locked and theme.text or theme.accent)) end
    if s.locked then lockParts[4]:Show() else lockParts[4]:Hide() end
    title:SetText("Forever Professions  |  "..(ns.syntheticPreview and "SIMULATED" or "Recorded journal"))
    local owner=ns.viewOwner or ns.core.owner
    ownerLabel:SetText("Character: "..characterLabel(owner).." v")
    local c=ns.ViewCharacter(owner)
    local snapshot=c and c.latest
    local ps=snapshot and snapshot.professions or {}
    ns.professionIndex=math.min(math.max(1,ns.professionIndex or 1),math.max(1,#ps))
    local p=ps[ns.professionIndex]
    local cache=p and p.cache or c
    status:SetText(age(snapshot).."\n"..(c and c.attempt and "Latest attempt: "..c.attempt.status..(snapshot and c.attempt.status~="accepted" and " | Previous cache preserved" or "") or ns.notice))
    if not s.advanced then
        status:SetText(snapshot and ("Cached observation"..(c.attempt and c.attempt.status~="accepted" and " - refresh failed; previous data kept" or "")) or "No recorded data")
    end
    if c and c.probeCache then
        local prefix=cache.learnedCache and ("Cached learned "..p.name.." - "..cache.observedCounts.learned.." recipes") or "Cached probe - one recipe"
        local notice=cache.attempt.status=="unavailable" and "\nLast attempt refused; saved capture retained"
            or cache.attempt.status=="unknown" and "\nLatest attempt: Unknown" or ""
        status:SetText(prefix.." | "..age(p and p.cache or snapshot):gsub("Cached | ","")..notice)
    end
    profession:SetText(p and (short(p.name,30).."  "..ns.Display(p.skill).." / "..ns.Display(p.maxSkill).."  ("..ns.professionIndex.."/"..#ps..") v") or "Profession: Unknown v")
    local recipes,unresolved,unlearned,total={},0,0,0
    for _,r in ipairs(p and p.recipes or {}) do
        if r.learned.status=="known" and r.learned.value then
            total=total+1
            if query=="" or r.name:lower():find(query,1,true) then recipes[#recipes+1]=r end
        elseif r.learned.status~="known" then unresolved=unresolved+1
        else unlearned=unlearned+1 end
    end
    ns.recipeIndex=math.min(math.max(1,ns.recipeIndex or 1),math.max(1,#recipes))
    listSummary:SetText("Learned recipes: "..#recipes.." recorded\nUnknown: "..unresolved.." | Unlearned: "..unlearned)
    if query~="" and p then listSummary:SetText("Matches: "..#recipes.." / "..total.." learned\nUnknown: "..unresolved.." | Unlearned: "..unlearned) end
    if c and c.probeCache and cache.learnedCache then
        listSummary:SetText((query~="" and ("Matches: "..#recipes.." / "..total) or ("Learned recipes: "..total.." recorded"))
            .."\nReturned list: "..cache.observedCounts.unlearned.." unlearned; "..cache.observedCounts.unknown.." unknown")
    end
    if not p then listSummary:SetText("Learned recipes: Unknown\nNo profession observation") end
    if not s.advanced and p then listSummary:SetText(query~="" and (#recipes.." matches") or "Recipes") end
    updateScroll(recipeScroll,#recipes,theme)
    local listOffset=ns.recipeOffset
    for i,row in ipairs(rows) do
        local entry=recipes[listOffset+i]
        row.index=entry and listOffset+i or nil; row.recipe=entry
        showPlaceholder(row.icon,entry and entry.recipeID)
        if entry then
            row.label:SetText((row.index==ns.recipeIndex and "> " or "  ")..short(entry.name,ns.syntheticPreview and 25 or 29))
            if row.index==ns.recipeIndex then row.button:SetBackdropColor(theme.accent[1]*.35,theme.accent[2]*.35,theme.accent[3]*.35,1) end
            row.button:Show()
        else row.button:Hide() end
    end
    local r=recipes[ns.recipeIndex]
    ns.shownRecipe=r
    showPlaceholder(recipeIcon,r and r.recipeID)
    recipe:SetText(r and (short(r.name,42).."\nLearned when recorded  ("..ns.recipeIndex.."/"..#recipes..")") or "No confirmed learned recipes\nCoverage unknown; this is not proof of none")
    if not r and p and total>0 and query~="" then
        recipe:SetText("No recipe names match your search\nClear the filter to see recorded recipes")
    end
    if not s.advanced and r then recipe:SetText(short(r.name,42).."\nMaterials") end
    local lines,materialIDs,materials={},{},{}
    if r then
        if s.advanced then lines[#lines+1]="Recipe ID "..r.recipeID.." | Output item "..ns.Display(r.outputItemID) end
        if s.advanced then lines[#lines+1]="Output per craft: "..ns.Display(r.outputMin).." - "..ns.Display(r.outputMax) end
        if s.advanced or r.reagentsStatus~="known" then lines[#lines+1]="Materials: "..r.reagentsStatus end
        for i,slot in ipairs(r.slots) do
            local required=slot.required.status=="known" and (slot.required.value and "required" or "optional") or ns.Display(slot.required)
            if s.advanced then lines[#lines+1]="Slot "..i.." ("..required.."): "..ns.Display(slot.quantity).." per craft" end
            if slot.alternativesStatus~="known" then lines[#lines+1]="  Choices: "..slot.alternativesStatus end
            for _,item in ipairs(slot.alternatives) do
                lines[#lines+1]="  "..short(ns.Display(materialName(item)),30)..(s.advanced and " ["..item.itemID.."]" or " x "..ns.Display(slot.quantity))..(#slot.alternatives>1 and " (choose one)" or "")..(not s.advanced and required~="required" and " ("..required..")" or "")
                materialIDs[#lines]=item.itemID
                materials[#lines]={item=item,slot=slot}
            end
        end
    end
    if r and (s.advanced or r.requirementsStatus) then
        local state=r.requirementsStatus or "unknown"
        local requirements=r.requirements or {}
        if state=="known" and #requirements==0 then
            if s.advanced then lines[#lines+1]="Requirements: None returned when recorded" end
        else
            lines[#lines+1]="Requirements (recorded): "..(state=="known" and "" or state)
            for _,req in ipairs(requirements) do
                local met=req.met.status=="known" and (req.met.value and "Met" or "Unmet") or "Unknown"
                lines[#lines+1]=short(ns.Display(req.name),38).." - "..met
            end
        end
    end
    if r and s.advanced then
        lines[#lines+1]=s.advanced and "Craftability: Unknown | Owned materials: Unknown" or "Owned materials: Unknown"
    end
    updateScroll(detailScroll,#lines,theme)
    for i,t in ipairs(detailLabels) do
        local index=ns.detailOffset+i
        local hasIcon=ns.syntheticPreview and materialIDs[index]~=nil
        showPlaceholder(detailIcons[i],materialIDs[index])
        detailHovers[i].material=materials[index]
        if materials[index] then detailHovers[i]:Show() else detailHovers[i]:Hide() end
        t:ClearAllPoints(); t:SetPoint("TOPLEFT",window,"TOPLEFT",hasIcon and 374 or 340,-(248+(i-1)*34))
        t:SetSize(hasIcon and 430 or 464,36)
        t:SetText(lines[index] or "")
    end
    if refreshResult and (refreshResult.owner~=owner or refreshResult.professionID~=(p and p.skillLineID)) then refreshResult=nil end
    footer:SetText(ns.presentationNotice or (refreshResult and refreshResult.message) or (ns.syntheticPreview and "Synthetic preview | Manual refresh only" or "Cached journal | Manual refresh only"))
end
SLASH_WFPROFESSIONS1="/wfprofessions"
function ns.ToggleJournal() ns.Refresh(); if window:IsShown() then window:Hide() else window:Show() end end
SlashCmdList.WFPROFESSIONS=function(message)
    local command=type(message)=="string" and message:lower():match("^%s*(.-)%s*$") or ""
    if command=="settings" then ns.OpenSettings()
    elseif command=="minimap show" then if ns.SetMinimapVisible then ns.SetMinimapVisible(true) end
    elseif command=="minimap hide" then if ns.SetMinimapVisible then ns.SetMinimapVisible(false) end
    else ns.ToggleJournal() end
end
window:Hide()

-- Follow the client's profession window, including its existing keybinding.
-- Visibility hooks are additive: never replace Blizzard handlers or bindings.
-- Both frame names are already inspected by our context probe on Forever.
local followedFrames=setmetatable({}, {__mode="k"})
local function showAlongside(frame) ns.NativePresentationShown(frame) end
local function hideAlongside() ns.NativePresentationHidden() end
-- This client also closes UISpecialFrames during NPC interactions. Use a
-- propagating keyboard handler instead; all keys still reach the game, including
-- Escape so Blizzard can close its own window. Never remap or swallow a key.
if type(window.EnableKeyboard)=="function" and type(window.SetPropagateKeyboardInput)=="function" then
    window:EnableKeyboard(true)
    window:SetPropagateKeyboardInput(true)
    window:SetScript("OnKeyDown",function(_,key)
        if key=="ESCAPE" then window:Hide() end
    end)
end
local function followProfessionWindows()
    local ok,version,build,_,interface=pcall(GetBuildInfo)
    if not ok or version~="1.60.1" or tostring(build)~="70532" or interface~=16001 then return end
    for _,name in ipairs({"ProfessionsFrame","ProfessionsBookFrame"}) do
        local frame=_G[name]
        if frame and not followedFrames[frame] then
            -- Guard absent/unsupported frames. No polling or forced UI loading.
            local attached=pcall(function() frame:HookScript("OnShow",showAlongside); frame:HookScript("OnHide",hideAlongside) end)
            if attached then
                followedFrames[frame]=true
                local readable,shown=pcall(function() return frame:IsShown() end)
                if readable and shown==true then showAlongside(frame) end
            end
        end
    end
end
ns.core.On("ADDON_LOADED",followProfessionWindows)
ns.core.On("PLAYER_ENTERING_WORLD",followProfessionWindows)
ns.core.On("TRADE_SKILL_SHOW",followProfessionWindows)
