local _, ns = ...
-- Session-only overrides of WoW's saved bag bindings. Never save/reassign keys.
local owner=CreateFrame("Frame")
local toggle=CreateFrame("Button","WFStorageInventoryToggle",UIParent)
local updating=false
local actions={"TOGGLEBACKPACK","OPENALLBAGS"}
toggle:RegisterForClicks("AnyUp")
toggle:SetScript("OnClick",function() SlashCmdList.WFSTORAGE() end)
function ns.UpdateInventoryBinding()
    if updating then return end
    local combat,status=ns.Read(InCombatLockdown)
    if status~="ok" or combat then return end -- Retry from PLAYER_REGEN_ENABLED.
    if type(ClearOverrideBindings)~="function" then return end
    updating=true
    local ok=pcall(function()
        ClearOverrideBindings(owner)
        -- Retain the legacy preference key so existing opt-outs are preserved.
        if not ns.db or ns.db.settings.bindB==false or ns.UsesNativeUI() then return end
        if type(GetBindingKey)~="function" or type(SetOverrideBindingClick)~="function" then return end
        local seen={}
        for _,action in ipairs(actions) do
            local keys=ns.Read(function() return {GetBindingKey(action)} end)
            if type(keys)=="table" then
                for i=1,2 do
                    local key=ns.Field(keys,i)
                    if type(key)=="string" and key~="" and not seen[key] then
                        SetOverrideBindingClick(owner,true,key,"WFStorageInventoryToggle","LeftButton")
                        seen[key]=true
                    end
                end
            end
        end
    end)
    if not ok then pcall(ClearOverrideBindings,owner) end
    updating=false
end
ns.On("PLAYER_ENTERING_WORLD",ns.UpdateInventoryBinding)
ns.On("PLAYER_REGEN_ENABLED",ns.UpdateInventoryBinding)
ns.On("UPDATE_BINDINGS",ns.UpdateInventoryBinding)


-- Standalone launcher; collection and saved observations never depend on this UI.
-- Keep its action reusable for a future shared Forever launcher.
function ns.LaunchStorage(mouse)
    if mouse=="RightButton" then SlashCmdList.WFSTORAGE("settings");return end
    if ns.UsesNativeUI() then
        if ns.InteractionReady() and type(ToggleAllBags)=="function" then ToggleAllBags() end
    else SlashCmdList.WFSTORAGE() end
end
local minimapButton
local dragged=false
local function minimapPosition()
    if not minimapButton then return end
    local map=minimapButton:GetParent()
    local angle=ns.db and ns.db.settings.storageMinimapAngle
    if type(angle)~="number" or angle~=angle or math.abs(angle)>100000 then angle=225 end
    local radius=math.min(map:GetWidth(),map:GetHeight())/2+8
    minimapButton:ClearAllPoints()
    minimapButton:SetPoint("CENTER",map,"CENTER",math.cos(math.rad(angle))*radius,math.sin(math.rad(angle))*radius)
end
local function dragMinimap()
    if not ns.db or not minimapButton then return end
    local map=minimapButton:GetParent()
    local x,y=map:GetCenter();local cx,cy=GetCursorPosition();local scale=map:GetEffectiveScale()
    if not x or not y or not cx or not cy or not scale or scale<=0 then return end
    local dx,dy=cx/scale-x,cy/scale-y
    if dx==0 and dy==0 then return end
    ns.db.settings.storageMinimapAngle=math.deg(math.atan2(dy,dx))%360
    minimapPosition()
end
function ns.RefreshMinimapButton()
    if not ns.db then return end
    if not minimapButton then
        local map=Minimap or (MinimapCluster and MinimapCluster.MinimapContainer and MinimapCluster.MinimapContainer.Minimap)
        if not map or type(map.GetCenter)~="function" then return end
        minimapButton=CreateFrame("Button",nil,map)
        ns.minimapButton=minimapButton
        minimapButton:SetSize(32,32);minimapButton:SetFrameStrata("MEDIUM")
        minimapButton:EnableMouse(true);minimapButton:RegisterForClicks("LeftButtonUp","RightButtonUp")
        minimapButton:RegisterForDrag("LeftButton")
        local icon=minimapButton:CreateTexture(nil,"ARTWORK")
        icon:SetTexture("Interface\\AddOns\\WFStorage\\branding\\forever-storage-icon");icon:SetSize(20,20);icon:SetPoint("CENTER")
        local rim=minimapButton:CreateTexture(nil,"OVERLAY")
        rim:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder");rim:SetSize(54,54);rim:SetPoint("TOPLEFT")
        minimapButton:SetScript("OnMouseDown",function() dragged=false end)
        minimapButton:SetScript("OnClick",function(_,mouse) if not dragged then ns.LaunchStorage(mouse) end end)
        minimapButton:SetScript("OnDragStart",function()
            dragged=true
            if GameTooltip then GameTooltip:Hide() end
            minimapButton:SetScript("OnUpdate",dragMinimap);dragMinimap()
        end)
        minimapButton:SetScript("OnDragStop",function() minimapButton:SetScript("OnUpdate",nil) end)
        minimapButton:SetScript("OnHide",function() minimapButton:SetScript("OnUpdate",nil) end)
        ns.SetTooltip(minimapButton,"Forever Storage\nLeft-click: bags\nRight-click: settings\nDrag to move")
        map:HookScript("OnSizeChanged",minimapPosition)
    end
    minimapPosition()
    if ns.db.settings.showMinimapButton==false then minimapButton:Hide() else minimapButton:Show() end
end
ns.On("PLAYER_ENTERING_WORLD",ns.RefreshMinimapButton)
