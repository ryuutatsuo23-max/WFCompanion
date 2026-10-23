-- SPDX-License-Identifier: GPL-3.0-only
local _,ns=...
-- Presentation-only entry points, reusable by a future shared launcher.
-- Neither action opens a native profession, captures observations or crafts.
function ns.LaunchProfessions(mouse)
    if mouse=="RightButton" then ns.OpenSettings() else ns.ToggleJournal() end
end
local launcher,dragged
local function finite(value)
    return type(value)=="number" and value==value and math.abs(value)<100000
end
local function position()
    if not launcher or not ns.store then return end
    local map=launcher:GetParent()
    local angle=ns.store.settings.minimapAngle
    if not finite(angle) then angle=225 end
    local radius=math.min(map:GetWidth(),map:GetHeight())/2+8
    launcher:ClearAllPoints()
    launcher:SetPoint("CENTER",map,"CENTER",math.cos(math.rad(angle))*radius,math.sin(math.rad(angle))*radius)
end
local function drag()
    if not launcher or not ns.store or type(GetCursorPosition)~="function" then return end
    local map=launcher:GetParent()
    local x,y=map:GetCenter(); local cx,cy=GetCursorPosition(); local scale=map:GetEffectiveScale()
    if not finite(x) or not finite(y) or not finite(cx) or not finite(cy) or not finite(scale) or scale<=0 then return end
    local dx,dy=cx/scale-x,cy/scale-y
    if dx==0 and dy==0 then return end
    ns.store.settings.minimapAngle=math.deg(math.atan2(dy,dx))%360
    position()
end
function ns.RefreshMinimapButton()
    if not ns.store then return end
    if not launcher then
        local map=Minimap or (MinimapCluster and MinimapCluster.MinimapContainer and MinimapCluster.MinimapContainer.Minimap)
        if not map or type(map.GetCenter)~="function" then return end
        launcher=CreateFrame("Button",nil,map)
        ns.minimapButton=launcher
        launcher:SetSize(32,32); launcher:SetFrameStrata("MEDIUM"); launcher:EnableMouse(true)
        launcher:RegisterForClicks("LeftButtonUp","RightButtonUp"); launcher:RegisterForDrag("LeftButton")
        local icon=launcher:CreateTexture(nil,"ARTWORK")
        icon:SetTexture("Interface\\AddOns\\WFProfessions\\branding\\forever-professions-icon")
        icon:SetSize(20,20); icon:SetPoint("CENTER",launcher,"CENTER",0,0)
        local rim=launcher:CreateTexture(nil,"OVERLAY")
        rim:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder"); rim:SetSize(54,54); rim:SetPoint("TOPLEFT",launcher,"TOPLEFT",0,0)
        launcher:SetScript("OnMouseDown",function() dragged=false end)
        launcher:SetScript("OnClick",function(_,mouse) if not dragged then ns.LaunchProfessions(mouse) end end)
        launcher:SetScript("OnDragStart",function()
            dragged=true; GameTooltip:Hide(); launcher:SetScript("OnUpdate",drag); drag()
        end)
        launcher:SetScript("OnDragStop",function() launcher:SetScript("OnUpdate",nil) end)
        launcher:SetScript("OnHide",function() launcher:SetScript("OnUpdate",nil); GameTooltip:Hide() end)
        launcher:SetScript("OnEnter",function()
            if dragged and launcher:GetScript("OnUpdate") then return end
            GameTooltip:SetOwner(launcher,"ANCHOR_CURSOR")
            GameTooltip:SetText("Forever Professions\nLeft-click: journal\nRight-click: settings\nDrag to move")
            GameTooltip:Show()
        end)
        launcher:SetScript("OnLeave",function() GameTooltip:Hide() end)
        map:HookScript("OnSizeChanged",position)
    end
    position()
    if ns.store.settings.showMinimapButton==false then launcher:Hide() else launcher:Show() end
end
function ns.SetMinimapVisible(visible)
    if not ns.store or type(visible)~="boolean" then return end
    ns.store.settings.showMinimapButton=visible
    ns.RefreshMinimapButton(); ns.Refresh()
end
ns.core.On("PLAYER_ENTERING_WORLD",ns.RefreshMinimapButton)
