local _, ns = ...
-- Forever 16001 legacy list API, matching installed Auctionator's legacy reader.
-- Observe returned lists only. Never query, paginate, bid, buy, post or cancel.
local opened, generation, serial, interrupt = false, 0, 0, nil
local summary = "[Auction listings]\nNot tested - browse an Auction House search."
function ns.AuctionReport() return summary end
local function read(fn, n, ...)
    if type(fn) ~= "function" then return "Missing API" end
    local args = {...}
    return ns.Read(function() return select(n, fn(unpack(args))) end)
end
local function token(s, v) return s == "OK" and tostring(v) or s end
local function value(fn, n, ...) return token(read(fn, n, ...)) end
local function integer(s, v)
    return s == "OK" and type(v) == "number" and v >= 0 and v <= 9007199254740991 and v == math.floor(v)
end
local function capture()
    serial = serial + 1
    local own, index = generation, 1
    local pages, lines, bytes = {}, {}, 0
    local function emit(line) lines[#lines+1] = line; bytes = bytes + #line + 1 end
    local function page()
        if #lines > 0 then pages[#pages+1] = table.concat(lines, "\n") end
        lines, bytes = {}, 0
    end
    local header = "[Auction listings - revision 1]\nAPI: legacy list; capture "..serial
        .."\nClient local time: "..value(date, 1, "%Y-%m-%d %H:%M:%S")
        .."\nServer epoch: "..value(GetServerTime, 1)
        .."\nPrices in copper. Zero buyout means no buyout. No seller identities or item links retained."
        .."\nReturned rows only, not an entire-market guarantee; query/page identity unavailable."
    local s, count = read(GetNumAuctionItems, 1, "list")
    local ts, total = read(GetNumAuctionItems, 2, "list")
    header = header.."\nReturned rows: "..token(s,count).."; reported total: "..token(ts,total)
    local key = "Auction capture "..serial.." "..value(GetTime,1)
    local function finish(state)
        interrupt = nil
        page()
        summary = header.."\nCoverage: "..state
        if ns.SaveAuctionPages then ns.SaveAuctionPages(key,header,state,pages) end
    end
    interrupt = finish
    if not integer(s,count) then finish("Unknown - returned count "..s); return end
    local fields = {{"itemID",17},{"name",1},{"quantity",3},{"quality",4},{"level",6},
        {"minimumBidCopper",8},{"minimumIncrementCopper",9},{"buyoutCopper",10},{"currentBidCopper",11}}
    local function step()
        if not opened or own ~= generation then return end
        local cs, current = read(GetNumAuctionItems,1,"list")
        if not integer(cs,current) or current ~= count then finish("Partial - list count changed"); return end
        for _=1,20 do
            if index > count then
                local state = "All "..count.." returned rows attempted; unavailable fields remain Unknown"
                if integer(ts,total) and total > count then state = "Partial result set - "..count.." of "..total.." rows attempted" end
                finish(state); return
            end
            if index > 500 or #pages >= 40 then finish("Partial - 500 row / 40 page safety limit"); return end
            if bytes >= 6000 then page() end
            emit("Listing "..index.." observedServerEpoch="..value(GetServerTime,1))
            local qs,q = read(GetAuctionItemInfo,3,"list",index)
            local bs,b = read(GetAuctionItemInfo,10,"list",index)
            for _,f in ipairs(fields) do emit("  "..f[1].."="..value(GetAuctionItemInfo,f[2],"list",index)) end
            local unit = "Unknown"
            if integer(qs,q) and q > 0 and integer(bs,b) then
                unit = b > 0 and tostring(b/q) or "Not applicable (no buyout)"
            end
            emit("  derivedUnitBuyoutCopper="..unit)
            emit("  timeLeftBand="..value(GetAuctionItemTimeLeft,1,"list",index))
            index = index + 1
        end
        if C_Timer and type(C_Timer.After)=="function" then
            C_Timer.After(0.05,function()
                if own ~= generation then return end
                local ok = pcall(step)
                if not ok then finish("Partial - API error; payload omitted") end
            end)
        else finish("Partial - timer unavailable") end
    end
    local ok = pcall(step)
    if not ok then finish("Partial - API error; payload omitted") end
end

-- Event payloads pass the same secret/access guards as ordinary API results.
local function modernCapture(kind, payload)
    local api = C_AuctionHouse or {}
    local key, itemID
    if kind == "commodity" then
        local s,v = ns.Read(function() return payload end)
        if not integer(s,v) or v == 0 then return "Unknown - invalid/restricted item ID" end
        key,itemID = v,v
    else
        local s,record = ns.ReadRecord(function() return payload end)
        if s ~= "OK" then return "Unknown - item key "..s end
        key = {}
        for _,field in ipairs({"itemID","itemLevel","itemSuffix","battlePetSpeciesID"}) do
            local fs,v = ns.ReadField(record,field)
            if not integer(fs,v) then return "Unknown - item key field "..field.." "..fs end
            key[field] = v
        end
        itemID = key.itemID
    end
    serial = serial + 1
    local own,index = generation,1
    local countFn = kind == "commodity" and api.GetNumCommoditySearchResults or api.GetNumItemSearchResults
    local infoFn = kind == "commodity" and api.GetCommoditySearchResultInfo or api.GetItemSearchResultInfo
    local fullFn = kind == "commodity" and api.HasFullCommoditySearchResults or api.HasFullItemSearchResults
    local s,count = ns.Read(countFn,key)
    local header = "[Auction listings - revision 2]\nAPI: modern "..kind.." itemID="..itemID
        .."\nClient local time: "..value(date,1,"%Y-%m-%d %H:%M:%S")
        .."\nServer epoch: "..value(GetServerTime,1).."\nReturned rows: "..token(s,count)
        .."\nPrices in copper. Commodity unitPrice is per item; item buyoutAmount is per listing."
    if kind == "item" then header = header.."\nVariant: level="..key.itemLevel.." suffix="..key.itemSuffix.." pet="..key.battlePetSpeciesID end
    local pages,lines,bytes = {},{},0
    local function page()
        if #lines>0 then pages[#pages+1]=table.concat(lines,"\n") end
        lines,bytes={},0
    end
    local function emit(line) lines[#lines+1]=line;bytes=bytes+#line+1 end
    local captureKey = "Modern auction "..serial.." "..value(GetTime,1)
    local function finish(state)
        interrupt=nil;page();summary=header.."\nCoverage: "..state
        if ns.SaveAuctionPages then ns.SaveAuctionPages(captureKey,header,state,pages) end
    end
    interrupt=finish
    if not integer(s,count) then finish("Unknown - count "..s);return end
    local fields = kind == "commodity" and {"itemID","auctionID","quantity","unitPrice","timeLeftSeconds"}
        or {"auctionID","quantity","minBid","bidAmount","buyoutAmount","timeLeft","timeLeftSeconds"}
    local function step()
        if own~=generation then return end
        local cs,current=ns.Read(countFn,key)
        if not integer(cs,current) or current~=count then finish("Partial - result count changed");return end
        for _=1,20 do
            if index>count then
                local fs,full=ns.Read(fullFn,key)
                finish((fs=="OK" and full==true and "All returned rows attempted" or "Partial/Unknown result completeness")
                    .."; hasFullResults="..token(fs,full).."; unavailable fields remain Unknown")
                return
            end
            if index>500 or #pages>=40 then finish("Partial - safety limit");return end
            if bytes>=6000 then page() end
            emit("Listing "..index.." itemID="..itemID.." observedServerEpoch="..value(GetServerTime,1))
            local rs,info=ns.ReadRecord(infoFn,key,index)
            for _,field in ipairs(fields) do
                local fs,v=rs,nil
                if rs=="OK" then fs,v=ns.ReadField(info,field) end
                emit("  "..field.."="..token(fs,v))
            end
            index=index+1
        end
        if C_Timer and type(C_Timer.After)=="function" then
            C_Timer.After(0.05,function()
                if own~=generation then return end
                if not pcall(step) then finish("Partial - API error; payload omitted") end
            end)
        else finish("Partial - timer unavailable") end
    end
    if not pcall(step) then finish("Partial - API error; payload omitted") end
end

local events={"AUCTION_HOUSE_SHOW","AUCTION_ITEM_LIST_UPDATE","AUCTION_HOUSE_CLOSED",
    "COMMODITY_SEARCH_RESULTS_UPDATED","ITEM_SEARCH_RESULTS_UPDATED","ITEM_SEARCH_RESULTS_ADDED",
    "AUCTION_HOUSE_BROWSE_RESULTS_UPDATED","AUCTION_HOUSE_BROWSE_RESULTS_ADDED",
    "AUCTION_HOUSE_NEW_RESULTS_RECEIVED","COMMODITY_SEARCH_RESULTS_RECEIVED",
    "PLAYER_LEAVING_WORLD","PLAYER_LOGOUT"}
local frame=CreateFrame("Frame")
local counts,registration,last={}, {}, "No auction events observed"
for _,event in ipairs(events) do
    registration[event]=pcall(frame.RegisterEvent,frame,event) and "registered" or "unsupported"
end
local function diagnostics()
    local lines={"[Auction event diagnostics - revision 2]", "Last event: "..last,
        "Legacy GetNumAuctionItems: "..type(GetNumAuctionItems),
        "Modern commodity reader: "..type(C_AuctionHouse and C_AuctionHouse.GetCommoditySearchResultInfo),
        "Modern item reader: "..type(C_AuctionHouse and C_AuctionHouse.GetItemSearchResultInfo)}
    for _,event in ipairs(events) do lines[#lines+1]=event.."="..(counts[event] or 0).." ("..registration[event]..")" end
    return table.concat(lines,"\n")
end
function ns.AuctionReport() return summary.."\n"..diagnostics() end
frame:SetScript("OnEvent",function(_,event,payload)
    counts[event]=math.min((counts[event] or 0)+1,99999)
    last=event.." at "..value(date,1,"%Y-%m-%d %H:%M:%S")
    local isResult=event=="AUCTION_ITEM_LIST_UPDATE" or event=="COMMODITY_SEARCH_RESULTS_UPDATED"
        or event=="ITEM_SEARCH_RESULTS_UPDATED" or event=="ITEM_SEARCH_RESULTS_ADDED"
    local closing=event=="AUCTION_HOUSE_CLOSED" or event=="PLAYER_LEAVING_WORLD" or event=="PLAYER_LOGOUT"
    if isResult or closing then
        generation=generation+1
        if interrupt then interrupt("Partial - results changed or window closed") end
    end
    if isResult then
        -- A result event is sufficient: reload may have missed the window opening.
        opened=true
        local ok,reason
        if event=="AUCTION_ITEM_LIST_UPDATE" then ok,reason=pcall(capture)
        else ok,reason=pcall(modernCapture,event=="COMMODITY_SEARCH_RESULTS_UPDATED" and "commodity" or "item",payload) end
        if not ok then summary="[Auction listings]\nPartial - API error; payload omitted"
        elseif reason then summary="[Auction listings]\n"..reason end
    elseif closing then opened=false end
    if ns.SaveAuctionDiagnostics then
        ns.SaveAuctionDiagnostics("Auction diagnostics", "Auction event diagnostics revision 2", "Event counts only; no raw payloads", {diagnostics()})
    end
end)
