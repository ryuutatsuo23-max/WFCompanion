-- SPDX-License-Identifier: GPL-3.0-only
-- Manual diagnostic only. No crafting, selection, filters, timers or inventory writes.
local addon, ns = ...
local core=ns.core
-- IDs verified from Forever saved observations; names are prompts, not identity.
local learnedModes={learnedTailoring={id=197,name="Tailoring"},learnedCooking={id=185,name="Cooking"}}
local db, opened, generation=nil,false,0
local eventLog, registrations={},{}
local sequence, lastReset=0,"addon-load"
local function noteEvent(event)
    sequence=math.min(sequence+1,1000000)
    if #eventLog==16 then table.remove(eventLog,1) end
    eventLog[#eventLog+1]={sequence=sequence,event=event,opened=opened}
end
local function say(s) if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("Forever Professions: "..s) end end
local function scalar(v,status)
    if status=="ok" and (type(v)=="string" or type(v)=="number" or type(v)=="boolean") then
        return {status="known",value=v}
    end
    return {status=status=="ok" and "invalid" or status}
end
local function read(fn,...) return scalar(core.Read(fn,...)) end
local function field(t,key) return scalar(core.Field(t,key)) end
local function nth(fn,n,...)
    if type(fn)~="function" then return {status="unavailable"} end
    local args={...}
    return read(function() return select(n,fn(unpack(args))) end)
end
local function fields(t,names)
    local result={}; for _,key in ipairs(names) do result[key]=field(t,key) end; return result
end
local function rows(t,limit,convert)
    local result={rows={},coverage="bounded-sample"}
    if type(t)~="table" then result.status="unavailable"; return result end
    for i=1,limit+1 do
        local value,status=core.Field(t,i)
        if status=="unknown" then result.status="observed"; result.coverage="returned-array-ended"; return result end
        if status~="ok" then result.status=status; return result end
        if i>limit then result.status="partial"; return result end
        result.rows[i]=convert(value)
    end
    return result
end
local function api(name)
    return type(C_TradeSkillUI)=="table" and C_TradeSkillUI[name] or nil
end
-- Visibility alone never grants permission to scan; manual UI refresh also
-- requires this evidence alongside the existing own-source and event guards.
local function visible(name,child)
    local frame,status=core.Field(_G,name)
    if status~="ok" then return {status=status} end
    if child then frame,status=core.Field(frame,child) end
    if status~="ok" then return {status=status} end
    if type(frame)~="table" then return {status="invalid"} end
    if not core.Access(frame,true) then return {status="restricted"} end
    return read(function() return frame:IsShown() end)
end
local function context()
    local result={status="observed",windowObserved=opened,lastReset=lastReset,
        sequence=sequence,registrations=ns.Copy(registrations),events=ns.Copy(eventLog),
        visibility={professions=visible("ProfessionsFrame"),bookPage=visible("ProfessionsFrame","BookPage"),
            craftingPage=visible("ProfessionsFrame","CraftingPage"),standaloneBook=visible("ProfessionsBookFrame")},
        capabilities={}}
    for _,name in ipairs({"GetAllRecipeIDs","GetRecipeInfo","GetRecipeSchematic","GetRecipeRequirements",
        "GetCraftableCount","GetBaseProfessionInfo","IsTradeSkillLinked","IsTradeSkillGuild","IsTradeSkillGuildMember"}) do
        result.capabilities[name]=type(api(name))=="function"
    end
    return result
end
local function skills()
    local result={entries={},coverage="five-profession-slots",status="unavailable"}
    for i=1,5 do
        local index=nth(GetProfessions,i)
        local row={index=index}
        if index.status=="known" and core.Integer(index.value,1,10000) then
            row.name=nth(GetProfessionInfo,1,index.value)
            row.rank=nth(GetProfessionInfo,3,index.value)
            row.maxRank=nth(GetProfessionInfo,4,index.value)
            row.skillLineID=nth(GetProfessionInfo,7,index.value)
            row.rankModifier=nth(GetProfessionInfo,8,index.value)
            if row.skillLineID.status=="known" then
                local value,status=core.Read(api("GetProfessionInfoBySkillLineID"),row.skillLineID.value)
                row.modernStatus=status
                if status=="ok" then row.modern=fields(value,{"professionName","skillLevel","maxSkillLevel","skillModifier"}) end
            end
            result.status="observed"
        end
        result.entries[i]=row
    end
    return result
end
local function recipe(id)
    local r={id=scalar(id,"ok")}
    if not core.Integer(id,1,2147483647) then r.status="invalid"; return r end
    local info,status=core.Read(api("GetRecipeInfo"),id)
    r.infoStatus=status
    if status=="ok" then r.info=fields(info,{"name","recipeID","learned","craftable","disabled","disabledReason","relativeDifficulty","numSkillUps","canSkillUp"}) end
    r.craftableCount=read(api("GetCraftableCount"),id)
    local requirements,rs=core.Read(api("GetRecipeRequirements"),id)
    r.requirementsStatus=rs
    r.requirements=rows(requirements,8,function(v) return fields(v,{"name","met","type"}) end)
    local schematic,ss=core.Read(api("GetRecipeSchematic"),id,false)
    r.schematicStatus=ss
    if ss=="ok" then
        r.output=fields(schematic,{"name","outputItemID","quantityMin","quantityMax","recipeType"})
        local slots,ts=core.Field(schematic,"reagentSlotSchematics")
        r.slotsStatus=ts
        r.slots=rows(slots,16,function(slot)
            local s=fields(slot,{"quantityRequired","required","reagentType","dataSlotType"})
            local choices,cs=core.Field(slot,"reagents"); s.choicesStatus=cs
            s.choices=rows(choices,8,function(item) return fields(item,{"itemID","currencyID"}) end)
            local detail,ds=core.Field(slot,"slotInfo"); s.detailStatus=ds
            if ds=="ok" then s.detail=fields(detail,{"requiredSkillRank","slotText"}) end
            return s
        end)
    end
    return r
end
local function recipes(target,learned,requireWindow)
    local result={status="unavailable",windowObserved=opened,coverage="at-most-five-returned-recipes"}
    result.context=context()
    if requireWindow then
        local page=result.context.visibility.craftingPage
        if page.status~="known" or page.value~=true then
            result.reason="Open the matching profession recipe window, then press Refresh again"
            return result
        end
    end
    result.source={}
    for _,name in ipairs({"IsTradeSkillLinked","IsTradeSkillGuild","IsTradeSkillGuildMember"}) do
        result.source[name]=read(api(name))
    end
    if not opened then result.reason="No recipe-window show observed; open Tailoring/Cooking recipe list, then retry. /wfprofprobe context records why"; return result end
    for _,v in pairs(result.source) do
        if v.status~="known" or v.value~=false then result.reason="Own-character source not established"; return result end
    end
    local prof,ps=core.Read(api("GetBaseProfessionInfo")); result.professionStatus=ps
    if ps=="ok" then result.profession=fields(prof,{"professionName","professionID","skillLevel","maxSkillLevel"}) end
    if learned then
        result.coverage="returned-list-only"
        result.counts={scanned=0,learned=0,unlearned=0,unknown=0}
        result.sample={rows={},status="partial",coverage="returned-list-only"}
        local function refuse(reason)
            result.status="partial"; result.reason=reason; return result
        end
        if not result.profession or result.profession.professionID.value~=learned.id then
            return refuse("Open your own "..learned.name.." window; profession "..learned.id.." required")
        end
        -- GetAllRecipeIDs is live-evidenced on 70532, not assumed from another client.
        -- Verify a dense bounded array before querying recipes; holes are not empty lists.
        local function list()
            local values,state=core.Read(api("GetAllRecipeIDs"))
            if state~="ok" or type(values)~="table" then return nil end
            local count,seen,copy=0,{},{}
            for key in pairs(values) do
                if not core.Access(key) or not core.Integer(key,1,2000) then return nil end
                count=count+1; if count>2000 then return nil end
            end
            for i=1,count do
                local id,st=core.Field(values,i)
                if st~="ok" or not core.Integer(id,1,2147483647) or seen[id] then return nil end
                seen[id]=true; copy[i]=id
            end
            return copy
        end
        local ids=list()
        if not ids then return refuse("Recipe list unavailable, malformed or exceeds 2000 IDs") end
        for _,id in ipairs(ids) do
            local info,state=core.Read(api("GetRecipeInfo"),id)
            local flag=state=="ok" and field(info,"learned") or {status=state}
            result.counts.scanned=result.counts.scanned+1
            if flag.status~="known" or type(flag.value)~="boolean" then
                result.counts.unknown=result.counts.unknown+1
            elseif not flag.value then result.counts.unlearned=result.counts.unlearned+1
            else
                if result.counts.learned>=100 then return refuse("Learned recipe limit 100 reached; previous capture retained") end
                local r=recipe(id)
                if not r.info or r.info.recipeID.value~=id or r.info.learned.value~=true
                    or r.info.name.status~="known" or type(r.info.name.value)~="string" or r.info.name.value=="" then
                    return refuse("Learned recipe identity or name changed/unavailable")
                end
                result.counts.learned=result.counts.learned+1
                result.sample.rows[#result.sample.rows+1]=r
            end
        end
        if result.counts.unknown>0 then return refuse("Unknown learned flags; previous capture retained") end
        local final=list()
        if not final or #final~=#ids then return refuse("Recipe list changed; previous capture retained") end
        for i,id in ipairs(ids) do if final[i]~=id then return refuse("Recipe list changed; previous capture retained") end end
        if requireWindow then
            local page=visible("ProfessionsFrame","CraftingPage")
            if page.status~="known" or page.value~=true then return refuse("Recipe window closed; previous capture retained") end
        end
        local after,st=core.Read(api("GetBaseProfessionInfo"))
        if st~="ok" or field(after,"professionID").value~=learned.id then return refuse("Profession changed") end
        for name in pairs(result.source) do
            local flag=read(api(name))
            if flag.status~="known" or flag.value~=false then return refuse("Own-character source changed") end
        end
        -- Complete traversal is not proof of an unfiltered catalogue. Detail fields
        -- retain their independent unknown/restricted/partial states from recipe().
        result.sample.status="observed"; result.sample.coverage="returned-array-ended"
        result.status="observed"; result.listStatus="ok"
        return result
    end
    local ids,is=core.Read(api("GetAllRecipeIDs")); result.listStatus=is
    if target then
        result.coverage="exact-name-search-at-most-2000-ids"
        result.requestedName=target
        if is~="ok" or type(ids)~="table" then result.reason="Recipe list unavailable"; return result end
        local match,ended=nil,false
        for i=1,2001 do
            local id,state=core.Field(ids,i)
            if state=="unknown" then ended=true; break end
            if state~="ok" or not core.Integer(id,1,2147483647) then result.reason="Unreadable recipe list; target unresolved"; return result end
            if i>2000 then result.reason="Search limit reached; target unresolved"; return result end
            local info,infoState=core.Read(api("GetRecipeInfo"),id)
            local name=infoState=="ok" and field(info,"name") or {status=infoState}
            if name.status~="known" or type(name.value)~="string" then
                result.reason="Recipe name unavailable; target unresolved"; return result
            end
            if name.value:lower()==target:lower() then
                if match then result.reason="Ambiguous recipe name; no capture"; return result end
                match=id
            end
        end
        if not ended or not match then result.reason="No exact recipe-name match in returned list"; return result end
        local captured=recipe(match)
        if not captured.info or captured.info.name.status~="known" or type(captured.info.name.value)~="string"
            or captured.info.name.value:lower()~=target:lower()
            or captured.info.recipeID.value~=match then
            result.reason="Recipe identity changed or unavailable; previous capture preserved"; return result
        end
        result.sample={status="observed",coverage="one-exact-name-match",rows={captured}}
        result.status="observed"
        return result
    end
    result.sample=rows(ids,5,recipe)
    if is=="ok" and type(ids)=="table" then result.status="observed" end
    return result
end
-- Saved diagnostics are bounded plain data. Unsupported saves are never replaced.
local function safe(v,seen,budget,depth)
    budget.n=budget.n+1
    if budget.n>80000 or depth>24 then return false end
    if type(v)=="table" then
        if getmetatable(v) or seen[v] then return false end
        seen[v]=true
        for k,x in pairs(v) do
            if (type(k)~="string" and type(k)~="number") or not safe(k,seen,budget,depth+1) or not safe(x,seen,budget,depth+1) then return false end
        end
        seen[v]=nil; return true
    end
    return type(v)=="boolean" or (type(v)=="string" and #v<=160)
        or (type(v)=="number" and v==v and math.abs(v)<math.huge)
end
local function initialize()
    if ns.syntheticPreview then db={schema=1,producer="WFProfessionsProbe",characters={}}; ns.probeStore=db; return end
    if WFProfessionsProbeDB==nil then WFProfessionsProbeDB={schema=1,producer="WFProfessionsProbe",characters={}} end
    local candidate=WFProfessionsProbeDB
    db=nil; ns.probeStore=nil
    if type(candidate)=="table" and safe(candidate,{}, {n=0},0) and candidate.schema==1
        and candidate.producer=="WFProfessionsProbe" and type(candidate.characters)=="table" then
        local count=0
        for guid,c in pairs(candidate.characters) do
            count=count+1
            if count>50 or type(guid)~="string" or not guid:match("^Player%-%d+%-%x+$") or type(c)~="table" then return end
        end
        db=candidate
    end
    ns.probeStore=db
end
function ns.RunProbe(mode,target,requireWindow)
    local learned=learnedModes[mode]
    if mode~="skills" and mode~="recipes" and mode~="context" and mode~="targetRecipe" and not learned then say("/wfprofprobe skills, recipes, context, learned [tailoring|cooking], or recipe <exact name>. No crafting."); return false end
    if mode=="targetRecipe" then
        if type(target)~="string" or #target==0 or #target>120 or target:find("[%c|]") then
            say("Provide an exact recipe name (1-120 characters)."); return false
        end
    else target=nil end
    local owner,epoch,startSequence=core.owner,generation,sequence
    local stamp=core.Stamp()
    if not db or not core.inWorld or not core.character or not owner or not core.Integer(stamp,1,2147483647) then
        say("Storage, identity, world or time unavailable; previous observations preserved."); return false
    end
    local client={version=nth(GetBuildInfo,1),build=nth(GetBuildInfo,2),interface=nth(GetBuildInfo,4)}
    if client.version.value~="1.60.1" or client.interface.value~=16001 then say("Unsupported client; no capture."); return false end
    local collect=mode=="skills" and skills or mode=="context" and context or recipes
    local ok,result=pcall(collect,target,learned,requireWindow)
    if not ok or generation~=epoch or owner~=core.owner or not core.inWorld or (learned and sequence~=startSequence) then say("Probe interrupted/error; previous observations preserved."); return false end
    local count=0; for _ in pairs(db.characters) do count=count+1 end
    if not db.characters[owner] and count>=50 then say("Character limit; preserved."); return false end
    local c=db.characters[owner] or {}
    local attempt={at=stamp,client=client,provenance=ns.syntheticPreview and "synthetic-probe" or "live-probe",report=result}
    if learned then
        -- Use the existing save validator/budget before committing either field.
        local candidate=ns.Copy(db)
        candidate.characters[owner]=candidate.characters[owner] or {}
        candidate.characters[owner][mode.."Attempt"]=attempt
        if result.status=="observed" then candidate.characters[owner][mode]=attempt end
        if not safe(candidate,{}, {n=0},0) then say("Save budget exceeded; previous observations preserved."); return false end
    end
    db.characters[owner]=c
    c[mode.."Attempt"]=attempt
    if result.status=="observed" then c[mode]=attempt end
    if mode=="context" then
        -- Six manually requested snapshots let closed/book/crafting/closed coexist.
        -- Keep malformed old history untouched rather than attempting a migration.
        if c.contextHistory==nil then c.contextHistory={} end
        if type(c.contextHistory)=="table" and #c.contextHistory<=6 then
            if #c.contextHistory==6 then table.remove(c.contextHistory,1) end
            c.contextHistory[#c.contextHistory+1]=ns.Copy(attempt)
        end
    end
    say(mode..": "..result.status.."; build "..ns.Display(client.build).."; "..(result.reason or "captured in memory; normal logout saves to disk"))
    if mode=="context" then
        say("Show event registered="..tostring(result.registrations.TRADE_SKILL_SHOW).."; observed="..tostring(opened).."; reset="..lastReset)
        say("Overview="..ns.Display(result.visibility.bookPage).."; crafting page="..ns.Display(result.visibility.craftingPage).."; recipe-list API="..tostring(result.capabilities.GetAllRecipeIDs))
    elseif mode=="skills" then
        for _,row in ipairs(result.entries) do
            if row.name then say(ns.Display(row.name)..": "..ns.Display(row.rank).." / "..ns.Display(row.maxRank)) end
        end
    elseif learned then
        local counts=result.counts
        if counts then say("Returned list: "..counts.learned.." learned; "..counts.unlearned.." unlearned; "..counts.unknown.." unknown. Details may be unavailable.") end
    elseif result.sample then
        for _,r in ipairs(result.sample.rows) do
            say("Recipe "..ns.Display(r.id)..": "..(r.info and ns.Display(r.info.name) or r.infoStatus or "Unknown").."; available count "..ns.Display(r.craftableCount))
            if mode=="targetRecipe" then
                say("Learned: "..(r.info and ns.Display(r.info.learned) or "Unknown"))
                for _,slot in ipairs(r.slots and r.slots.rows or {}) do
                    for _,item in ipairs(slot.choices.rows) do
                        say("Material item "..ns.Display(item.itemID).."; quantity "..ns.Display(slot.quantityRequired).."; required "..ns.Display(slot.required))
                    end
                end
            end
        end
    end
    return result.status=="observed"
end
-- Called only by the explicit journal Refresh click. No event invokes capture.
function ns.RefreshLearned(owner,professionID)
    if owner~=core.owner or not core.inWorld or not core.character then
        return false,"Refresh refused: select your current character"
    end
    local mode=professionID==197 and "learnedTailoring" or professionID==185 and "learnedCooking"
    if not mode then return false,"Refresh supports Tailoring and Cooking only" end
    local accepted=ns.RunProbe(mode,nil,true)
    return accepted,accepted and "Recipes refreshed" or "Refresh refused; previous capture retained"
end
core.On("ADDON_LOADED",function(name) if name==addon then initialize() end end)
for _,name in ipairs({"TRADE_SKILL_SHOW","TRADE_SKILL_CLOSE","TRADE_SKILL_DATA_SOURCE_CHANGING",
    "TRADE_SKILL_DATA_SOURCE_CHANGED","TRADE_SKILL_LIST_UPDATE","PLAYER_LEAVING_WORLD","PLAYER_ENTERING_WORLD","PLAYER_LOGOUT"}) do
    local event=name
    registrations[event]=core.On(event,function()
        if event=="TRADE_SKILL_SHOW" then opened=true
        elseif event=="TRADE_SKILL_CLOSE" or event:find("^PLAYER_") then opened=false; lastReset=event end
        if event~="TRADE_SKILL_LIST_UPDATE" then generation=generation+1 end
        noteEvent(event)
    end)
end
SLASH_WFPROFESSIONSPROBE1="/wfprofprobe"
SlashCmdList.WFPROFESSIONSPROBE=function(message)
    local mode,arg=(message or ""):match("^%s*(%S+)%s*(.-)%s*$")
    mode=(mode or ""):lower()
    if mode=="learned" then
        local profession=(arg or ""):lower()
        if profession=="" or profession=="tailoring" then mode="learnedTailoring"
        elseif profession=="cooking" then mode="learnedCooking"
        else say("Use /wfprofprobe learned tailoring or /wfprofprobe learned cooking."); return end
    end
    ns.RunProbe(mode=="recipe" and "targetRecipe" or mode,arg)
end
