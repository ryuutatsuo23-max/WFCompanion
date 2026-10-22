local _, ns = ...
-- Independent presentation preferences. Never migrate or rewrite observations.
ns.ViewChoices = {
    view={"Grid","List"}, theme={"Slate","Warm","Midnight"}, opacity={0.85,0.95,1},
    iconSize={32,40,48}, columns={6,8,10}, order={"Slots","Name","Count","Category"}, category={"All","Equipment","Materials","Consumables","Other","Unknown"},
    windowScale={0.85,1,1.15}, fontSize={12,14,16},
}
local defaults={view="Grid",theme="Slate",opacity=0.95,iconSize=40,columns=8,
    category="All",order="Slots",windowScale=1,fontSize=14}
ns.OptionHelp={category="Filter both inventory windows by item category. Missing metadata stays Unknown.",
    favoritesFirst="Show favorites first within the selected display order. Never moves items.",view="Choose an icon grid or a named item list.",theme="Choose the window colors.",
    opacity="Change the background opacity; item icons stay opaque.",iconSize="Size of inventory grid icons.",
    columns="Number of icons in each grid row.",fontSize="Size of item labels and counts.",
    windowScale="Scale the whole window; limited to fit your screen.",order="Display order only; does not move items.",
    showUnknown="Show unresolved slot observations for diagnostics.",showDetails="Show scan coverage details.",
    dimPoor="Dim poor-quality icons. This does not sell anything.",lockWindow="Prevent dragging inventory windows.",
    bindB="Use B to toggle Forever inventory. Your saved keybindings are preserved.",
    nativeUI="Show or hide native bags and bank for purchases, trading and special actions."}
function ns.SetTooltip(frame,message)
    frame:SetScript("OnEnter",function()
        if GameTooltip then GameTooltip:SetOwner(frame,"ANCHOR_RIGHT"); GameTooltip:SetText(message); GameTooltip:Show() end
    end)
    frame:SetScript("OnLeave",function() if GameTooltip then GameTooltip:Hide() end end)
end
function ns.SetViewOption(key,value)
    if not ns.db then return end
    if key=="opacity" or key=="windowScale" then
        local low,high=key=="opacity" and 0.5 or 0.7,key=="opacity" and 1 or 1.3
        if type(value)~="number" or value~=value or value<low or value>high then return end
    elseif ns.ViewChoices[key] then
        local found=false; for _,v in ipairs(ns.ViewChoices[key]) do if v==value then found=true end end
        if not found then return end
    elseif type(ns.ViewOptions()[key])~="boolean" or type(value)~="boolean" then return end
    ns.db.settings[key]=value
    if key=="bindB" and ns.UpdateInventoryBinding then ns.UpdateInventoryBinding() end
    ns.RefreshUI()
end
ns.Themes={
    Slate={bg={0.055,0.075,0.10},accent={0.40,0.75,0.90},text={0.91,0.94,0.97}},
    Warm={bg={0.10,0.075,0.05},accent={0.94,0.73,0.38},text={0.97,0.93,0.85}},
    Midnight={bg={0.035,0.035,0.055},accent={0.70,0.58,0.94},text={0.93,0.91,0.98}},
}
function ns.ViewOptions()
    local saved=ns.db and ns.db.settings or {}
    local result={}
    for key,values in pairs(ns.ViewChoices) do
        result[key]=defaults[key]
        for _,value in ipairs(values) do if saved[key]==value then result[key]=value end end
    end
    if saved.fontSize==nil and saved.largeText==true then result.fontSize=16 end
    for _,key in ipairs({"opacity","windowScale"}) do
        local low,high=key=="opacity" and 0.5 or 0.7,key=="opacity" and 1 or 1.3
        if type(saved[key])=="number" and saved[key]>=low and saved[key]<=high then result[key]=saved[key] end
    end
    for _,key in ipairs({"showUnknown","showDetails","lockWindow","dimPoor","favoritesFirst"}) do result[key]=saved[key]==true end
    result.bindB=saved.bindB~=false
    return result
