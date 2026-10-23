-- SPDX-License-Identifier: GPL-3.0-only
local _, ns = ...
local core=ns.core
local opening=false
local function nth(fn,index,...)
    if type(fn)~="function" then return nil,"unavailable" end
    local args={...}
    return core.Read(function() return select(index,fn(unpack(args))) end)
end
-- Explicit hardware-click entry point only. Never called by events or Refresh.
-- The installed 70532 bootstrap implements this helper; no spell IDs or casts.
function ns.OpenProfession(owner,skillLineID)
    if opening then return false,"Opening already in progress" end
    if not core.inWorld or not core.character or not owner or owner~=core.owner then
        return false,"Select your current character to open a profession"
    end
    if skillLineID~=197 and skillLineID~=185 then return false,"Select Tailoring or Cooking" end
    local version=core.Read(GetBuildInfo)
    local build=nth(GetBuildInfo,2)
    local interface=nth(GetBuildInfo,4)
    if version~="1.60.1" or build~="70532" or interface~=16001 then
        return false,"Profession opening unavailable on this build"
    end
    local combat,state=core.Read(InCombatLockdown)
    if state~="ok" or combat~=false then return false,"Cannot open: combat or unknown state" end
    if type(GetProfessions)~="function" or type(GetProfessionInfo)~="function"
        or type(OpenProfessionUIToSkillLine)~="function" then
        return false,"Profession opening API unavailable; use the game window"
    end
    -- Resolve ownership from current client data, never a cached name or spell.
    local matches=0
    for slot=1,5 do
        local index,status=nth(GetProfessions,slot)
        if status=="ok" and core.Integer(index,1,10000) then
            local id,idStatus=nth(GetProfessionInfo,7,index)
            if idStatus~="ok" or not core.Integer(id,1,10000) then
                return false,"Current profession identity unavailable"
            end
            if id==skillLineID then matches=matches+1 end
        elseif status~="unknown" then
            return false,"Current professions unavailable; previous data retained"
        end
    end
    if matches~=1 then return false,"Selected profession not established on this character" end
    combat,state=core.Read(InCombatLockdown)
    if owner~=core.owner or not core.inWorld or not core.character or state~="ok" or combat~=false then
        return false,"Opening cancelled; character or combat state changed"
    end
    opening=true
    ns.BeginNativeOpening()
    local ok=pcall(OpenProfessionUIToSkillLine,skillLineID)
    opening=false
    ns.EndNativeOpening(ok)
    if not ok then return false,"Game declined opening; use the native profession window" end
    if owner~=core.owner or not core.inWorld then return false,"Character changed while opening" end
    -- The native helper returns nothing. Do not equate pcall success with ready
    -- recipe data. Refresh retains its own stronger source/event/list guards.
    local ready,readyStatus=core.Read(function()
        local info=C_TradeSkillUI.GetBaseProfessionInfo()
        local id,status=core.Field(info,"professionID")
        return status=="ok" and id==skillLineID and ProfessionsFrame.CraftingPage:IsShown()==true
    end)
    if readyStatus=="ok" and ready==true then return true,"Profession open; click Refresh when ready" end
    return false,"Open requested; check the game's recipe window"
end
