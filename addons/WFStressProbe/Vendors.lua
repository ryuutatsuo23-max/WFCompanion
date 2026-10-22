local _,ns=...
-- Passive merchant listings only. Never buy, sell, repair, select or change filters.
local opened,pending,generation,interrupt=false,false,0,nil
local summary="[Vendor items]\nNot tested - open a vendor."
function ns.VendorReport() return summary end
local function read(fn,n,...)
    if type(fn)~="function" then return "Missing API" end
    local args={...}
    return ns.Read(function() return select(n,fn(unpack(args))) end)
end
local function token(s,v) return s=="OK" and tostring(v) or s end
local function value(fn,n,...) return token(read(fn,n,...)) end
local function copper(status,amount)
    return status=="OK" and type(amount)=="number" and amount>=0
        and amount<=9007199254740991 and amount==math.floor(amount)
end
local function scan()
    pending=false
    if not opened then return end
    if interrupt then interrupt("Partial - merchant list changed") end
    generation=generation+1
    local own=generation
    local npc=value(UnitName,1,"npc")
    local header="[Vendor items - revision 2]\nNPC: "..npc.."\nCapture time (client local): "
        ..value(date,1,"%Y-%m-%d %H:%M:%S")
        .."\nQuoted copper price is per purchase bundle, not per individual item. Stock -1 means unlimited."
        .."\nEnough money checks copper only, not extra costs or purchase eligibility; observations are sequential. Raw canAfford is unchanged."
        .."\nObserved listings only; filters unchanged. Detailed reputation/quest/level gates are Unknown unless separately reported."
    local pages,lines,bytes,index={}, {},0,1
    local function emit(s) lines[#lines+1]=s; bytes=bytes+#s+1 end
    local function page()
        if #lines>0 then pages[#pages+1]=table.concat(lines,"\n") end
        lines,bytes={},0
    end
    local function finish(state)
        interrupt=nil; page()
        summary=header.."\nCoverage: "..state.."\nVendor pages saved: "..#pages
        if ns.SaveVendorPages then ns.SaveVendorPages(npc,header,state,pages) end
        if ns.Capture then ns.Capture("Vendor item sample") end
    end
    interrupt=finish
    local s,count=read(GetMerchantNumItems,1)
    if s~="OK" or type(count)~="number" or count<0 or count~=math.floor(count) then finish("Unknown - item count "..s); return end
    local fields={{"name",1},{"price",3},{"stackCount",4},{"numAvailable",5},{"isPurchasable",6},{"isUsable",7},{"hasExtendedCost",8},{"currencyID",9}}
    local function step()
        if not opened or own~=generation then return end
        for _=1,8 do
            if index>count then finish("All "..count.." returned listings attempted; Unknown fields remain unresolved"); return end
            if bytes>=6000 then page() end
            if index>2000 or #pages>=40 then finish("Partial - safety limit"); return end
            emit("Listing "..index.." itemID="..value(GetMerchantItemID,1,index))
            local modern=C_MerchantFrame and C_MerchantFrame.GetItemInfo
            local beforeStatus,beforeMoney=read(GetMoney,1)
            local rs,info=ns.ReadRecord(modern,index)
            local priceStatus,price="Unknown (nil)",nil
            for _,f in ipairs(fields) do
                local fs,fv
                if type(modern)=="function" then
                    if rs=="OK" then fs,fv=ns.ReadField(info,f[1]) else fs=rs end
                else fs,fv=read(GetMerchantItemInfo,f[2],index) end
                if f[1]=="price" then priceStatus,price=fs,fv end
                emit("  "..f[1].."="..token(fs,fv))
            end
            local moneyStatus,money=read(GetMoney,1)
            local enough="Unknown (money or price unavailable/invalid)"
            if copper(moneyStatus,money) and copper(beforeStatus,beforeMoney) and copper(priceStatus,price) then
                if money~=beforeMoney then enough="Unknown (money changed during observation)"
                else enough=money>=price and "Yes" or "No" end
            end
            emit("  moneyCopper="..token(moneyStatus,money))
            emit("  Enough money for one bundle="..enough)
            emit("  canAfford="..value(CanAffordMerchantItem,1,index))
            local cs,costs=read(GetMerchantItemCostInfo,1,index)
            if cs=="OK" and type(costs)=="number" and costs>=0 and costs==math.floor(costs) then
                emit("  extendedCostCount="..costs)
                for c=1,math.min(costs,16) do
                    local ls,link=read(GetMerchantItemCostItem,3,index,c)
                    local kind,id="Unknown","Unknown"
                    if ls=="OK" and type(link)=="string" then
                        id=link:match("item:(%d+)"); kind="item"
                        if not id then id=link:match("currency:(%d+)"); kind="currency" end
                        if not id then kind,id="Unknown","Unknown" end
                    elseif ls~="OK" then id=ls end
                    emit("    costType="..kind.." id="..id.." quantity="..value(GetMerchantItemCostItem,2,index,c)
                        .." currencyName="..value(GetMerchantItemCostItem,4,index,c))
                end
                if costs>16 then emit("  Partial - extended cost limit") end
            else emit("  extendedCostCount="..cs) end
            index=index+1
        end
        summary=header.."\nCoverage: Partial - scan in progress"
        if C_Timer and type(C_Timer.After)=="function" then
            C_Timer.After(0.05,function() local ok=pcall(step); if not ok then finish("Partial - API error; raw payload omitted") end end)
        else finish("Partial - timer unavailable") end
    end
    step()
end
local frame=CreateFrame("Frame")
for _,event in ipairs({"MERCHANT_SHOW","MERCHANT_UPDATE","MERCHANT_CLOSED","PLAYER_LEAVING_WORLD"}) do pcall(frame.RegisterEvent,frame,event) end
frame:SetScript("OnEvent",function(_,event)
    if event=="MERCHANT_CLOSED" or event=="PLAYER_LEAVING_WORLD" then
        opened=false; generation=generation+1
        if interrupt then pcall(interrupt,"Partial - vendor closed before completion") end
        return
    end
    if event=="MERCHANT_SHOW" then opened=true end
    if not opened or pending then return end
    pending=true
    local function guarded()
        local ok=pcall(scan)
        if not ok then pending=false; summary="[Vendor items]\nAPI error - raw payload omitted." end
    end
    if C_Timer and type(C_Timer.After)=="function" then C_Timer.After(0.15,guarded) else guarded() end
end)
