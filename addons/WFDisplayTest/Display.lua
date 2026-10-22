local _, ns = ...
-- Original display-only experiment for Forever build 70532. No saved variables,
-- raw value comparisons, serialization, casting, targeting or input automation.
local panel, health, mana, buffs
local spells = {}
local pending = false
local function label(parent, text, x, y)
    local font = parent:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    font:SetPoint("TOPLEFT", parent, "TOPLEFT", x, y)
    font:SetText(text)
    return font
end
local function message(text)
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("Forever Display Test: " .. text) end
end
local function bar(parent, title, y, r, g, b)
    label(parent, title, 12, y)
    local widget = CreateFrame("StatusBar", nil, parent)
    widget:SetPoint("TOPLEFT", parent, "TOPLEFT", 12, y - 17)
    widget:SetSize(280, 20)
    widget:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar")
    widget:SetStatusBarColor(r, g, b)
    local bg = widget:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints(); bg:SetColorTexture(0.12, 0.12, 0.12, 1)
    local text = widget:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    text:SetPoint("CENTER")
    return {frame=widget, text=text, status=label(parent, "Awaiting sample", 12, y - 40)}
end
local function updateBar(display, currentAPI, maxAPI, ...)
    local ok = pcall(function(...)
        local current = currentAPI(...)
        local maximum = maxAPI(...)
        -- Pass directly to native consumers. Never format or inspect secret numbers in Lua.
        display.frame:SetMinMaxValues(0, maximum)
        display.frame:SetValue(current)
        display.text:SetFormattedText("%d / %d", current, maximum)
    end, ...)
    display.status:SetText(ok and "Native display calls accepted" or "Display unavailable")
    if not ok then
        pcall(display.frame.SetValue, display.frame, 0)
        pcall(display.text.SetText, display.text, "Unavailable")
    end
end
local function update()
    if not panel then return end
    updateBar(health, UnitHealth, UnitHealthMax, "player")
    updateBar(mana, UnitPower, UnitPowerMax, "player", 0)
    for _, spell in ipairs(spells) do
        local ok = pcall(function()
            local duration = C_Spell.GetSpellCooldownDuration(spell.id)
            spell.cooldown:SetCooldownFromDurationObject(duration)
        end)
        spell.status:SetText(ok and "Native timer" or "Timer unavailable")
        if not ok then pcall(spell.cooldown.Clear, spell.cooldown) end
    end
end
local function createBuffs()
    local ok = pcall(function()
        buffs = CreateFrame("AuraContainer", nil, panel, "CustomAuraContainerTemplate")
        buffs:Hide()
        buffs:SetPoint("TOPLEFT", panel, "TOPLEFT", 12, -310)
        buffs:SetSize(280, 72)
        buffs:SetUnit("player")
        buffs:AddAuraGroup("playerHelpful", "HELPFUL", {
            maxFrameCount=8,
            layout={elementWidth=30, elementHeight=30, elementSpacing=4, lineSpacing=4},
            initializeFrame=function(button)
                -- Layout dimensions reserve space but do not resize the AuraButton.
                -- Size it before its anchored icon/cooldown and before access restrictions apply.
                button:SetSize(30, 30)
                local icon = button:CreateTexture(nil, "BACKGROUND")
                icon:SetAllPoints(button)
                button:SetIcon(icon)
                local cooldown = CreateFrame("Cooldown", nil, button, "CooldownFrameTemplate")
                cooldown:SetAllPoints(button)
                cooldown:SetHideCountdownNumbers(false)
                -- Use Blizzard's small white UI font only for the 30px buff icons.
                cooldown:SetCountdownFont("GameFontHighlightSmall")
                button:SetDurationCooldown(cooldown)
            end,
        })
        buffs:Show()
    end)
    if not ok and buffs then pcall(buffs.Hide, buffs) end
    label(panel, ok and "Native buff container configured" or "Buff container unavailable", 12, -390)
end
local function build()
    if panel then return end
    if InCombatLockdown() then return end
    panel = CreateFrame("Frame", nil, UIParent)
    panel:SetSize(310, 420)
    panel:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 30, -220)
    local bg = panel:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints(); bg:SetColorTexture(0.025, 0.035, 0.055, 0.9)
    label(panel, "FOREVER - DISPLAY TEST", 12, -12)
    label(panel, "Read-only / no saved settings", 12, -30)
    health = bar(panel, "Your HP", -52, 0.2, 0.8, 0.35)
    mana = bar(panel, "Your mana", -116, 0.2, 0.45, 1)
    for index, spec in ipairs({{20154, "Seal"}, {20594, "Stoneform"}}) do
        local x = 12 + (index - 1) * 145
        label(panel, spec[2], x, -180)
        local holder = CreateFrame("Frame", nil, panel)
        holder:SetSize(44, 44); holder:SetPoint("TOPLEFT", panel, "TOPLEFT", x, -200)
        local icon = holder:CreateTexture(nil, "BACKGROUND"); icon:SetAllPoints()
        pcall(function() icon:SetTexture(C_Spell.GetSpellTexture(spec[1])) end)
        local cd = CreateFrame("Cooldown", nil, holder, "CooldownFrameTemplate")
        cd:SetAllPoints(holder); cd:SetHideCountdownNumbers(false)
        spells[#spells+1]={id=spec[1], cooldown=cd, status=label(panel, "Awaiting timer", x, -250)}
    end
    label(panel, "Player buffs - managed by Blizzard", 12, -285)
    createBuffs()
    update()
    message("loaded. Native displays need visual confirmation; nothing is saved.")
end
local events = CreateFrame("Frame")
for _, event in ipairs({"PLAYER_LOGIN", "PLAYER_ENTERING_WORLD", "PLAYER_REGEN_ENABLED",
    "UNIT_HEALTH", "UNIT_MAXHEALTH", "UNIT_POWER_UPDATE", "UNIT_MAXPOWER", "SPELL_UPDATE_COOLDOWN"}) do
    pcall(events.RegisterEvent, events, event)
end
events:SetScript("OnEvent", function()
    -- Coalesce events without per-frame polling. Ignore unit payloads, which may be restricted.
    if pending then return end
    pending = true
    C_Timer.After(0.1, function()
        pending = false
        local ok = pcall(function() if not panel then build() else update() end end)
        if not ok then message("display update unavailable; no game data was recorded.") end
    end)
end)
