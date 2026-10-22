local _, ns = ...
-- Party tokens only; no identities, targeting, messages or gameplay actions.
function ns.PartyReport()
    local ts,time=ns.Read(date,"%Y-%m-%d %H:%M:%S")
    local lines={"[Party member diagnostics - revision 1]",
        "Capture time (client local): " .. (ts=="OK" and tostring(time) or ts)}
    local function emit(label,s,v,detail)
        lines[#lines+1]=label..": "..s..(s=="OK" and (" = "..tostring(v)) or "")
            ..(detail and (" ("..detail..")") or "")
    end
    local rs,raid=ns.Read(IsInRaid)
    emit("Raid",rs,raid)
    if rs=="OK" and raid==true then
        lines[#lines+1]="Raid members not sampled by this party-only diagnostic."
        return table.concat(lines,"\n")
    end
    emit("Subgroup member count",ns.Read(GetNumSubgroupMembers))
    lines[#lines+1]="Sequential observations. Readable online values may be stale/out of range; no live combat or death inference from HP."
    for i=1,4 do
        local unit="party"..i
        local ms,member=ns.Read(UnitInParty,unit)
        emit(unit.." membership",ms,member)
        if ms=="OK" and member==true then
            local cs,connected=ns.Read(UnitIsConnected,unit)
            emit(unit.." connected",cs,connected)
            if cs=="OK" and connected==false then
                lines[#lines+1]=unit.." state: Offline; HP/mana/death unavailable - not sampled"
            elseif cs=="OK" and connected==true then
                local es,exists=ns.Read(UnitExists,unit)
                emit(unit.." exists",es,exists)
                if es=="OK" and exists==true then
                    lines[#lines+1]=unit.." state: Online (API observation)"
                    emit(unit.." deadOrGhost",ns.Read(UnitIsDeadOrGhost,unit))
                    emit(unit.." HP",ns.Read(UnitHealth,unit))
                    emit(unit.." maxHP",ns.Read(UnitHealthMax,unit))
                    local ps,power=ns.Read(UnitPowerType,unit)
                    emit(unit.." powerType",ps,power)
                    if ps=="OK" and power==0 then
                        emit(unit.." mana",ns.Read(UnitPower,unit,0))
                        emit(unit.." maxMana",ns.Read(UnitPowerMax,unit,0))
                    else lines[#lines+1]=unit.." mana: Not sampled - mana power type not confirmed" end
                else lines[#lines+1]=unit.." state: Unavailable; HP/mana/death not sampled" end
            else lines[#lines+1]=unit.." state: Connection Unknown/restricted; HP/mana/death not sampled" end
        elseif ms=="OK" and member==false then
            lines[#lines+1]=unit.." state: Not a party member"
        else lines[#lines+1]=unit.." state: Membership Unknown/restricted; not sampled" end
    end
    return table.concat(lines,"\n")
end