end
function ns.CycleViewOption(key)
    if not ns.db then return end
    local values=ns.ViewChoices[key]
    local current=ns.ViewOptions()[key]
    if values then
        for i,value in ipairs(values) do
            if value==current then ns.db.settings[key]=values[i % #values+1]; return end
        end
    elseif key=="showUnknown" or key=="showDetails" or key=="lockWindow" or key=="dimPoor" or key=="bindB" then
        ns.db.settings[key]=not current
    end
end
function ns.InventoryLayout(options,count)
    local grid=options.view=="Grid"
    local columns=grid and options.columns or 1
    local capacity=grid and columns*4 or 10
    local step=grid and options.iconSize+8 or math.max(30,options.fontSize+14)
    local width=grid and math.max(480,32+columns*step) or 540
    local visible=math.min(count,capacity)
    local lines=grid and math.max(1,math.ceil(visible/columns)) or math.max(1,visible)
    local top=options.showDetails and 190 or 154
    return {width=width,height=top+lines*step+82,top=top,step=step,columns=columns,
        capacity=capacity,grid=grid,bottom=top+lines*step+8}
end
function ns.SortInventory(rows,order)
    -- Stable tie-break by original location/slot order; this moves no game items.
    for i,row in ipairs(rows) do row.ordinal=i end
    local favoritesFirst=ns.ViewOptions().favoritesFirst
    if order=="Slots" and not favoritesFirst then return end
    table.sort(rows,function(a,b)
        if favoritesFirst and a.favorite~=b.favorite then return a.favorite==true end
        if order=="Category" and a.category~=b.category then return (a.category or "Unknown")<(b.category or "Unknown") end
        if order=="Name" and a.name:lower()~=b.name:lower() then return a.name:lower()<b.name:lower() end
        if order=="Count" and (a.item.count or -1)~=(b.item.count or -1) then return (a.item.count or -1)>(b.item.count or -1) end
        return a.ordinal<b.ordinal
    end)
end

-- Do not use UISpecialFrames: this client closes those during NPC interactions.
-- Keyboard propagation keeps ordinary keys available to the game.
function ns.EnableEscapeClose(frame, callback)
    if type(frame.EnableKeyboard)~="function" or type(frame.SetPropagateKeyboardInput)~="function" then return end
    frame:EnableKeyboard(true)
    frame:SetPropagateKeyboardInput(true)
    frame:SetScript("OnKeyDown",function(self,key)
        local combat,status=ns.Read(InCombatLockdown)
        if status=="ok" and not combat then self:SetPropagateKeyboardInput(key~="ESCAPE") end
        if key=="ESCAPE" then callback() end
    end)
end

-- Presentation metadata is never written back into saved observations.
ns.QualityColors={[0]={.45,.45,.45},[1]={.65,.65,.65},[2]={.2,.8,.3},
    [3]={.2,.5,1},[4]={.7,.3,.95},[5]={1,.55,.12},[6]={.9,.8,.5},[7]={.4,.8,1},[8]={.4,.8,1}}
function ns.ItemCategory(item)
    if item.state~="observed" or not item.itemID then return "Unknown" end
    local class=ns.Read(function() return select(6,C_Item.GetItemInfoInstant(item.itemID)) end)
    local classes=Enum and Enum.ItemClass
    if not ns.Integer(class,0,100) or type(classes)~="table" then return "Unknown" end
    if class==classes.Weapon or class==classes.Armor then return "Equipment" end
    if class==classes.Tradegoods or class==classes.Reagent then return "Materials" end
    if class==classes.Consumable then return "Consumables" end
    return "Other"
end
function ns.CapacityText(snapshot)
    if type(snapshot)~="table" then return "capacity unobserved" end
    if snapshot.coverage~="complete" or not ns.Integer(snapshot.expectedSlots,0,100000)
        or not ns.Integer(snapshot.emptySlots,0,snapshot.expectedSlots) then return "capacity incomplete" end
    return snapshot.emptySlots.."/"..snapshot.expectedSlots.." free"
end
