-- SPDX-License-Identifier: GPL-3.0-only
local _,ns=...
local core=ns.core
local modes={Alongside=true,Custom=true,["Native UI"]=true}
local hiding=false
local nativeForRefresh=false
local function shown(frame)
    local value,status=core.Read(function() return frame:IsShown() end)
    return status=="ok" and value==true
end
local function frames()
    local result={}
    for _,name in ipairs({"ProfessionsFrame","ProfessionsBookFrame"}) do
        local frame,status=core.Field(_G,name)
        if status=="ok" and type(frame)=="table" then result[#result+1]=frame end
    end
    return result
end
local function safeToClose()
    local version=core.Read(GetBuildInfo)
    local build=core.Read(function() return select(2,GetBuildInfo()) end)
    local interface=core.Read(function() return select(4,GetBuildInfo()) end)
    if version~="1.60.1" or build~="70532" or interface~=16001 then return false end
    local combat,status=core.Read(InCombatLockdown)
    return status=="ok" and combat==false and type(HideUIPanel)=="function"
end
function ns.PresentationMode()
    local value=ns.store and ns.store.settings and ns.store.settings.presentation
    return modes[value] and value or "Alongside"
end
local function closeNative()
    if not safeToClose() then return false end
    hiding=true
    local ok=true
    for _,frame in ipairs(frames()) do
        if shown(frame) then
            if not pcall(HideUIPanel,frame) or shown(frame) then ok=false end
        end
    end
    hiding=false
    return ok
end
function ns.SetPresentationMode(mode)
    if not modes[mode] or not ns.store then return false end
    -- A mode switch never opens a profession or captures anything. Native hides
    -- execute their original handlers (including CloseTradeSkill), not bypasses.
    if mode=="Custom" and not closeNative() then
        ns.presentationNotice="Cannot hide native UI now; mode unchanged"
        ns.Refresh(); return false
    end
    nativeForRefresh=false
    ns.store.settings.presentation=mode
    ns.presentationNotice=nil
    if mode=="Native UI" then ns.window:Hide() else ns.window:Show() end
    ns.Refresh(); return true
end
function ns.BeginNativeOpening()
    -- Explicit Open profession temporarily retains the native recipe page.
    nativeForRefresh=ns.PresentationMode()=="Custom"
    ns.presentationNotice=nil
end
function ns.NativePresentationShown(frame)
    if not core.inWorld or hiding or (frame and not shown(frame)) then return end
    local mode=ns.PresentationMode()
    if mode=="Native UI" then ns.window:Hide(); return end
    if mode=="Custom" and not nativeForRefresh then
        local was=ns.window:IsShown()
        if closeNative() then
            ns.presentationNotice=nil
            -- The remapped profession key toggles the cached journal by opening
            -- the native window. Hiding it closes native data; Refresh must refuse.
            if was then ns.window:Hide() else ns.window:Show() end
        else
            ns.presentationNotice="Native UI retained; Custom unavailable now"
            ns.window:Show()
        end
    else ns.window:Show() end
    ns.Refresh()
end
function ns.NativePresentationHidden()
    if hiding then return end
    for _,frame in ipairs(frames()) do if shown(frame) then return end end
    nativeForRefresh=false
    ns.window:Hide()
end

function ns.EndNativeOpening(ok)
    if not ok then nativeForRefresh=false end
end
core.On("PLAYER_LEAVING_WORLD",function() nativeForRefresh=false end)
