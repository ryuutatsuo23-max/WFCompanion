"""Class-neutral simulated observations and reminder decisions. No input backend."""

from dataclasses import asdict, dataclass, field
import math
from typing import Optional


def number(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return value


def text(value, label, limit=80, allow_empty=False):
    if not isinstance(value, str) or len(value) > limit or (not value.strip() and not allow_empty):
        raise ValueError(f"{label} must be {'0' if allow_empty else '1'}–{limit} characters.")
    if any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must be a single line.")
    return value.strip()


@dataclass
class Rule:
    id: str
    name: str
    kind: str
    enabled: bool = True
    target: str = "self"
    threshold: float = 40
    recovery: float = 50
    delay: float = 0.5
    repeat: float = 0
    priority: int = 2
    require_cooldown: bool = False
    message: str = "Check the configured action"
    binding: str = ""
    tracker_id: str = "primary"
    cooldown_id: str = "primary"

    def validate(self):
        text(self.id, "Rule ID")
        text(self.name, "Rule name")
        if self.kind not in {"health", "buff", "cooldown"}:
            raise ValueError("Choose HP, missing buff or cooldown completion.")
        if self.target not in {"self", "party"}:
            raise ValueError("Choose your HP or the party member's HP.")
        if type(self.enabled) is not bool or type(self.require_cooldown) is not bool:
            raise ValueError("Rule switches must be on or off.")
        number(self.threshold, "HP threshold", 1, 99)
        number(self.recovery, "Recovery threshold", 2, 100)
        if self.recovery <= self.threshold:
            raise ValueError("Recovery must be higher than the HP threshold.")
        number(self.delay, "Confirmation delay", 0, 60)
        number(self.repeat, "Repeat interval", 0, 3600)
        if 0 < self.repeat < 1:
            raise ValueError("Use 0 for one reminder, or a repeat interval of at least 1 second.")
        if type(self.priority) is not int or not 1 <= self.priority <= 9:
            raise ValueError("Priority must be a whole number from 1 to 9.")
        text(self.message, "Reminder text", 140)
        text(self.binding, "Binding label", 30, allow_empty=True)
        text(self.tracker_id, "Tracker ID")
        text(self.cooldown_id, "Required cooldown ID")


@dataclass
class Tracker:
    """A stable profile identity, independent of its editable display label."""

    id: str
    name: str

    def validate(self):
        text(self.id, "Tracker ID")
        text(self.name, "Tracker name")


def extra_party():
    return [Tracker(f"party-{i}", f"Party member {i}") for i in range(2, 5)]


def extra_buffs():
    return [Tracker(f"buff-{i}", f"Buff {i}") for i in range(2, 4)]


def extra_cooldowns():
    return [Tracker(f"cooldown-{i}", f"Ability {i}") for i in range(2, 4)]


@dataclass
class Profile:
    id: str
    name: str
    character_class: str = "Unspecified"
    role: str = "General"
    party_name: str = "Party member"
    buff_name: str = "Tracked buff"
    cooldown_name: str = "Tracked ability"
    rules: list[Rule] = field(default_factory=list)
    party_members: list[Tracker] = field(default_factory=extra_party)
    buffs: list[Tracker] = field(default_factory=extra_buffs)
    cooldowns: list[Tracker] = field(default_factory=extra_cooldowns)
    level: int | None = None

    def trackers(self, kind):
        label, extra = {"party": (self.party_name, self.party_members),
                        "buff": (self.buff_name, self.buffs),
                        "cooldown": (self.cooldown_name, self.cooldowns)}[kind]
        return [Tracker("primary", label), *extra]

    def validate(self):
        for label, value in [("Profile ID", self.id), ("Profile name", self.name),
                             ("Party label", self.party_name), ("Buff label", self.buff_name),
                             ("Cooldown label", self.cooldown_name)]:
            text(value, label)
        if self.character_class not in CLASSES or self.role not in ROLES:
            raise ValueError("Choose a listed class and role.")
        if self.level is not None and (type(self.level) is not int or not 1 <= self.level <= 1000):
            raise ValueError("Character level must be a whole number from 1 to 1000, or blank for Unknown.")
        for kind, extras, limit in (("party", self.party_members, 3),
                                    ("buff", self.buffs, 7), ("cooldown", self.cooldowns, 7)):
            if not isinstance(extras, list) or len(extras) > limit:
                raise ValueError(f"Too many {kind} trackers in this profile.")
            tracker_ids = {"primary"}
            for tracker in extras:
                if not isinstance(tracker, Tracker):
                    raise ValueError("Invalid tracker.")
                tracker.validate()
                if tracker.id in tracker_ids:
                    raise ValueError("Tracker IDs must be unique within each category.")
                tracker_ids.add(tracker.id)
        if not isinstance(self.rules, list) or len(self.rules) > 30:
            raise ValueError("A profile supports up to 30 rules.")
        ids = set()
        for rule in self.rules:
            if not isinstance(rule, Rule):
                raise ValueError("Invalid reminder rule.")
            rule.validate()
            kind = "party" if rule.kind == "health" and rule.target == "party" else rule.kind
            if kind != "health" and rule.tracker_id not in {t.id for t in self.trackers(kind)}:
                raise ValueError(f"{rule.name} refers to a missing tracker.")
            if rule.require_cooldown and rule.cooldown_id not in {t.id for t in self.trackers("cooldown")}:
                raise ValueError(f"{rule.name} refers to a missing required cooldown.")
            if rule.id in ids:
                raise ValueError("Rule IDs must be unique.")
            ids.add(rule.id)

    def to_dict(self):
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
            raise ValueError("Invalid saved profile.")
        values = dict(data)
        try:
            values["rules"] = [Rule(**r) for r in values["rules"]]
            for key in ("party_members", "buffs", "cooldowns"):
                if key in values:
                    if not isinstance(values[key], list):
                        raise ValueError("Invalid saved tracker list.")
                    values[key] = [Tracker(**item) for item in values[key]]
            profile = cls(**values)
            profile.validate()
        except (TypeError, KeyError) as exc:
            raise ValueError("Invalid saved profile fields.") from exc
        return profile


CLASSES = ("Unspecified", "Druid", "Hunter", "Mage", "Paladin", "Priest",
           "Rogue", "Shaman", "Warlock", "Warrior")
ROLES = ("General", "Tank", "Healer", "Damage", "Professions", "Leveling")


def default_profile():
    return Profile("first-character", "First character", rules=[
        Rule("own-hp", "Your low HP", "health", priority=1,
             message="Consider your configured defensive or consumable"),
        Rule("party-hp", "Party low HP", "health", target="party", priority=2,
             message="Check this party member's health"),
        Rule("missing-buff", "Missing buff", "buff", delay=3, priority=3,
             message="Refresh the tracked buff when appropriate"),
        Rule("cooldown-ready", "Cooldown finished", "cooldown", delay=0, priority=4,
             message="The tracked cooldown has finished; castability is unknown"),
    ])


@dataclass(frozen=True)
class PartyReading:
    hp: Optional[float] = None
    identity_confirmed: bool = False


@dataclass(frozen=True)
class Observation:
    observed_at: float
    own_hp: Optional[float] = 100
    party_hp: Optional[float] = 82
    buff: str = "Present"
    cooldown: Optional[float] = 15
    identity_confirmed: bool = True
    available: bool = True
    party_readings: dict[str, PartyReading] = field(default_factory=dict)
    buff_readings: dict[str, str] = field(default_factory=dict)
    cooldown_readings: dict[str, Optional[float]] = field(default_factory=dict)

    def party_value(self, tracker_id):
        if tracker_id == "primary":
            return PartyReading(self.party_hp, self.identity_confirmed)
        return self.party_readings.get(tracker_id, PartyReading())

    def buff_value(self, tracker_id):
        return self.buff if tracker_id == "primary" else self.buff_readings.get(tracker_id, "Unknown")

    def cooldown_value(self, tracker_id):
        return self.cooldown if tracker_id == "primary" else self.cooldown_readings.get(tracker_id)

    def is_fresh(self, now):
        return math.isfinite(self.observed_at) and 0 <= now - self.observed_at <= 2


@dataclass(frozen=True)
class Decision:
    rule_id: str
    name: str
    code: str
    detail: str
    priority: int
    message: str = ""
    binding: str = ""


@dataclass
class Episode:
    active: bool = False
    since: Optional[float] = None
    last_notice: Optional[float] = None
    cooldown_armed: bool = False


class ReminderEngine:
    """Pure decisions. Bindings are descriptive text, never executable input.

    Unknown/stale data clears the episode and confirmation timer. Cooldown notices
    require an observed cooling -> ready transition; initial ready is silent.
    Every eligible rule is visible; priority orders the proposals, not execution.
    """

    def __init__(self):
        self.episodes = {}
        self.last_time = None

    def reset(self):
        self.episodes.clear()
        self.last_time = None

    def evaluate(self, rules, observation, now, paused=False):
        number(now, "Simulation time", 0, 1e15)
        if self.last_time is not None and now < self.last_time:
            self.reset()
        self.last_time = now
        decisions, notices = [], []
        valid_ids = {r.id for r in rules}
        self.episodes = {k: v for k, v in self.episodes.items() if k in valid_ids}
        for rule in sorted(rules, key=lambda r: (r.priority, r.name.casefold())):
            rule.validate()
            episode = self.episodes.setdefault(rule.id, Episode())

            def output(code, detail, clear=False):
                if clear:
                    self.episodes[rule.id] = Episode()
                decision = Decision(rule.id, rule.name, code, detail, rule.priority,
                                    rule.message if code == "active" else "",
                                    rule.binding if code == "active" else "")
                decisions.append(decision)
                return decision

            if not rule.enabled:
                output("disabled", "Disabled in this profile", True)
                continue
            if paused:
                output("paused", "Reminders paused", True)
                continue
            if not observation.available:
                output("blocked", "Simulated readings unavailable", True)
                continue
            if not observation.is_fresh(now):
                output("blocked", "Simulated reading is stale", True)
                continue

            if rule.kind == "health":
                party = observation.party_value(rule.tracker_id)
                if rule.target == "party" and not party.identity_confirmed:
                    output("blocked", "Party identity needs confirmation", True)
                    continue
                hp = observation.own_hp if rule.target == "self" else party.hp
                try:
                    number(hp, "HP", 0, 100)
                except ValueError:
                    output("blocked", "HP reading unknown", True)
                    continue
                cutoff = rule.recovery if episode.active else rule.threshold
                condition = hp < cutoff
                detail = f"{hp:g}% HP; clears at {rule.recovery:g}%" if condition else f"HP above trigger ({rule.threshold:g}%)"
            elif rule.kind == "buff":
                buff = observation.buff_value(rule.tracker_id)
                if buff not in {"Present", "Missing"}:
                    output("blocked", "Buff reading unknown", True)
                    continue
                condition = buff == "Missing"
                detail = "Tracked buff is clearly missing" if condition else "Tracked buff present"
            else:
                cooldown = observation.cooldown_value(rule.tracker_id)
                try:
                    number(cooldown, "Cooldown", 0, 3600)
                except ValueError:
                    output("blocked", "Cooldown reading unknown", True)
                    continue
                if cooldown > 0:
                    self.episodes[rule.id] = Episode(cooldown_armed=True)
                    output("watching", "Watching for cooldown completion")
                    continue
                condition = episode.cooldown_armed
                detail = "Cooldown finished; castability unknown"
                if not condition:
                    output("watching", "Ready at start; waiting for a cooling → ready transition")
                    continue

            if not condition:
                self.episodes[rule.id] = Episode()
                output("watching", detail)
                continue

            if rule.require_cooldown:
                required = observation.cooldown_value(rule.cooldown_id)
                try:
                    number(required, "Cooldown", 0, 3600)
                except ValueError:
                    output("blocked", "Required cooldown reading unknown", True)
                    continue
                if required > 0:
                    # Keep HP recovery hysteresis while the cooldown is blocked.
                    episode.since = None
                    output("blocked", "Waiting for the tracked cooldown")
                    continue

            if episode.since is None:
                episode.since = now
            elapsed = now - episode.since
            if elapsed + 1e-9 < rule.delay:
                output("confirming", f"Confirming condition · {rule.delay - elapsed:.1f}s remaining")
                continue
            episode.active = True
            decision = output("active", detail)
            if episode.last_notice is None or (rule.repeat > 0 and now - episode.last_notice >= rule.repeat):
                notices.append(decision)
                episode.last_notice = now
        return decisions, notices
