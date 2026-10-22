local _, ns = ...
-- Additive text section; never import counts into the companion or infer empty from nil.
-- Existing summary remains the legacy four-slot sample. This section contains full coverage.
function ns.FullInventory(budget)
    local lines, bytes, clipped = {}, 0, false
    local function emit(text)
        if bytes + #text + 1 > budget - 150 then clipped = true; return false end
        lines[#lines + 1] = text; bytes = bytes + #text + 1
        return true
    end
    local function integer(status, value, low, high)
        return status == "OK" and type(value) == "number" and value >= low
            and value <= high and value == math.floor(value)
    end
    local function token(status, value, low, high)
        if integer(status, value, low, high) then return tostring(value) end
        if status == "OK" then return "Unknown(invalid)" end
        return status
    end
    emit("[Full carried inventory and equipment - revision 1]")
    local timeStatus, timeValue = ns.Read(date, "%Y-%m-%d %H:%M:%S")
    emit("Capture time (client local): " .. (timeStatus == "OK" and tostring(timeValue) or timeStatus))
    emit("Each row shares this capture time. Sequential reads are not an atomic inventory transaction.")
    emit("Nil means Unknown (empty or inaccessible), not zero ownership. Bank/mail are not scanned.")
    local c = C_Container or {}
    local totalStatus, total = ns.Read(function() return NUM_TOTAL_EQUIPPED_BAG_SLOTS end)
    local complete = true
    local bagIDs = {}
    if integer(totalStatus, total, 0, 10) then
        for id = 0, total do bagIDs[#bagIDs+1] = id end
        emit("Bag range: client-declared 0.." .. total)
    else
        -- Do not assume a bank index is an extra carried bag on this build.
        for id = 0, 4 do bagIDs[#bagIDs+1] = id end
        complete = false
        emit("Bag range: fallback 0..4; extra-bag coverage Unknown (client constant unavailable/invalid)")
    end
    local keyStatus, keyring = ns.Read(function() return KEYRING_CONTAINER end)
    if integer(keyStatus, keyring, -2, -2) then bagIDs[#bagIDs+1] = keyring end
    for _, bag in ipairs(bagIDs) do
        if clipped then break end
        local status, slots = ns.Read(c.GetContainerNumSlots, bag)
        emit("Bag " .. bag .. " slots: " .. token(status, slots, 0, 200))
        if integer(status, slots, 0, 200) then
            for slot = 1, slots do
                if clipped then break end
                local idStatus, id = ns.Read(c.GetContainerItemID, bag, slot)
                local countStatus, count = "Unknown (nil)", nil
                local recordStatus, item = ns.ReadRecord(c.GetContainerItemInfo, bag, slot)
                if recordStatus == "OK" then
                    countStatus, count = ns.ReadField(item, "stackCount")
                    local infoStatus, infoID = ns.ReadField(item, "itemID")
                    if integer(idStatus, id, 1, 2147483647) and integer(infoStatus, infoID, 1, 2147483647) and id ~= infoID then
                        countStatus, count = "Unknown (item changed)", nil
                    end
                else countStatus = recordStatus end
                emit("B" .. bag .. "/" .. slot .. " id=" .. token(idStatus, id, 1, 2147483647)
                    .. " qty=" .. token(countStatus, count, 0, 2147483647))
            end
        else complete = false end
    end
    -- These named slots are verified in the extracted Forever FrameXML constants.
    -- Slot 0 (ammo) is sampled separately; unsupported/nil stays Unknown.
    emit("Equipment slots: 0 ammo; 1 head; 2 neck; 3 shoulder; 4 shirt; 5 chest; 6 waist; 7 legs; 8 feet; 9 wrist; 10 hands; 11-12 fingers; 13-14 trinkets; 15 back; 16 main hand; 17 off hand; 18 ranged; 19 tabard")
    for slot = 0, 19 do
        if clipped then break end
        local idStatus, id = ns.Read(GetInventoryItemID, "player", slot)
        local countStatus, count = ns.Read(GetInventoryItemCount, "player", slot)
        -- Do not attach a reported zero count to an unidentified equipment slot.
        if not integer(idStatus, id, 1, 2147483647) then countStatus, count = "Unknown (item unidentified)", nil end
        emit("E" .. slot .. " id=" .. token(idStatus, id, 1, 2147483647)
            .. " qty=" .. token(countStatus, count, 0, 2147483647))
    end
    lines[#lines+1] = "Scan coverage: " .. (clipped and "Partial - report size limit reached" or complete and "All declared bag slots and equipment slots attempted; Unknown rows remain unresolved" or "Partial - bag coverage unavailable/invalid")
    return table.concat(lines, "\n")
end
