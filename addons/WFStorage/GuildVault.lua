local _,ns=...
-- Session-only guild browsing. Never write guild records into character snapshots.
-- Transfers, money and permission administration remain in Blizzard's UI.
local vault={open=false,selected=nil}
ns.guildVault=vault
local frame,title,status,search,footer,lockButton
local mode="Bank"
local request
local textRows={}
local modeButtons={}
local tabs,rows,controls={},{},{}
local page=1
local backdrop={bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1}
local function tabInfo(index)
    return ns.Read(function()
        local name,icon,view,deposit,limit,remaining=GetGuildBankTabInfo(index)
        return {name=name,icon=icon,view=view,deposit=deposit,remaining=remaining}
    end)
end
function ns.ReadGuildVault()
    local result={tabs={},items={},message="Visit your guild vault",guild="Guild vault"}
    if not vault.open or not ns.inWorld then return result end
    local guild=ns.Read(GetGuildInfo,"player")
    if type(guild)~="string" or guild=="" then result.message="Guild identity unavailable"; return result end
    if vault.guild~=guild then result.message="Guild changed: reopen the vault";return result end
    result.guild=guild
    local count=ns.Read(GetNumGuildBankTabs)
    if not ns.Integer(count,0,20) then result.message="Guild tabs unavailable"; return result end
    local selected
    for i=1,count do
        local data=tabInfo(i)
        local name=ns.Field(data,"name")
        local view=ns.Field(data,"view")
        local tab={index=i,name=type(name)=="string" and name or ("Tab "..i),view=view==true}
        result.tabs[#result.tabs+1]=tab
        if tab.view and (not selected or i==vault.selected) then selected=tab end
    end
    if not selected then
        result.message=count==0 and "No guild vault tabs available" or "No permission to view guild vault tabs"
        vault.selected=nil; return result
    end
    vault.selected=selected.index; result.selected=selected.index
    if ns.Read(GetCurrentGuildBankTab)~=selected.index then
        result.message="Select a tab or Refresh to request its contents"; return result
    end
    -- The native grid is 7 groups of 14 slots (98), from captured Forever UI.
    -- A missing link is unreadable/empty, never proof of an empty guild slot.
    for slot=1,98 do
        local link=ns.Read(GetGuildBankItemLink,selected.index,slot)
        if type(link)=="string" then
            local id=tonumber(link:match("item:(%d+)"))
            local data=ns.Read(function()
                local icon,count,locked=GetGuildBankItemInfo(selected.index,slot)
                return {icon=icon,count=count,locked=locked}
            end)
            local count=ns.Field(data,"count")
            if ns.Integer(id,1,2147483647) and ns.Integer(count,1,1000000) then
                local name=ns.Read(function() return C_Item.GetItemNameByID(id) end)
                result.items[#result.items+1]={slot=slot,link=link,id=id,count=count,
                    name=type(name)=="string" and name or ("Item "..id),icon=ns.Field(data,"icon")}
            end
        end
    end
    result.message="Viewing "..selected.name.." · Read-only"
    return result
end
local function label(parent,size)
    local t=parent:CreateFontString(nil,"OVERLAY","GameFontNormal")
    t:SetFont("Fonts\\FRIZQT__.TTF",size);t:SetJustifyH("LEFT");return t
end
local function button(text,x,y,width,callback)
    local b=CreateFrame("Button",nil,frame,"BackdropTemplate")
    b:SetBackdrop(backdrop);b:SetSize(width,26);b:SetPoint("TOPLEFT",x,y)
    b.caption=label(b,12);b.caption:SetPoint("CENTER");b.caption:SetText(text)
    b:SetScript("OnClick",callback);controls[#controls+1]=b;return b
end
-- Requests and responses stay in this vault session; never persist guild history.
local function identityReady()
    return vault.open and ns.inWorld and type(vault.guild)=="string" and ns.Read(GetGuildInfo,"player")==vault.guild
end
local function chunks(value)
    local result,current,n={},"",0
    -- UTF-8 codepoints, so wrapped guild notes never split a multibyte character.
    for char in value:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
        current=current..char;n=n+1
        if n==60 then result[#result+1]=current;current="";n=0 end
    end
    if current~="" then result[#result+1]=current end
    return result
end
local function money(amount)
    if not ns.Integer(amount,0,100000000000000) then return "Unknown amount" end
    return math.floor(amount/10000).."g "..math.floor(amount/100)%100 .."s "..amount%100 .."c"
end
function ns.ReadGuildHistory()
    local lines={}
    if not identityReady() then return lines,"Visit your guild vault" end
    local selected=ns.ReadGuildVault().selected
    if mode~="Money Log" and not selected then return lines,"No permission to view guild vault tabs" end
    if not request or request.mode~=mode or request.tab~=selected then return lines,"Refresh to request this view" end
    if not request.ready then return lines,request.error or "Waiting for guild vault response" end
    if mode=="Info" then
        local value=ns.Read(GetGuildBankText,selected)
        if type(value)~="string" then return lines,"Guild information unavailable" end
        -- Preserve newlines; bounded chunks keep long notes reachable at large fonts.
        value=value:gsub("|c%x%x%x%x%x%x%x%x",""):gsub("|r","")
        for line in (value.."\n"):gmatch("([^\n]*)\n") do
            if line=="" then lines[#lines+1]=" " end
            for _,part in ipairs(chunks(line)) do lines[#lines+1]=part end
        end
        return lines,value=="" and "No tab information returned" or "Tab information · Read-only"
    end
    local count
    if mode=="Money Log" then count=ns.Read(GetNumGuildBankMoneyTransactions)
    else count=ns.Read(GetNumGuildBankTransactions,selected) end
    if not ns.Integer(count,0,1000) then return lines,"Guild log unavailable" end
    for i=1,count do
        local record=ns.Read(function()
            if mode=="Money Log" then
                local kind,name,amount=GetGuildBankMoneyTransaction(i)
                return {kind=kind,name=name,detail=money(amount)}
            end
            local kind,name,link,count,from,to=GetGuildBankTransaction(selected,i)
            local item=type(link)=="string" and (link:match("%[(.-)%]") or link) or "Unknown item"
            local detail=item.." x"..(ns.Integer(count,1,1000000) and count or "?")
            if kind=="move" then detail=detail.." (tab "..tostring(from or "?").." to "..tostring(to or "?")..")" end
            return {kind=kind,name=name,detail=detail}
        end)
        if type(record)=="table" then
            local verbs={deposit="deposited",withdraw="withdrew",move="moved",repair="repaired with",withdrawForTab="withdrew for a tab",buyTab="bought a tab for",depositSummary="deposited",buyRename="bought a rename for",refundRename="received a rename refund of"}
            local who=type(record.name)=="string" and record.name or "Unknown player"
            lines[#lines+1]=who.." "..(verbs[record.kind] or "transaction").." "..record.detail
        else lines[#lines+1]="Unreadable log entry" end
    end
    return lines,count==0 and "No log entries returned" or (mode.." · Read-only")
end
function ns.SetGuildMode(value)
    if value~="Bank" and value~="Log" and value~="Money Log" and value~="Info" then return end
    mode=value;request=nil;page=1;ns.QueryGuildVault()
end
function ns.RefreshGuildVault()
    if not frame or not frame:IsShown() then return end
    local data=ns.ReadGuildVault()
    local options=ns.ViewOptions("guild");local theme=ns.Themes[options.theme]
    local width=math.max(592,32+options.columns*(options.iconSize+6))
    frame:SetWidth(width)
    ns.ApplyPanelTheme(frame,theme,options.opacity)
    for _,b in ipairs(controls) do ns.ApplyControlTheme(b,theme) end
    ns.ApplyControlTheme(lockButton,theme);ns.RefreshLockButton(lockButton)
    title:SetText(data.guild.." - Guild vault");title:SetTextColor(unpack(theme.text));title:SetWidth(width-260)
    for name,b in pairs(modeButtons) do b.caption:SetText((name==mode and "• " or "")..name) end
    status:SetText(data.message);status:SetTextColor(unpack(theme.text));status:SetWidth(width-32)
    for _,b in ipairs(tabs) do b:Hide() end
    for i,tab in ipairs(data.tabs) do
        local b=tabs[i]
        if not b then
            b=button("",16+((i-1)%5)*112,-122-math.floor((i-1)/5)*28,106,function()
                if tabs[i].view then vault.selected=i;page=1;request=nil;ns.QueryGuildVault() end
            end);tabs[i]=b
        end
        b.view=tab.view;b.caption:SetText((tab.view and "" or "Locked: ")..tab.name)
        b.caption:SetSize(100,22);ns.ApplyControlTheme(b,theme)
        if mode~="Money Log" then b:Show() end
    end
    local top=132+(mode=="Money Log" and 0 or math.ceil(#data.tabs/5)*28)
    for _,row in ipairs(rows) do row:Hide();row.item=nil end
    for _,row in ipairs(textRows) do row:Hide() end
    local query=(search:GetText() or ""):lower();local filtered={}
    local size=options.iconSize;local columns=options.view=="List" and 1 or options.columns
    local perPage=options.view=="List" and 6 or columns*3
    if mode=="Bank" then
        for _,item in ipairs(data.items) do
            item.category=ns.ItemCategory({state="observed",itemID=item.id})
            if (options.category=="All" or item.category==options.category) and (item.name.." "..item.id):lower():find(query,1,true) then filtered[#filtered+1]=item end
        end
        table.sort(filtered,function(a,b)
            if options.order=="Name" and a.name~=b.name then return a.name<b.name end
            if options.order=="Count" and a.count~=b.count then return a.count>b.count end
            if options.order=="Category" and a.category~=b.category then return a.category<b.category end
            return a.slot<b.slot
        end)
    else
        local message;local lines;lines,message=ns.ReadGuildHistory();status:SetText(message)
        for _,line in ipairs(lines) do
            if line:lower():find(query,1,true) then
                if line==" " then filtered[#filtered+1]=line else
                    for _,part in ipairs(chunks(line)) do filtered[#filtered+1]=part end
                end
            end
        end
        perPage=6
    end
    local pages=math.max(1,math.ceil(#filtered/perPage));page=math.min(page,pages)
    local height=mode=="Bank" and math.ceil(perPage/columns)*(size+6) or 6*(options.fontSize*3+8)
    for i=1,perPage do
        local item=filtered[(page-1)*perPage+i]
        if mode=="Bank" then
            local row=rows[i]
            if item then
                row.item=item;row:ClearAllPoints();row:SetPoint("TOPLEFT",16+((i-1)%columns)*(size+6),-top-math.floor((i-1)/columns)*(size+6))
                row:SetSize(options.view=="List" and width-32 or size,size)
                row.icon:SetSize(size-4,size-4);row.icon:SetTexture(item.icon or "Interface\\Icons\\INV_Misc_QuestionMark")
                local quality=ns.Read(function() return C_Item.GetItemQualityByID(item.id) end)
                row.icon:SetDesaturated(options.dimPoor and quality==0);row.icon:SetAlpha(options.dimPoor and quality==0 and .5 or 1)
                row.count:SetText(tostring(item.count));row.caption:SetText(options.view=="List" and item.name or "")
                row.caption:ClearAllPoints();row.caption:SetPoint("TOPLEFT",size+8,-4);row.caption:SetSize(width-size-70,size-8)
                row.caption:SetFont("Fonts\\FRIZQT__.TTF",options.fontSize);row:Show()
            end
        elseif item then
            local row=textRows[i];row:ClearAllPoints();row:SetPoint("TOPLEFT",16,-top-(i-1)*(options.fontSize*3+8))
            row:SetFont("Fonts\\FRIZQT__.TTF",options.fontSize);row:SetSize(width-32,options.fontSize*3+6);row:SetText(item);row:SetTextColor(unpack(theme.text));row:Show()
        end
    end
    footer:SetText(#filtered..(mode=="Bank" and " readable stacks" or " lines").." | Page "..page.." / "..pages.."\nUse Native UI for transfers, money and permissions.")
    footer:ClearAllPoints();footer:SetPoint("TOPLEFT",16,-top-height-48);footer:SetWidth(width-32)
    frame:SetHeight(top+height+108)
    frame:SetScale(math.min(options.windowScale,UIParent:GetWidth()/(width+24),UIParent:GetHeight()/(top+height+132)))
end
function ns.QueryGuildVault()
    local data=ns.ReadGuildVault()
    if not identityReady() or not ns.InteractionReady() then request=nil;ns.RefreshGuildVault();return end
    if mode~="Money Log" and (not data.selected or ns.Field(tabInfo(data.selected),"view")~=true) then request=nil;ns.RefreshGuildVault();return end
    local fn,arg
    if mode=="Money Log" then
        fn=QueryGuildBankLog
        if ns.Integer(MAX_GUILDBANK_TABS,1,20) then arg=MAX_GUILDBANK_TABS+1 end
    else
        if type(SetCurrentGuildBankTab)=="function" then pcall(SetCurrentGuildBankTab,data.selected) end
        fn=mode=="Bank" and QueryGuildBankTab or mode=="Info" and QueryGuildBankText or QueryGuildBankLog
        arg=data.selected
    end
    request={mode=mode,tab=data.selected,ready=false}
    if type(fn)~="function" or not arg then request.error="This guild view is unavailable on this client"
    elseif not pcall(fn,arg) then request.error="Could not request guild data; try Refresh" end
    ns.RefreshGuildVault()
end
function ns.ShowGuildVault()
    if not frame then
        frame=CreateFrame("Frame",nil,UIParent,"BackdropTemplate")
        frame:SetSize(592,380);frame:SetPoint("CENTER",UIParent,"CENTER",200,0)
        frame:SetBackdrop(backdrop);frame:SetFrameStrata("DIALOG");frame:SetClampedToScreen(true)
        frame:EnableMouse(true);frame:SetMovable(true);frame:RegisterForDrag("LeftButton")
        frame:SetScript("OnDragStart",function() if not ns.ViewOptions("guild").lockWindow then frame:StartMoving() end end)
        frame:SetScript("OnDragStop",function()
            frame:StopMovingOrSizing()
            local x,y=frame:GetCenter();local px,py=UIParent:GetCenter();local scale=frame:GetScale()
            if ns.db and x and y and px and py and scale>0 then ns.db.settings.guildPosition={x=x-px/scale,y=y-py/scale} end
        end)
        local saved=ns.db and ns.db.settings.guildPosition
        if type(saved)=="table" and type(saved.x)=="number" and type(saved.y)=="number" and math.abs(saved.x)<10000 and math.abs(saved.y)<10000 then
            frame:ClearAllPoints();frame:SetPoint("CENTER",UIParent,"CENTER",saved.x,saved.y)
        end
        ns.EnableEscapeClose(frame,function() frame:Hide() end)
        title=label(frame,14);title:SetPoint("TOPLEFT",16,-16);title:SetSize(410,24)
        local close=button("X",550,-12,26,function() frame:Hide() end)
        close:ClearAllPoints();close:SetPoint("TOPRIGHT",-16,-12)
        lockButton=ns.CreateLockButton(frame,"guild");lockButton:SetPoint("TOPRIGHT",-84,-12)
        local cog=button("",0,0,26,function() ns.ToggleSettings("guild") end)
        cog:ClearAllPoints();cog:SetPoint("TOPRIGHT",-50,-12);cog:SetNormalTexture("Interface\\Buttons\\UI-OptionsButton")
        ns.SetTooltip(cog,"Guild settings")
        local native=button("Native UI",450,-12,92,function()
            frame:Hide()
            if vault.open and GuildBankFrame and type(GuildBankFrame.Show)=="function" then GuildBankFrame:Show() end
        end)
        native:ClearAllPoints();native:SetPoint("TOPRIGHT",-118,-12)
        for i,name in ipairs({"Bank","Log","Money Log","Info"}) do
            modeButtons[name]=button(name,16+(i-1)*120,-46,112,function() ns.SetGuildMode(name) end)
        end
        for i=1,6 do textRows[i]=label(frame,14) end
        search=CreateFrame("EditBox",nil,frame,"InputBoxTemplate")
        search:SetPoint("TOPLEFT",24,-80);search:SetSize(420,24);search:SetAutoFocus(false);search:SetMaxLetters(80)
        search:SetScript("OnTextChanged",function() page=1;ns.RefreshGuildVault() end)
        search:SetScript("OnEscapePressed",function() search:ClearFocus();frame:Hide() end)
        button("Refresh",458,-80,118,ns.QueryGuildVault)
        status=label(frame,12);status:SetPoint("TOPLEFT",16,-108);status:SetSize(560,20)
        for i=1,42 do
            local row=CreateFrame("Button",nil,frame,"BackdropTemplate");row:SetSize(36,36);row:SetBackdrop(backdrop)
            row.icon=row:CreateTexture(nil,"ARTWORK");row.icon:SetPoint("TOPLEFT",2,-2);row.icon:SetSize(32,32)
            row.caption=label(row,14)
            row.count=label(row,11);row.count:SetPoint("BOTTOMRIGHT",-2,2)
            row:SetScript("OnEnter",function()
                if row.item and GameTooltip then
                    GameTooltip:SetOwner(row,"ANCHOR_CURSOR");GameTooltip:SetText(row.item.name)
                    GameTooltip:AddLine("x"..row.item.count.." · Read-only");GameTooltip:Show()
                end
            end)
            row:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
            rows[i]=row
        end
        local prev=button("Previous",16,0,90,function() page=math.max(1,page-1);ns.RefreshGuildVault() end)
        prev:ClearAllPoints();prev:SetPoint("BOTTOMLEFT",16,70)
        local nextButton=button("Next",114,0,76,function() page=page+1;ns.RefreshGuildVault() end)
        nextButton:ClearAllPoints();nextButton:SetPoint("BOTTOMLEFT",114,70)
        footer=label(frame,12);footer:SetSize(560,44)
    end
    frame:Show();ns.QueryGuildVault()
end
local function opened()
    if vault.open then return end -- Legacy and interaction-manager events may both fire.
    mode="Bank";request=nil;vault.open=true;vault.guild=ns.Read(GetGuildInfo,"player");vault.selected=nil;page=1;ns.ShowGuildVault()
    ns.RefreshUI()
end
ns.On("GUILDBANKFRAME_OPENED",opened)
local function closed()
    request=nil;vault.open=false;vault.guild=nil;vault.selected=nil;if frame then frame:Hide() end
    ns.RefreshUI()
end
ns.On("GUILDBANKFRAME_CLOSED",closed)
-- Forever's Blizzard_GuildBankUI bootstrap registers GuildBanker with the
-- player interaction manager. Keep the legacy events as a compatible fallback.
local function isGuildInteraction(kind)
    local expected=ns.Read(function() return Enum.PlayerInteractionType.GuildBanker end)
    return expected~=nil and kind==expected
end
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW",function(kind) if isGuildInteraction(kind) then opened() end end)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_HIDE",function(kind) if isGuildInteraction(kind) then closed() end end)
ns.On("PLAYER_LEAVING_WORLD",closed)
ns.On("PLAYER_GUILD_UPDATE",function() vault.selected=nil;ns.RefreshGuildVault() end)
for _,event in ipairs({"GUILDBANK_UPDATE_TABS","GUILDBANKBAGSLOTS_CHANGED","GUILDBANK_ITEM_LOCK_CHANGED"}) do
    ns.On(event,ns.RefreshGuildVault)
end

ns.On("GUILDBANKLOG_UPDATE",function()
    if request and (request.mode=="Log" or request.mode=="Money Log") then request.ready=true;ns.RefreshGuildVault() end
end)
ns.On("GUILDBANK_UPDATE_TEXT",function(tab)
    if request and request.mode=="Info" and request.tab==tab then request.ready=true;ns.RefreshGuildVault() end
end)
ns.On("GUILDBANK_TEXT_CHANGED",function(tab)
    if mode=="Info" and vault.selected==tab then ns.QueryGuildVault() end
end)
