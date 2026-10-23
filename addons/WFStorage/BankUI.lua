local _,ns=...
local frame,info,footer,search
local previous,nextPage,lockButton
local rows={}; local page=1
local controls={}
local categoryHeaders={}
local collapsedCategories={}
local filterLabel,clearFilters,emptyLabel
local backdrop={bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1}
local function text(parent,size)
    local f=parent:CreateFontString(nil,"OVERLAY","GameFontNormal")
    f:SetFont("Fonts\\FRIZQT__.TTF",size); f:SetJustifyH("LEFT"); return f
end
local function button(label,x,y,w,callback,hint)
    local b=CreateFrame("Button",nil,frame,"BackdropTemplate")
    b:SetPoint("TOPLEFT",x,y); b:SetSize(w,26); b:SetBackdrop(backdrop)
    b:SetBackdropColor(0.10,0.13,0.17,1); b:SetBackdropBorderColor(0.3,0.4,0.5,1)
    local t=text(b,12); t:SetPoint("CENTER"); t:SetText(label)
    b.caption=t; controls[#controls+1]=b
    b:SetScript("OnClick",callback)
    ns.SetTooltip(b,hint or label); return b
end
function ns.RefreshBankUI()
    if not frame or not frame:IsShown() then return end
    local options=ns.ViewOptions("bank"); local theme=ns.Themes[options.theme]
    local items=ns.InventoryRows("bank",search:GetText(),false,true)
    ns.SortInventory(items,options.order,"bank")
    local capacity=options.columns*4
    if options.order~="Category" then page=math.max(1,math.min(page,math.max(1,math.ceil(#items/capacity)))) end
    local visible=math.min(capacity,math.max(0,#items-(page-1)*capacity))
    local step=options.iconSize+8
    local filterSummary=ns.FilterSummary(search:GetText(),options.category,false)
    local top=filterSummary and 132 or 100
    local bottom=top+math.max(1,math.ceil(visible/options.columns))*step+12
    local sections,section
    local pages=math.max(1,math.ceil(#items/capacity))
    if options.order=="Category" then
        sections=ns.CategoryPages(items,options.columns,step,step*4+96,capacity,collapsedCategories,"bank")
        pages=#sections; page=math.min(page,pages); section=sections[page]
        bottom=top+math.max(step,section.height)+12
    end
    local width=math.max(480,32+options.columns*step)
    for _,header in ipairs(categoryHeaders) do header:Hide() end
    for i,group in ipairs(section and section.headers or {}) do
        local header=categoryHeaders[i]
        if not header then
            header=ns.CreateCategoryHeader(frame,function(key)
                collapsedCategories[key]=not collapsedCategories[key]; page=1; ns.RefreshBankUI()
            end); categoryHeaders[i]=header
        end
        header:ClearAllPoints(); header:SetPoint("TOPLEFT",16,-top-group.y)
        header.categoryKey=group.key; header:SetSize(width-32,22)
        header.caption:SetSize(width-32,22); header.caption:SetText(group.text); header.caption:SetTextColor(unpack(theme.accent)); header:Show()
    end
    if filterSummary then
        filterLabel:SetText(filterSummary); filterLabel:SetTextColor(unpack(theme.accent))
        filterLabel:SetSize(width-146,22); filterLabel:Show()
        clearFilters:ClearAllPoints(); clearFilters:SetPoint("TOPRIGHT",-16,-100); clearFilters:Show()
    else filterLabel:Hide(); clearFilters:Hide() end
    emptyLabel:ClearAllPoints(); emptyLabel:SetPoint("TOPLEFT",16,-top-8)
    emptyLabel:SetSize(width-32,24); emptyLabel:SetTextColor(unpack(theme.text))
    emptyLabel:SetText(#items==0 and (filterSummary and "No matching items - clear filters to show more" or "No observed bank items") or "")
    bottom=bottom+ns.RefreshBagSlotStrip(frame,"bank",ns.owner,bottom,width)
    frame:SetSize(width,bottom+92)
    search:SetWidth(width-118)
    previous:ClearAllPoints(); previous:SetPoint("TOPLEFT",16,-bottom)
    nextPage:ClearAllPoints(); nextPage:SetPoint("TOPLEFT",114,-bottom)
    footer:ClearAllPoints(); footer:SetPoint("TOPLEFT",16,-bottom-40)
    ns.ApplyPanelTheme(frame,theme,options.opacity)
    info:SetTextColor(unpack(theme.text)); footer:SetTextColor(0.65,0.73,0.8)
    for _,b in ipairs(controls) do ns.ApplyControlTheme(b,theme) end
    frame:SetScale(math.min(options.windowScale,UIParent:GetWidth()/(width+24),UIParent:GetHeight()/(bottom+116)))
    local location=ns.character and ns.character.locations.bank
    local snap=location and location.latest
    info:SetWidth(width-202)
    ns.RefreshLockButton(lockButton,"bank")
    info:SetText(ns.CharacterLabel(ns.character and ns.character.identity or {}).." - Bank\n"..
        (location and location.attempt and "Updating; previous snapshot" or "Last seen: "..ns.SnapshotAge(snap and snap.finishedAt)).." | "..ns.CapacityText(snap))
    for i,row in ipairs(rows) do
        local placement=section and section.entries[i]
        local entry=section and (placement and placement.entry) or (not section and i<=capacity and items[(page-1)*capacity+i] or nil); row.entry=entry
        if entry then
            row:ClearAllPoints(); row:SetPoint("TOPLEFT",16+(placement and placement.x or ((i-1)%options.columns)*step),-top-(placement and placement.y or math.floor((i-1)/options.columns)*step))
            row:SetSize(options.iconSize,options.iconSize); row.icon:SetSize(options.iconSize-4,options.iconSize-4)
            row.count:SetFont("Fonts\\FRIZQT__.TTF",options.fontSize,"OUTLINE"); row.count:SetTextColor(1,1,1)
            row.icon:SetTexture(entry.item.icon or "Interface\\Icons\\INV_Misc_QuestionMark")
            row:SetBackdropBorderColor(unpack(ns.QualityColors[entry.item.quality] or {.25,.30,.36}))
            row.icon:SetDesaturated(options.dimPoor and entry.item.quality==0)
            row.icon:SetAlpha(options.dimPoor and entry.item.quality==0 and .5 or 1)
            row.count:SetText(entry.item.count and tostring(entry.item.count) or "?"); row.star:SetText(entry.favorite and "*" or "")
            row:Show()
        else row:Hide() end
    end
    footer:SetText(#items.." stacks ("..options.category..") | Page "..page.." / "..pages.."\n"..(ns.StatusNotice()~="Ready" and ns.StatusNotice() or "Right-click: withdraw  |  Alt+left: favorite"))
end
function ns.HideBankUI() if frame then frame:Hide() end end
function ns.ShowBankUI()
    if ns.UsesNativeUI() then return end
    if not frame then
        frame=CreateFrame("Frame",nil,UIParent,"BackdropTemplate")
        ns.EnableEscapeClose(frame,ns.CloseInventoryWindows)
        frame:SetSize(466,394); frame:SetPoint("CENTER",UIParent,"CENTER",-360,0)
        local saved=ns.db and ns.db.settings.bankPosition
        if type(saved)=="table" and type(saved.x)=="number" and type(saved.y)=="number"
            and math.abs(saved.x)<10000 and math.abs(saved.y)<10000 then
            frame:ClearAllPoints(); frame:SetPoint("CENTER",UIParent,"CENTER",saved.x,saved.y)
        end
        frame:SetBackdrop(backdrop); frame:SetFrameStrata("DIALOG"); frame:SetClampedToScreen(true)
        frame:EnableMouse(true); frame:SetMovable(true); frame:RegisterForDrag("LeftButton")
        frame:SetScript("OnDragStart",function() if not ns.ViewOptions("bank").lockWindow then frame:StartMoving() end end)
        frame:SetScript("OnDragStop",function()
            frame:StopMovingOrSizing()
            local x,y=frame:GetCenter(); local px,py=UIParent:GetCenter(); local scale=frame:GetScale()
            if ns.db and x and y and px and py and scale>0 then ns.db.settings.bankPosition={x=x-px/scale,y=y-py/scale} end
        end)
        info=text(frame,14); info:SetPoint("TOPLEFT",16,-14); info:SetSize(335,40)
        local close=button("X",424,-12,26,function()
            if ns.InteractionReady() and C_Bank and type(C_Bank.CloseBankFrame)=="function" then C_Bank.CloseBankFrame() end
        end,"Close bank")
        close:ClearAllPoints(); close:SetPoint("TOPRIGHT",-16,-12)
        local sort=button("Sort",366,-12,50,function() ns.SortLiveInventory("bank") end,"Sort character bank using WoW's sort rules. Moves items.")
        sort:ClearAllPoints(); sort:SetPoint("TOPRIGHT",-118,-12)
        lockButton=ns.CreateLockButton(frame,"bank"); lockButton:SetPoint("TOPRIGHT",-84,-12)
        local cog=button("",0,0,26,function() ns.ToggleSettings("bank") end,"Bank settings")
        cog:ClearAllPoints(); cog:SetPoint("TOPRIGHT",-50,-12)
        cog:SetNormalTexture("Interface\\Buttons\\UI-OptionsButton")
        local searchLabel=text(frame,12); searchLabel:SetPoint("TOPLEFT",16,-65); searchLabel:SetText("Search"); searchLabel:SetTextColor(.65,.73,.8)
        search=CreateFrame("EditBox",nil,frame,"InputBoxTemplate")
        search:SetPoint("TOPLEFT",96,-63); search:SetSize(348,24); search:SetAutoFocus(false); search:SetMaxLetters(80)
        search:SetScript("OnTextChanged",function() page=1; ns.RefreshBankUI() end)
        search:SetScript("OnEscapePressed",function() search:ClearFocus(); ns.CloseInventoryWindows() end)
        filterLabel=text(frame,11); filterLabel:SetPoint("TOPLEFT",16,-103)
        emptyLabel=text(frame,12)
        clearFilters=button("Clear filters",0,-100,112,function()
            page=1; ns.SetViewOption("category","All","bank")
            search:SetText(""); search:ClearFocus(); ns.RefreshUI(); ns.RefreshBankUI()
        end,"Clear this bank window's search and category filter. Bags settings stay unchanged.")
        for i=1,40 do
            local row=CreateFrame("Button",nil,frame,"BackdropTemplate,InsecureActionButtonTemplate")
            row:SetSize(38,38); row:SetPoint("TOPLEFT",16+((i-1)%10)*43,-100-math.floor((i-1)/10)*43)
            row:SetBackdrop(backdrop); row:SetBackdropBorderColor(0.4,0.5,0.6,1)
            row.icon=row:CreateTexture(nil,"ARTWORK"); row.icon:SetPoint("TOPLEFT",2,-2); row.icon:SetSize(34,34)
            row.count=text(row,13); row.count:SetPoint("BOTTOMRIGHT",-2,2)
            row.star=text(row,13); row.star:SetPoint("TOPRIGHT",-2,-2)
            row:RegisterForClicks("LeftButtonUp","RightButtonUp")
            ns.EnableItemDrag(row)
            ns.ConfigureItemButton(row)
            row:SetScript("OnEnter",function()
                if row.entry and GameTooltip then
                    GameTooltip:SetOwner(row,"ANCHOR_RIGHT"); GameTooltip:SetText(row.entry.name)
                    GameTooltip:AddLine("Category: "..row.entry.category)
                    GameTooltip:AddLine("Observed count: "..tostring(row.entry.item.count or "Unknown"))
                    GameTooltip:AddLine("Last seen: "..ns.SnapshotAge(row.entry.at))
                    GameTooltip:AddLine(ns.ActionHint(row.entry)); GameTooltip:Show()
                end
            end)
            row:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
            rows[i]=row
        end
        previous=button("Previous",16,-284,90,function() page=math.max(1,page-1); ns.RefreshBankUI() end)
        nextPage=button("Next",114,-284,76,function() page=page+1; ns.RefreshBankUI() end)
        footer=text(frame,12); footer:SetPoint("TOPLEFT",16,-326); footer:SetSize(434,48)
        frame:SetScript("OnReceiveDrag",function() ns.DropInFreeSlot("bank") end)
        frame:SetScript("OnMouseUp",function(_,mouse) if mouse=="LeftButton" then ns.DropInFreeSlot("bank") end end)
        frame:SetScript("OnHide",function() ns.CloseItemSplit(frame); if GameTooltip then GameTooltip:Hide() end end)
    end
    page=1; frame:Show(); ns.RefreshBankUI()
end
