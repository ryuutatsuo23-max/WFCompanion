"""Validate schema-2 evidence independently; no inventory replacement authority."""
from collections import Counter,defaultdict
from probe_report import ReportError,array

STATES={'ok','unknown','unavailable','restricted','error','invalid'}
EMPTY='HasContainerItem-false-twice+nil-records+free-slot-crosscheck'


def parse_snapshot(snap,guid,scope,kind):
    from core_observations import Observation,integer,timestamp
    def require(test,message):
        if not test:raise ReportError('Schema 2: '+message)
    # 0.5.x changed interaction/appearance; Bags.lua collection is unchanged.
    require(snap.get('addonVersion') in ('0.4.0','0.5.0','0.5.1'),'unsupported producer version.')
    require(snap.get('owner')==guid and snap.get('scope')==scope and snap.get('accessible') is True,'owner/scope/access mismatch.')
    identity=snap.get('identity');client=snap.get('client')
    require(isinstance(identity,dict) and identity.get('guid')==guid,'snapshot identity mismatch.')
    require(all(isinstance(identity.get(k,''),str) and len(identity.get(k,''))<=160 for k in ('firstName','lastName','realm')),'invalid identity label.')
    require(isinstance(client,dict) and client.get('version')=='1.60.1' and type(client.get('interface')) is int and client['interface']==16001,'unsupported client.')
    require(snap.get('coverage') in ('complete','partial') and snap.get('scanStatus') in ('scanning','completed','interrupted','failed'),'invalid scan status.')
    require(type(snap.get('completed')) is bool and type(snap.get('declared')) is bool and type(snap.get('expectedSlotsKnown')) is bool,'invalid scan flags.')
    require(snap.get('consistency')=='event-invalidated-sequential' and snap.get('emptyEvidence')==EMPTY,'unsupported evidence predicate.')
    started,finished=timestamp(snap.get('startedAt')),timestamp(snap.get('finishedAt'))
    expected=array(snap.get('expectedContainers'),12)
    require(all(integer(i,-2,100) for i in expected) and len(set(expected))==len(expected),'invalid container declaration.')
    containers={}
    for container in array(snap.get('containers'),12):
        require(isinstance(container,dict),'invalid container row.')
        bag=container.get('id');size=container.get('slots')
        require(integer(bag,-2,100) and bag in expected and bag not in containers,'unexpected/duplicate container.')
        require(type(container.get('readable')) is bool,'invalid capacity flag.')
        require(integer(size,0,200) if container['readable'] else size is None,'invalid container capacity.')
        containers[bag]=container
    totals=defaultdict(int);counts=Counter();per={bag:Counter() for bag in containers};seen=set()
    for slot in array(snap.get('slots'),2400):
        require(isinstance(slot,dict),'invalid slot row.')
        bag,index=slot.get('bag'),slot.get('slot')
        require(integer(bag,-2,100) and bag in containers and integer(index,1,containers[bag].get('slots') or 0),'slot outside capacity.')
        require((bag,index) not in seen,'duplicate slot.');seen.add((bag,index))
        state=slot.get('state');require(state in ('observed','empty','unknown'),'unknown slot state.')
        require(all(slot.get(k) in STATES for k in ('presenceStatus','presenceAfterStatus','itemStatus','idStatus')),'invalid API status.')
        for value,status in (('presence','presenceStatus'),('presenceAfter','presenceAfterStatus')):
            if value in slot:require(type(slot[value]) is bool and slot[status]=='ok','invalid presence evidence.')
        if state=='observed':
            require(integer(slot.get('itemID'),1,2147483647) and integer(slot.get('count'),1,2147483647),'invalid item/count.')
            require(slot['itemStatus']=='ok' and slot['idStatus']=='ok' and slot.get('presence') is not False and slot.get('presenceAfter') is not False,'contradictory occupied evidence.')
            totals[slot['itemID']]+=slot['count']
        else:
            require('itemID' not in slot and 'count' not in slot,'non-item row contains ownership.')
            if state=='empty':
                require(slot.get('presence') is False and slot.get('presenceAfter') is False and slot['presenceStatus']=='ok' and slot['presenceAfterStatus']=='ok' and slot['itemStatus']=='unknown' and slot['idStatus']=='unknown','unproven empty slot.')
                c=containers[bag]
                require(c.get('sizeStable') is True and c.get('freeStable') is True,'empty slot lacks stable container evidence.')
        counts[state]+=1;per[bag][state]+=1
    complete=snap['coverage']=='complete'
    final=snap['scanStatus']!='scanning'
    for bag,c in containers.items():
        actual=per[bag];size=c.get('slots')
        if actual['empty']:
            require(integer(c.get('freeSlots'),0,size) and integer(c.get('freeSlotsEnd'),0,size) and c['freeSlotsEnd']==c['freeSlots']==actual['empty'],'free-slot evidence mismatch.')
        if c.get('coverage')=='complete' or complete:
            require(c.get('coverage')=='complete' and c['readable'] and c.get('sizeStable') is True and c.get('freeStable') is True,'incomplete container.')
            require(sum(actual.values())==size and actual['unknown']==0 and integer(c.get('freeSlots'),0,size) and integer(c.get('freeSlotsEnd'),0,size) and c['freeSlotsEnd']==c['freeSlots']==actual['empty'],'container coverage mismatch.')
        if final:
            for field,state in (('observedSlots','observed'),('emptySlots','empty'),('unknownSlots','unknown')):
                require(type(c.get(field)) is int and c[field]==actual[state],'container counters disagree.')
            require(type(c.get('scannedSlots')) is int and c['scannedSlots']==sum(actual.values()),'container scanned count mismatch.')
    if final:
        for field,state in (('observedSlots','observed'),('emptySlots','empty'),('unknownSlots','unknown')):
            require(type(snap.get(field)) is int and snap[field]==counts[state],'global counters disagree.')
        require(type(snap.get('scannedSlots')) is int and snap['scannedSlots']==len(seen),'global scanned count mismatch.')
    if complete:
        require(kind=='latest' and snap['completed'] is True and snap['scanStatus']=='completed' and snap['declared'] is True and snap['expectedSlotsKnown'] is True,'invalid complete-scan flags.')
        require(started is not None and finished is not None and finished>=started,'invalid complete-scan times.')
        require(set(containers)==set(expected) and len(seen)>0 and type(snap.get('expectedSlots')) is int and snap['expectedSlots']==len(seen),'incomplete declared coverage.')
        if scope=='bank':require(set(expected)==set(range(6,15)),'bank declaration mismatch.')
        else:
            positives=sorted(i for i in expected if i>=0);negatives=[i for i in expected if i<0]
            require(positives==list(range(len(positives))) and 1<=len(positives)<=11 and len(negatives)==1,'bag declaration mismatch.')
    name=' '.join(identity.get(k,'') for k in ('firstName','lastName')).strip() or guid
    return Observation(guid,name,scope,str(client.get('build','Unknown')),started,finished,snap['coverage'],counts['unknown'],tuple(sorted(totals.items())),kind=='attempt',2,counts['observed'],counts['empty'],snap['scanStatus'],identity.get('realm',''),client['version'],client['interface'])
