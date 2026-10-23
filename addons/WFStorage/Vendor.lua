local _,ns=...
-- Manual batches only. No sale on opening a merchant, refresh or login.
local vendor={open=false,status="Sell gray items; favorites are kept"}
ns.vendor=vendor
local pending,active
local function ready()
    local cursor,status=ns.Read(GetCursorInfo)
    return vendor.open and ns.InteractionReady() and MerchantFrame
        and MerchantFrame:IsShown() and cursor==nil and status=="unknown"
end
local function info(bag,slot)
    local api=C_Container or {}
    local record=ns.Read(api.GetContainerItemInfo,bag,slot)
    local id=ns.Read(api.GetContainerItemID,bag,slot)
    if not ns.Integer(id,1,2147483647) or ns.Field(record,"itemID")~=id
        or ns.Field(record,"quality")~=0 or ns.Field(record,"isLocked")~=false
        or ns.Field(record,"hasNoValue")~=false or ns.IsFavorite(ns.owner,id) then return end
    local count=ns.Field(record,"stackCount")
    local price=ns.Read(function() return select(11,C_Item.GetItemInfo(id)) end)
    if not ns.Integer(count,1,1000000) or not ns.Integer(price,1,2147483647) then return end
    local name=ns.Read(function() return C_Item.GetItemNameByID(id) end)
    return {bag=bag,slot=slot,id=id,count=count,price=price,
        name=type(name)=="string" and name or ("Item "..id)}
end
local function same(a,b)
    return a and b and a.id==b.id and a.count==b.count and a.price==b.price
end
local function report(text)
    vendor.status=text
    if ns.RefreshUI then ns.RefreshUI() end
end
function ns.CancelJunkSale(message)
    pending=nil; active=nil
    if type(StaticPopup_Hide)=="function" then StaticPopup_Hide("WFSTORAGE_SELL_JUNK") end
    report(message or "Junk sale cancelled")
end
function ns.JunkSalePreview()
    if not ready() then return nil end
    local result={owner=ns.owner,items={},total=0}
    for _,bag in ipairs(ns.inventory.ActionContainers("bags")) do
        local size=ns.Read(C_Container.GetContainerNumSlots,bag)
        if ns.Integer(size,0,200) then
            for slot=1,size do
                local item=info(bag,slot)
                if item then
                    result.items[#result.items+1]=item
                    result.total=result.total+item.price*item.count
                    if #result.items==12 then return result end
                end
            end
        end
    end
    return result
end
local function finish(message)
    active=nil; report(message); ns.inventory.Request("bags")
end
local function sellNext(job)
    if active~=job then return end
    if not ready() or ns.owner~=job.owner then ns.CancelJunkSale("Junk sale stopped: vendor unavailable"); return end
    local item=job.items[job.index]
    if not item then finish("Junk sold: "..job.sold.." stacks"); return end
    if not same(item,info(item.bag,item.slot)) then finish("Junk sale stopped: item changed; review again"); return end
    if type(C_Container.UseContainerItem)~="function" then finish("Vendor sale unavailable"); return end
    local ok=pcall(C_Container.UseContainerItem,item.bag,item.slot)
    if not ok then finish("Vendor sale blocked; use Native UI"); return end
    -- Do not infer success from pcall or retry a potentially protected action.
    local tries=0
    local function confirm()
        if active~=job then return end
        if not ready() or ns.owner~=job.owner then ns.CancelJunkSale("Junk sale stopped: vendor unavailable"); return end
        local present,status=ns.Read(C_Container.HasContainerItem,item.bag,item.slot)
        local id,idStatus=ns.Read(C_Container.GetContainerItemID,item.bag,item.slot)
        if status=="ok" and present==false and id==nil and idStatus=="unknown" then
            job.sold=job.sold+1; job.index=job.index+1; sellNext(job); return
        end
        tries=tries+1
        if tries>=10 then finish("Sale not confirmed; stopped. Check vendor buyback."); return end
        C_Timer.After(.2,confirm)
    end
    C_Timer.After(.2,confirm)
end
function ns.ConfirmJunkSale(request)
    if not request or request~=pending or active then return false end
    pending=nil
    if not ready() or request.owner~=ns.owner or not C_Timer or type(C_Timer.After)~="function" then return false end
    for _,item in ipairs(request.items) do
        if not same(item,info(item.bag,item.slot)) then report("Junk changed; review again"); return false end
    end
    active=request; active.index=1; active.sold=0
    report("Selling reviewed junk…"); sellNext(active); return true
end
function ns.RequestJunkSale()
    if active then ns.CancelJunkSale(); return end
    local request=ns.JunkSalePreview()
    if not request then report("Visit a vendor to sell junk"); return end
    if #request.items==0 then report("No readable, sellable gray items (favorites kept)"); return end
    if type(StaticPopupDialogs)~="table" or type(StaticPopup_Show)~="function" then report("Sale confirmation unavailable"); return end
    local lines={"Sell these gray items? (up to 12 stacks)","Favorites are kept."}
    for _,item in ipairs(request.items) do lines[#lines+1]=item.name.." x"..item.count end
    local value=request.total
    lines[#lines+1]="Total: "..math.floor(value/10000).."g "..math.floor(value/100)%100 .."s "..value%100 .."c"
    StaticPopupDialogs.WFSTORAGE_SELL_JUNK={text="%s",button1="Sell",button2="Cancel",timeout=0,
        whileDead=false,hideOnEscape=true,preferredIndex=3,
        OnAccept=function(_,data) ns.ConfirmJunkSale(data) end,
        OnCancel=function() pending=nil end}
    pending=request; StaticPopup_Show("WFSTORAGE_SELL_JUNK",table.concat(lines,"\n"),nil,request)
end
ns.On("MERCHANT_SHOW",function() vendor.open=true; ns.ShowInventory("bags"); report("Sell gray items; favorites are kept") end)
ns.On("MERCHANT_CLOSED",function() vendor.open=false; ns.CancelJunkSale("Visit a vendor to sell junk") end)
ns.On("PLAYER_REGEN_DISABLED",function() ns.CancelJunkSale("Junk sale stopped: combat") end)
ns.On("PLAYER_LEAVING_WORLD",function() vendor.open=false; ns.CancelJunkSale("Junk sale stopped") end)
