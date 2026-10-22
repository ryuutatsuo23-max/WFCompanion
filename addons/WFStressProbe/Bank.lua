local _, ns = ...
-- Character bank only, while the bank is open. No item movement or UI selection.
local opened, pending, generation, interrupt = false, false, 0, nil
local summary = "[Character bank]\nNot tested - open the bank."
function ns.BankReport() return summary end
local function integer(s,v,low,high)
    return s == "OK" and type(v) == "number" and v >= low and v <= high and v == math.floor(v)
end
local function token(s,v)
    return s == "OK" and tostring(v) or s
end
local function scan()
    pending = false
    if not opened then return end
    if interrupt then interrupt("Partial - bank changed during scan") end
    generation = generation + 1
    local mine = generation
    local containers = C_Container or {}
    local ids, seen, lines, pages, bytes = {}, {}, {}, {}, 0
    local header = "[Character bank - revision 1]\nCapture time (client local): "
        .. token(ns.Read(date,"%Y-%m-%d %H:%M:%S"))
        .. "\nSequential observations, not an atomic total. Nil stays Unknown (empty or inaccessible). Account/guild banks excluded."
    local function emit(text) lines[#lines+1]=text; bytes=bytes+#text+1 end
    local function page()
        if #lines > 0 then pages[#pages+1]=table.concat(lines,"\n") end
        lines,bytes={},0
    end
    local function finish(state)
        interrupt=nil; page()
        summary=header.."\nCoverage: "..state.."\nBank pages saved: "..#pages
        if ns.SaveBankPages then ns.SaveBankPages("Character bank",header,state,pages) end
        if ns.Capture then ns.Capture("Character bank sample") end
    end
    interrupt=finish
    local function add(s,id,label)
        if integer(s,id,-10,100) and not seen[id] then
            seen[id]=true; ids[#ids+1]=id; emit(label.." container="..id)
        elseif s ~= "OK" then emit(label..": "..s) end
    end
    -- Use the client's declarations rather than guessing bank bag offsets.
    local bs,bank=ns.Read(function() return BANK_CONTAINER end)
    add(bs,bank,"Main bank constant")
    for i=1,9 do
        local s,id=ns.Read(function() return Enum.BagIndex["CharacterBankTab_"..i] end)
        add(s,id,"Character bank tab "..i)
    end
    emit("Coverage scope: declared character containers only; unavailable declarations remain Unknown.")
    if #ids == 0 then finish("Unknown - no readable bank container declarations"); return end
    local bagIndex,slot,total,unresolved=1,1,nil,false
    local function step()
        if not opened or mine ~= generation then return end
        for _=1,12 do
            if bytes>=6000 then page() end
            if #pages>=40 then finish("Partial - page safety limit"); return end
            local bag=ids[bagIndex]
            if not bag then finish(unresolved and "Partial - some container slot counts unavailable" or "All slots in declared containers attempted; Unknown rows remain unresolved"); return end
            if total==nil then
                local s,n=ns.Read(containers.GetContainerNumSlots,bag)
                emit("Container "..bag.." slots="..token(s,n))
                if integer(s,n,0,200) then total=n else total=0; unresolved=true end
            end
            if slot>total then bagIndex=bagIndex+1; slot=1; total=nil
            else
                local s,id=ns.Read(containers.GetContainerItemID,bag,slot)
                local rs,item=ns.ReadRecord(containers.GetContainerItemInfo,bag,slot)
                local qs,qty=rs,nil
                if rs=="OK" then
                    qs,qty=ns.ReadField(item,"stackCount")
                    local otherStatus,otherID=ns.ReadField(item,"itemID")
                    if integer(s,id,1,2147483647) and integer(otherStatus,otherID,1,2147483647) and id~=otherID then
                        qs,qty="Unknown (item changed)",nil
                    end
                end
                if not integer(s,id,1,2147483647) then qs,qty="Unknown (item unidentified)",nil end
                if qs=="OK" and not integer(qs,qty,0,2147483647) then qs,qty="Unknown (invalid quantity)",nil end
                emit("Bank "..bag.."/"..slot.." id="..token(s,id).." qty="..token(qs,qty))
                slot=slot+1
            end
        end
        summary=header.."\nCoverage: Partial - scan in progress"
        if C_Timer and type(C_Timer.After)=="function" then
            C_Timer.After(0.1,function()
                local ok=pcall(step)
                if not ok then finish("Partial - API error; raw error not stored") end
            end)
        else finish("Partial - timer unavailable") end
    end
    step()
end
local frame=CreateFrame("Frame")
for _,event in ipairs({"BANKFRAME_OPENED","BANKFRAME_CLOSED","PLAYERBANKSLOTS_CHANGED","PLAYERBANKBAGSLOTS_CHANGED","BAG_UPDATE_DELAYED","PLAYER_LEAVING_WORLD"}) do
    pcall(frame.RegisterEvent,frame,event)
end
frame:SetScript("OnEvent",function(_,event)
    if event=="BANKFRAME_CLOSED" or event=="PLAYER_LEAVING_WORLD" then
        opened=false; generation=generation+1
        if interrupt then pcall(interrupt,"Partial - bank closed before completion") end
        return
    end
    if event=="BANKFRAME_OPENED" then opened=true end
    if not opened or pending then return end
    pending=true
    local function guarded()
        local ok=pcall(scan)
        if not ok then pending=false; summary="[Character bank]\nAPI error - raw error not stored." end
    end
    if C_Timer and type(C_Timer.After)=="function" then C_Timer.After(0.5,guarded) else guarded() end
end)
