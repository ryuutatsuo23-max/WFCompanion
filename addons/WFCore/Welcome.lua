local _, ns = ...
-- Core onboarding only: no inventory UI, bindings, collection or reload action.
local window, remember, attempted
local function settings()
    local db=ns.db
    if type(db)=="table" and type(db.settings)=="table" then return db.settings end
end
local function dismiss()
    local saved=settings()
    local checked=remember and remember:GetChecked()==true
    if saved and (checked or saved.coreWelcomeDismissed==true) then
        saved.coreWelcomeDismissed=checked
    end
    -- Unsupported saves remain untouched; dismissal still works for this UI load.
    if window then window:Hide() end
end
local function show()
    if not window then
        local panel=CreateFrame("Frame",nil,UIParent,"BackdropTemplate")
        panel:Hide()
        panel:SetSize(400,244)
        panel:SetPoint("TOP",UIParent,"TOP",0,-110)
        panel:SetFrameStrata("DIALOG")
        panel:SetBackdrop({bgFile="Interface\\Buttons\\WHITE8X8",
            edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1})
        panel:SetBackdropColor(0.06,0.07,0.09,0.98)
        panel:SetBackdropBorderColor(0.45,0.48,0.55,1)
        local title=panel:CreateFontString(nil,"OVERLAY","GameFontNormalLarge")
        title:SetPoint("TOPLEFT",panel,"TOPLEFT",18,-18)
        title:SetText("Welcome to WoW Forever!")
        local body=panel:CreateFontString(nil,"OVERLAY","GameFontHighlight")
        body:SetPoint("TOPLEFT",panel,"TOPLEFT",18,-46)
        body:SetWidth(364)
        body:SetJustifyH("LEFT")
        body:SetText("To refresh your saved character data in WF Companion, type /reload. "
            .."Logging out or exiting normally also saves your data. "
            .."Once connected, WF Companion shows your latest saved information.")
        local hint=panel:CreateFontString(nil,"OVERLAY","GameFontDisableSmall")
        hint:SetPoint("BOTTOM",panel,"BOTTOM",0,52)
        hint:SetText("Show again: /wfcore welcome")
        remember=CreateFrame("CheckButton",nil,panel,"UICheckButtonTemplate")
        remember:SetSize(26,26)
        remember:SetPoint("BOTTOMLEFT",panel,"BOTTOMLEFT",18,76)
        local label=remember:CreateFontString(nil,"OVERLAY","GameFontHighlight")
        label:SetPoint("LEFT",remember,"RIGHT",4,0)
        label:SetText("Don't show again")
        local button=CreateFrame("Button",nil,panel,"UIPanelButtonTemplate")
        button:SetSize(112,26)
        button:SetPoint("BOTTOM",panel,"BOTTOM",0,16)
        button:SetText("Dismiss")
        button:SetScript("OnClick",dismiss)
        window=panel
    end
    local saved=settings()
    remember:SetChecked(saved and saved.coreWelcomeDismissed==true or false)
    window:Show()
end
ns.On("PLAYER_ENTERING_WORLD",function()
    if attempted then return end
    attempted=true
    local saved=settings()
    if not saved or saved.coreWelcomeDismissed~=true then show() end
end)
-- Use a Core-specific registry key: Storage retains WFCORE as a legacy handler.
-- The public command stays /wfcore; never replace Storage commands or bindings.
SLASH_WFCOREWELCOME1="/wfcore"
SlashCmdList.WFCOREWELCOME=function(message)
    if type(message)=="string" and message:lower():match("^%s*welcome%s*$") then
        show()
    elseif DEFAULT_CHAT_FRAME then
        DEFAULT_CHAT_FRAME:AddMessage("Forever Core: /wfcore welcome shows the saved-data welcome.")
    end
end
