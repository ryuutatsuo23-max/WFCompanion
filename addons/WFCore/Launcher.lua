local _,ns=...
-- Presentation only. Original project icons; client primitives are referenced only.
local entries,button,menu,dragged={},nil,nil,false
local function settings()
    return ns.db and ns.db.settings
end
local function finite(n)
    return type(n)=="number" and n==n and math.abs(n)<1000000
end
local function position()
    if not button then return end
    local map=button:GetParent()
    local angle=settings() and settings().coreMinimapAngle
    if not finite(angle) then angle=225 end
    local radius=math.min(map:GetWidth(),map:GetHeight())/2+8
    button:ClearAllPoints()
    button:SetPoint("CENTER",map,"CENTER",math.cos(math.rad(angle))*radius,math.sin(math.rad(angle))*radius)
end
local function drag()
    local saved=settings()
    if not saved or not button or type(GetCursorPosition)~="function" then return end
    local map=button:GetParent()
    local x,y=map:GetCenter();local cx,cy=GetCursorPosition();local scale=map:GetEffectiveScale()
    if not finite(x) or not finite(y) or not finite(cx) or not finite(cy) or not finite(scale) or scale<=0 then return end
    local dx,dy=cx/scale-x,cy/scale-y
    if dx==0 and dy==0 then return end
    saved.coreMinimapAngle=math.deg(math.atan2(dy,dx))%360
    position()
end
function ns.RegisterLauncher(id,title,callback,icon)
    if type(id)~="string" or type(title)~="string" or type(callback)~="function" then return false end
    if not entries[id] then
        entries[id]={title=title,callback=callback,icon=icon or "Interface\\AddOns\\WFCore\\branding\\wfcompanion-icon"}
        if menu then menu:Hide() end
    end
    return true
end
function ns.ToggleLauncher()
    if menu and menu:IsShown() then menu:Hide();return end
    if not menu then
        menu=CreateFrame("Frame",nil,UIParent,"BackdropTemplate")
        ns.launcherMenu=menu;menu.rows={}
        menu:SetFrameStrata("DIALOG");menu:SetClampedToScreen(true)
        menu:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1})
        menu:SetBackdropColor(.06,.07,.09,.98);menu:SetBackdropBorderColor(.6,.5,.25,1)
        local close=CreateFrame("Button",nil,menu,"UIPanelButtonTemplate")
        close:SetSize(44,22);close:SetPoint("BOTTOM",menu,"BOTTOM",0,8)
        close:SetText("Close");close:SetScript("OnClick",function() menu:Hide() end)
    end
    for _,row in ipairs(menu.rows) do row:Hide() end
    local ids={};for id in pairs(entries) do ids[#ids+1]=id end;table.sort(ids)
    for i,id in ipairs(ids) do
        local entry=entries[id]
        local row=menu.rows[i]
        if not row then
            row=CreateFrame("Button",nil,menu);menu.rows[i]=row
            row.icon=row:CreateTexture(nil,"ARTWORK");row.icon:SetSize(40,40);row.icon:SetPoint("CENTER",row,"CENTER",0,0)
        end
        row:SetSize(44,44);row:ClearAllPoints();row:SetPoint("TOPLEFT",menu,"TOPLEFT",8+((i-1)%4)*48,-8-math.floor((i-1)/4)*48)
        row.title=entry.title;row.icon:SetTexture(entry.icon)
        row:SetScript("OnEnter",function()
            if GameTooltip then GameTooltip:SetOwner(row,"ANCHOR_CURSOR");GameTooltip:SetText(entry.title.."\nLeft-click: open • Right-click: settings");GameTooltip:Show() end
        end)
        row:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
        row:RegisterForClicks("LeftButtonUp","RightButtonUp")
        row:SetScript("OnClick",function(_,mouse)
            menu:Hide()
            -- A broken optional module cannot break the launcher or other entries.
            if not pcall(entry.callback,mouse) and DEFAULT_CHAT_FRAME then
                DEFAULT_CHAT_FRAME:AddMessage("Forever: this addon action is unavailable.")
            end
        end)
        row:Show()
    end
    menu:SetSize(16+math.min(4,#ids)*48,42+math.ceil(#ids/4)*48);menu:ClearAllPoints()
    if button then menu:SetPoint("TOPRIGHT",button,"BOTTOMLEFT",0,0)
    else menu:SetPoint("CENTER",UIParent,"CENTER",0,0) end
    menu:Show()
end
function ns.RefreshCoreMinimapButton()
    if not button then
        local map=Minimap or (MinimapCluster and MinimapCluster.MinimapContainer and MinimapCluster.MinimapContainer.Minimap)
        if not map or type(map.GetCenter)~="function" then return end
        button=CreateFrame("Button",nil,map,"BackdropTemplate");ns.coreMinimapButton=button
        button:SetSize(32,32);button:SetFrameStrata("MEDIUM");button:EnableMouse(true)
        button:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1})
        button:SetBackdropColor(.08,.07,.04,1);button:SetBackdropBorderColor(.8,.65,.3,1)
        local icon=button:CreateTexture(nil,"ARTWORK")
        icon:SetSize(30,30);icon:SetPoint("CENTER",button,"CENTER",0,0)
        icon:SetTexture("Interface\\AddOns\\WFCore\\branding\\wfcompanion-icon")
        button:RegisterForClicks("LeftButtonUp","RightButtonUp");button:RegisterForDrag("LeftButton")
        button:SetScript("OnMouseDown",function() dragged=false end)
        button:SetScript("OnClick",function() if not dragged then ns.ToggleLauncher() end end)
        button:SetScript("OnDragStart",function()
            dragged=true;if menu then menu:Hide() end
            if GameTooltip then GameTooltip:Hide() end
            button:SetScript("OnUpdate",drag);drag()
        end)
        button:SetScript("OnDragStop",function() button:SetScript("OnUpdate",nil) end)
        button:SetScript("OnHide",function()
            button:SetScript("OnUpdate",nil);if menu then menu:Hide() end
            if GameTooltip then GameTooltip:Hide() end
        end)
        button:SetScript("OnEnter",function()
            if not GameTooltip then return end
            GameTooltip:SetOwner(button,"ANCHOR_CURSOR")
            GameTooltip:SetText("Forever addons\nClick: addon menu\nMenu left-click: open; right-click: settings\nDrag to move\n/wfcore minimap show restores this button")
            GameTooltip:Show()
        end)
        button:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
        map:HookScript("OnSizeChanged",position)
    end
    position()
    if settings() and settings().coreMinimapHidden==true then button:Hide() else button:Show() end
end
function ns.SetCoreMinimapVisible(visible)
    if type(visible)~="boolean" or not settings() then return end
    settings().coreMinimapHidden=not visible;ns.RefreshCoreMinimapButton()
end
ns.On("PLAYER_ENTERING_WORLD",ns.RefreshCoreMinimapButton)
