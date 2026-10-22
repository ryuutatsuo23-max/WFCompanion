local _, ns = ...
-- Session-only override. Never rewrite the user's saved keybinding set.
local owner=CreateFrame("Frame")
local toggle=CreateFrame("Button","WFStorageInventoryToggle",UIParent)
toggle:RegisterForClicks("AnyUp")
toggle:SetScript("OnClick",function() SlashCmdList.WFSTORAGE() end)
function ns.UpdateInventoryBinding()
    local combat,status=ns.Read(InCombatLockdown)
    if status~="ok" or combat then return end
    if type(ClearOverrideBindings)~="function" or type(SetOverrideBindingClick)~="function" then
        ns.notice="B shortcut unavailable; use /wf"; return
    end
    ClearOverrideBindings(owner)
    if ns.db and ns.db.settings.bindB~=false then
        SetOverrideBindingClick(owner,true,"B","WFStorageInventoryToggle","LeftButton")
    end
end
ns.On("PLAYER_ENTERING_WORLD",ns.UpdateInventoryBinding)
ns.On("PLAYER_REGEN_ENABLED",ns.UpdateInventoryBinding)
