local _, ns = ...
local report = ns.report
local window, output, spellInput

local function say(message)
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("WF Probe: " .. message) end
end

local function refresh()
    if output then output:SetText(report); output:SetCursorPosition(0); output:ClearFocus() end
end

local function run()
    local spellID, problem = ns.ParseSpell(spellInput:GetText())
    if problem then say(problem); return end
    local ok, result = pcall(ns.Capture, "Manual sample", spellID)
    report = ok and result or "Probe stopped after an internal error. No raw game values or error payload were exported."
    refresh()
end

local function show()
    if window then window:Show(); return end
    window = CreateFrame("Frame", nil, UIParent, "BackdropTemplate")
    local width = math.max(400, math.min(760, UIParent:GetWidth() - 40))
    local height = math.max(300, math.min(560, UIParent:GetHeight() - 40))
    window:SetSize(width, height)
    window:SetPoint("CENTER")
    window:SetFrameStrata("DIALOG")
    window:SetClampedToScreen(true)
    window:SetMovable(true); window:EnableMouse(true); window:RegisterForDrag("LeftButton")
    window:SetScript("OnDragStart", window.StartMoving)
    window:SetScript("OnDragStop", window.StopMovingOrSizing)
    window:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background", edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 24, insets = { left = 6, right = 6, top = 6, bottom = 6 } })
    local title = window:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    title:SetPoint("TOP", 0, -18); title:SetText("Forever - API capability probe")
    local close = CreateFrame("Button", nil, window, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -3, -3)
    close:SetScript("OnClick", function() window:Hide() end)
    local help = window:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    help:SetPoint("TOPLEFT", 18, -48); help:SetPoint("TOPRIGHT", -18, -48)
    help:SetJustifyH("LEFT"); help:SetText("Automatic reports are running. Type /reload to save. Spell ID and Run checks are optional.")
    local label = window:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    label:SetPoint("TOPLEFT", 18, -82); label:SetText("Spell ID")
    spellInput = CreateFrame("EditBox", nil, window, "InputBoxTemplate")
    spellInput:SetSize(110, 24); spellInput:SetPoint("LEFT", label, "RIGHT", 12, 0)
    spellInput:SetAutoFocus(false); spellInput:SetMaxLetters(10)
    spellInput:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    spellInput:SetScript("OnEnterPressed", function(self) self:ClearFocus(); run() end)
    local runButton = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
    runButton:SetSize(100, 26); runButton:SetPoint("LEFT", spellInput, "RIGHT", 12, 0)
    runButton:SetText("Run checks"); runButton:SetScript("OnClick", run)
    local scroll = CreateFrame("ScrollFrame", nil, window, "UIPanelScrollFrameTemplate")
    scroll:SetPoint("TOPLEFT", 18, -115); scroll:SetPoint("BOTTOMRIGHT", -36, 55)
    output = CreateFrame("EditBox", nil, scroll)
    output:SetMultiLine(true); output:SetAutoFocus(false); output:SetFontObject(ChatFontNormal)
    output:SetWidth(width - 60)
    output:SetScript("OnEscapePressed", function(self) self:ClearFocus(); window:Hide() end)
    -- Keep the report immutable while allowing selection and Ctrl+C.
    output:SetScript("OnTextChanged", function(self, userInput)
        if userInput then self:SetText(report) end
    end)
    scroll:SetScrollChild(output)
    local copy = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
    copy:SetSize(170, 26); copy:SetPoint("BOTTOMLEFT", 18, 17); copy:SetText("Select report (Ctrl+C)")
    copy:SetScript("OnClick", function() output:SetFocus(); output:HighlightText() end)
    local note = window:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    note:SetPoint("LEFT", copy, "RIGHT", 12, 0); note:SetPoint("RIGHT", window, "RIGHT", -18, 0)
    note:SetJustifyH("LEFT"); note:SetText("/reload saves locally. Copying is optional.")
    refresh()
end

ns.OnSnapshot = function()
    if output and output:HasFocus() then return end
    report = ns.report; refresh()
end

-- Slash registration and the declared SavedVariables are our only global names.
SLASH_WFSTRESSPROBE1 = "/wfprobe"
SlashCmdList.WFSTRESSPROBE = function(message)
    local ok = pcall(function()
        show()
        if message and not message:match("^%s*$") then
            local spellID, problem = ns.ParseSpell(message)
            if problem then say(problem); return end
            spellInput:SetText(tostring(spellID)); run()
        end
    end)
    if not ok then say("Could not open the probe window. No game actions were performed.") end
end
