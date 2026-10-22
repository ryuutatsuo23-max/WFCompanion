"""Display-only simplification; never changes counts or freshness evidence."""
def easy_mode(host):
    return host.qt_settings.get('experience_mode','Easy')=='Easy'


def simple_observation(value):
    if value.startswith('Unavailable'):return 'Could not check'
    if 'manual records only' in value:return 'Manually recorded'
    if value.startswith('Not captured'):return 'Not checked yet'
    if value.startswith('Outdated') or 'date unknown' in value or 'check clock' in value:return 'May need updating'
    return 'Saved records available'


def simple_count(quantity,status):
    if status=='Recheck':return 'May need updating'
    if status!='Known' or quantity is None:return 'Not checked yet'
    return f'Yes · {quantity}' if quantity>0 else 'No · recorded zero'


def simple_other_stock(characters):
    if not characters:return 'No other characters'
    quantities=[count.quantity for character in characters for count in character.counts]
    if any(q is not None and q>0 for q in quantities):return 'Yes · view characters'
    if any(q is None for q in quantities):return 'Not checked yet'
    return 'No · recorded zero'


def simple_requirement(requirement):
    """Keep incomplete stock unknown, even when one location has items."""
    owned='Not checked yet' if requirement.owned is None else str(requirement.owned)
    remaining=requirement.remaining
    missing='Not checked yet' if remaining is None else ('Ready' if remaining==0 else str(remaining))
    return owned,missing
