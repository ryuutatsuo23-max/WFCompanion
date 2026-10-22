"""Offline Tk preview: simulated reminders, manual plans and local item lookup."""

import argparse
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import time
import traceback
import tkinter as tk
from tkinter import ttk
from uuid import uuid4

from model import (CLASSES, ROLES, Observation, PartyReading, Profile, ReminderEngine,
                   Rule, Tracker, number, text)
from storage import ProfileStore
from search_filters import SearchFilterStore
from ui_layout import ScrollPage, WrapRow
from professions_ui import ProfessionUI
from inventory_ui import InventoryUI
from gear_ui import GearUI
from catalogue import ItemCatalogue
from prices_ui import PriceJournalUI
from preferences_ui import PreferencesUI, SupportUI


BG = "#101722"
CARD = "#1b2635"
FIELD = "#111c2a"
FG = "#edf3fa"
MUTED = "#a8b8cb"
ACCENT = "#75ddcb"
AMBER = "#ffd084"
RED = "#ff929e"
SCENARIOS = ("Calm", "Low HP", "Missing buff", "Cooldown ending", "Uncertain readings", "Custom")
KINDS = {"Low HP": "health", "Missing buff": "buff", "Cooldown finished": "cooldown"}
PLAYBACK_FRAME_MS = 33
IDLE_FRAME_MS = 100
RULE_CHECK_SECONDS = 0.1


def configure_changed(widget, **options):
    """Avoid invalidating Tk widgets when their presentation is unchanged."""
    previous = getattr(widget, "_preview_options", {})
    changed = {key: value for key, value in options.items() if previous.get(key) != value}
    if changed:
        widget.configure(**changed)
        previous.update(changed)
        widget._preview_options = previous


def set_changed(variable, value):
    # A repeated Tk variable write still runs traces and repaints linked scales.
    if variable.get() != value:
        variable.set(value)


def duration(value):
    if value is None:
        return "Unknown"
    seconds = max(0, int(value + 0.999))
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds >= 60 else f"{seconds}s"


class HealthMeter(ttk.Frame):
    def __init__(self, parent, heading):
        super().__init__(parent, style="FantasyCard.TFrame", padding=(16, 12))
        self.heading = ttk.Label(self, text=heading, style="FantasyHeading.TLabel")
        self.heading.pack(fill="x")
        self.value_label = ttk.Label(self, text="100%", style="Value.Card.TLabel")
        self.value_label.pack(anchor="w", pady=(3, 8))
        self.bar = tk.Canvas(self, height=14, background=CARD, highlightthickness=0)
        self.bar.pack(fill="x")
        self.note = ttk.Label(self, text="Simulated HP", style="Muted.Card.TLabel")
        self.note.pack(anchor="w", pady=(7, 0))
        self.value = 100
        self.colour = ACCENT
        self.track_item = self.bar.create_rectangle(0, 0, 1, 14, fill=FIELD, outline="")
        self.fill_item = self.bar.create_rectangle(0, 0, 1, 14, fill=self.colour, outline="")
        self.drawn_state = None
        self.bar.bind("<Configure>", lambda _event: self.draw())

    def draw(self):
        width = max(1, self.bar.winfo_width())
        state = (width, self.value, self.colour)
        if state == self.drawn_state:
            return
        previous = self.drawn_state
        if previous is None or width != previous[0]:
            self.bar.coords(self.track_item, 0, 0, width, 14)
        if self.value is None:
            if previous is None or previous[1] is not None:
                self.bar.itemconfigure(self.fill_item, state="hidden")
        else:
            self.bar.coords(self.fill_item, 0, 0, width * self.value / 100, 14)
            if previous is None or previous[1] is None or previous[2] != self.colour:
                self.bar.itemconfigure(self.fill_item, state="normal", fill=self.colour)
        self.drawn_state = state

    def update_reading(self, label, value, reason="Simulated HP"):
        configure_changed(self.heading, text=label)
        self.value = value
        self.colour = (getattr(self, "theme_red", RED) if value is not None and value < 40
                       else getattr(self, "theme_accent", ACCENT))
        configure_changed(self.value_label, text="Unknown" if value is None else f"{value:.0f}%",
                          foreground=getattr(self, "theme_muted", MUTED) if value is None else self.colour)
        configure_changed(self.note, text=reason)
        self.draw()


class PreviewApp:
    def __init__(self, root, state_directory):
        self.root = root
        self.root.title("WoW Forever · Offline Preview")
        self.root.geometry("1040x840")
        self.root.minsize(900, 800)
        self.root.configure(background=BG)
        from window_placement import WindowPlacement
        self.window_placement = WindowPlacement(root, state_directory)
        self.store = ProfileStore(state_directory)
        self.profiles, active = self.store.load()
        self.item_search_filters = SearchFilterStore(self.store.directory)
        self.saved_profile_ids = {p.id for p in self.profiles} if self.store.path.exists() and not self.store.error else set()
        self.profile = next(p for p in self.profiles if p.id == active)
        self.engine = ReminderEngine()
        self.playing = False
        self.play_started = 0.0
        self.frozen_at = None
        self.updating = False
        self.dirty = False
        self.previous_codes = {}
        self.log_rows = []
        self.notice_count = 0
        self.last_sound = -10.0
        self.advanced = True
        self.last_observation = None
        self.last_decisions = []
        self.last_notices = []
        self.last_rule_key = None
        self.next_rule_check = 0.0
        self.next_frame_at = None
        self.frame_interval = None
        self.rendered_rows = {}
        self.rendered_order = ()
        self.after_id = None
        self.paused = tk.BooleanVar(value=False)
        self.sound = tk.BooleanVar(value=False)
        self.large_text = tk.BooleanVar(value=False)
        self.own_hp = tk.DoubleVar(value=100)
        self.party_hp = tk.DoubleVar(value=82)
        self.cooldown = tk.DoubleVar(value=15)
        self.buff = tk.StringVar(value="Present")
        self.buff_remaining = 60.0
        self.source_mode = tk.StringVar(value="Normal")
        self.identity = tk.BooleanVar(value=True)
        self.scenario = tk.StringVar(value="Calm")
        self.tracker_values = {}
        self.tracker_rows = {}
        self.primary_unknown = {"self": False, "party": False, "cooldown": False}
        self._reset_tracking()
        self._styles()
        self._build()
        self._load_profile_form()
        self._load_rules()
        self.root.report_callback_exception = self._callback_error
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._log("Session", "Started", "Offline simulator only. No game connection or input backend.")
        if self.store.error:
            self.settings_notice.configure(text=self.store.error, foreground=RED)
            self.save_button.state(["disabled"])
            self._log("Settings", "Preserved", self.store.error)
        self._apply_view()
        self._tick()

    def _styles(self):
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#344d60")
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.style.configure(".", font=("Segoe UI", 10), background=BG, foreground=FG)
        self.style.configure("TFrame", background=BG)
        self.style.configure("Card.TFrame", background=CARD)
        self.style.configure("TLabel", background=BG, foreground=FG)
        self.style.configure("Muted.TLabel", foreground=MUTED)
        self.style.configure("Card.TLabel", background=CARD)
        self.style.configure("Muted.Card.TLabel", background=CARD, foreground=MUTED)
        self.style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
        self.style.configure("Value.Card.TLabel", background=CARD, font=("Segoe UI", 26, "bold"))
        self.style.configure("Heading.Card.TLabel", background=CARD, font=("Segoe UI", 12, "bold"))
        self.style.configure("TButton", background="#293a4d", foreground=FG, borderwidth=0,
                             padding=(12, 7), focusthickness=2, focuscolor=ACCENT)
        self.style.map("TButton", background=[("active", "#3a526b")],
                       foreground=[("disabled", "#77889b")])
        self.style.configure("Primary.TButton", background=ACCENT, foreground=BG)
        self.style.map("Primary.TButton", background=[("active", "#a0f2e2"), ("disabled", "#344755")])
        self.style.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG,
                             bordercolor="#3e536c", padding=5)
        self.style.configure("TCombobox", fieldbackground=FIELD, foreground=FG,
                             arrowcolor=FG, background="#293a4d", padding=4)
        self.style.map("TCombobox", fieldbackground=[("readonly", FIELD), ("disabled", CARD)],
                       foreground=[("readonly", FG), ("disabled", MUTED)])
        self.style.configure("TSpinbox", fieldbackground=FIELD, foreground=FG,
                             arrowcolor=FG, background="#293a4d", padding=4)
        self.style.map("TSpinbox", foreground=[("disabled", MUTED)])
        self.style.configure("TCheckbutton", background=BG, foreground=FG)
        self.style.map("TCheckbutton", background=[("active", BG)])
        self.style.configure("TScale", background=BG, troughcolor=FIELD)
        self.style.configure("TNotebook", background=BG, borderwidth=0)
        self.style.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(6, 9))
        self.style.map("TNotebook.Tab", background=[("selected", "#293a4d")],
                       foreground=[("selected", FG)])
        self.style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=FG,
                             borderwidth=0, rowheight=29)
        self.style.map("Treeview", background=[("selected", "#34556a")])
        self.style.configure("Treeview.Heading", background="#293a4d", foreground=FG,
                             relief="flat", padding=5)
        self.style.configure("Vertical.TScrollbar", background="#344b60", troughcolor=BG,
                             arrowcolor=MUTED)

    def _build(self):
        outer = ttk.Frame(self.root, padding=(22, 12))
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="WoW Forever", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="  OFFLINE PREVIEW", foreground=ACCENT).pack(side="left", padx=12)
        intro_row = ttk.Frame(outer)
        intro_row.pack(fill="x", pady=(3, 13))
        self.intro = ttk.Label(intro_row, style="Muted.TLabel")
        self.intro.pack(anchor="w")
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="Character profile").pack(side="left")
        self.profile_selector = ttk.Combobox(toolbar, state="readonly", width=25,
                                             values=[p.name for p in self.profiles])
        self.profile_selector.pack(side="left", padx=(10, 16))
        self.profile_selector.current(self.profiles.index(self.profile))
        self.profile_selector.bind("<<ComboboxSelected>>", self._switch_profile)
        self.role_label = ttk.Label(toolbar, style="Muted.TLabel")
        self.role_label.pack(side="left")
        # Hidden editor pages must not set the everyday page's minimum size.
        self.artwork = ttk.Label(outer, anchor="center")
        self.navigation = WrapRow(outer)
        self.navigation.pack(fill="x", pady=(0, 6))
        self.style.layout("Pages.TNotebook.Tab", [])
        self.tabs = ttk.Notebook(outer, width=1, height=1, style="Pages.TNotebook")
        self.tabs.pack(fill="both", expand=True)
        self.overview = ttk.Frame(self.tabs, style="Fantasy.TFrame", padding=6)
        ttk.Label(self.overview, text="Overview", style="FantasyTitle.TLabel").pack(fill="x", pady=(0, 8))
        self.settings = ttk.Frame(self.tabs, padding=(0, 14, 0, 0))
        self.tracking = ttk.Frame(self.tabs, padding=(0, 14, 0, 0))
        self.activity = ttk.Frame(self.tabs, padding=(0, 14, 0, 0))
        self.tabs.add(self.overview, text="Overview")
        self.tabs.add(self.settings, text="Profiles & Rules")
        self.tabs.add(self.tracking, text="Party & Trackers")
        self.tabs.add(self.activity, text="Activity")
        for name in ("overview", "settings", "tracking"):
            page = ScrollPage(getattr(self, name))
            page.pack(fill="both", expand=True)
            setattr(self, f"{name}_scroll", page)
            setattr(self, f"{name}_content", page.inner)
        self._overview()
        self._settings()
        self._tracking()
        self._activity()
        self.catalogue = ItemCatalogue(self.store.directory)
        self.profession_pages = ProfessionUI(self)
        self.gathering = self.profession_pages.gathering
        self.crafting = self.profession_pages.crafting
        self.tabs.insert(1, self.gathering, text="Gathering")
        self.tabs.insert(2, self.crafting, text="Crafting")
        self.inventory_page = InventoryUI(self)
        self.inventory = self.inventory_page.page
        self.tabs.insert(3, self.inventory, text="Inventory & Bank")
        self.gear_page = GearUI(self)
        self.gear = self.gear_page.page
        self.tabs.insert(4, self.gear, text="Gear wishlist")
        self.price_journal = PriceJournalUI(self)
        self.support_page = SupportUI(self)
        self.preferences = PreferencesUI(self, self.navigation, self.artwork)
        footer = ttk.Frame(outer)
        footer.pack(side="bottom", fill="x", pady=(12, 0), before=self.tabs)
        self.data_status = ttk.Label(footer, text="Manual simulation", style="Muted.TLabel")
        self.data_status.pack(side="left")
        self.pause_button = ttk.Button(footer, text="Pause reminders", command=self.toggle_pause)
        self.pause_button.pack(side="right")
        self.unsaved = ttk.Label(footer, text="", foreground=AMBER)
        self.unsaved.pack(side="right", padx=12)
        # Footer is created after Settings; apply the saved skin to it as well.
        import fantasy_style
        display = self.preferences.runtime_data
        fantasy_style.apply_workspace(self, self.preferences.page, display.get("ui_style", "WoW"),
                                      display.get("font_family", "Segoe UI"), display["text_size"])
        self.preferences.highlight()

    def _overview(self):
        self.overview_content.columnconfigure(0, weight=1)
        self.overview_content.rowconfigure(2, weight=1)
        readings = ttk.Frame(self.overview_content)
        readings.grid(row=0, column=0, sticky="ew")
        for c in range(3):
            readings.columnconfigure(c, weight=1, uniform="readings")
        self.own_meter = HealthMeter(readings, "YOUR HP")
        self.own_meter.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.party_meter = HealthMeter(readings, "PARTY MEMBER")
        self.party_meter.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        tracking = ttk.Frame(readings, style="FantasyCard.TFrame", padding=16)
        tracking.grid(row=0, column=2, sticky="nsew")
        self.buff_title = ttk.Label(tracking, text="Tracked buff", style="Muted.Card.TLabel")
        self.buff_title.pack(anchor="w")
        self.buff_status = ttk.Label(tracking, text="Present", style="Heading.Card.TLabel")
        self.buff_status.pack(anchor="w", pady=(3, 12))
        self.cooldown_title = ttk.Label(tracking, text="Tracked ability", style="Muted.Card.TLabel")
        self.cooldown_title.pack(anchor="w")
        self.cooldown_status = ttk.Label(tracking, text="15s", style="Heading.Card.TLabel")
        self.cooldown_status.pack(anchor="w", pady=(3, 0))
        ttk.Label(tracking, text="Castability is not simulated", style="Muted.Card.TLabel").pack(anchor="w", pady=(6, 0))
        proposal = ttk.Frame(self.overview_content, style="FantasyCard.TFrame", padding=16)
        proposal.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        self.reminder_heading = ttk.Label(proposal, text="REMINDER", style="FantasyHeading.TLabel")
        self.reminder_heading.pack(fill="x")
        self.proposal = ttk.Label(proposal, text="No proposed action", style="Heading.Card.TLabel", wraplength=850)
        self.proposal.pack(anchor="w", pady=(5, 3))
        self.proposal_detail = ttk.Label(proposal, text="", style="Muted.Card.TLabel", wraplength=850)
        self.proposal_detail.pack(anchor="w")
        self.tracker_summary = ttk.Label(proposal, text="", style="Muted.Card.TLabel", wraplength=850)
        self.tracker_summary.pack(anchor="w", pady=(6, 0))
        list_frame = ttk.Frame(self.overview_content)
        self.rule_panel = list_frame
        list_frame.grid(row=2, column=0, sticky="nsew")
        self.decision_tree = ttk.Treeview(list_frame, columns=("state", "reason"), height=4,
                                          selectmode="none")
        self.decision_tree.heading("#0", text="Rule")
        self.decision_tree.column("#0", width=180, minwidth=120, stretch=False)
        self.decision_tree.heading("state", text="State")
        self.decision_tree.column("state", width=110, minwidth=95, stretch=False)
        self.decision_tree.heading("reason", text="Why")
        self.decision_tree.column("reason", width=560)
        self.decision_tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(list_frame, command=self.decision_tree.yview)
        scroll.pack(side="right", fill="y")
        self.decision_tree.configure(yscrollcommand=scroll.set)
        self.decision_tree.tag_configure("active", foreground=ACCENT)
        self.decision_tree.tag_configure("blocked", foreground=AMBER)
        self.decision_tree.tag_configure("disabled", foreground=MUTED)
        self.latest = ttk.Label(self.overview_content, text="No reminders yet", style="Muted.TLabel")
        self.latest.grid(row=3, column=0, sticky="w", pady=(9, 8))
        self.simulation_panel = ttk.Frame(self.overview_content)
        self.simulation_panel.grid(row=4, column=0, sticky="ew")
        top = ttk.Frame(self.simulation_panel)
        top.pack(fill="x", pady=(4, 8))
        ttk.Label(top, text="Try example", font=("Segoe UI", 11, "bold")).pack(side="left")
        scenario = ttk.Combobox(top, values=SCENARIOS, textvariable=self.scenario,
                                state="readonly", width=20)
        scenario.pack(side="left", padx=12)
        scenario.bind("<<ComboboxSelected>>", lambda _event: self.select_scenario(self.scenario.get()))
        self.play_button = ttk.Button(top, text="Play demo", command=self.toggle_demo)
        self.play_button.pack(side="left")
        ttk.Button(top, text="Reset", command=lambda: self.select_scenario("Calm")).pack(side="left", padx=8)
        self.manual_panel = ttk.Frame(self.simulation_panel)
        self.manual_panel.pack(fill="x")
        controls = ttk.Frame(self.manual_panel)
        controls.pack(fill="x")
        for col, (label, variable, maximum) in enumerate([
                ("Your HP %", self.own_hp, 100), ("Party HP %", self.party_hp, 100),
                ("Cooldown seconds", self.cooldown, 120)]):
            controls.columnconfigure(col, weight=1, uniform="sliders")
            group = ttk.Frame(controls, padding=(0, 0, 16 if col < 2 else 0, 0))
            group.grid(row=0, column=col, sticky="ew")
            row = ttk.Frame(group)
            row.pack(fill="x")
            ttk.Label(row, text=label).pack(side="left")
            value = ttk.Label(row, width=5, anchor="e", style="Muted.TLabel")
            value.pack(side="right")
            variable.trace_add("write", lambda *_args, v=variable, w=value: configure_changed(w, text=f"{v.get():.0f}"))
            value.configure(text=f"{variable.get():.0f}")
            ttk.Scale(group, variable=variable, from_=0, to=maximum, length=230,
                       command=lambda value, k=("self", "party", "cooldown")[col]: self._manual_slider(k, value)).pack(anchor="w", pady=(4, 0))
        options = ttk.Frame(self.manual_panel)
        options.pack(fill="x", pady=(10, 0))
        ttk.Label(options, text="Buff").pack(side="left")
        buff = ttk.Combobox(options, values=("Present", "Missing", "Unknown"),
                            textvariable=self.buff, state="readonly", width=10)
        buff.pack(side="left", padx=(7, 18))
        buff.bind("<<ComboboxSelected>>", self._manual_change)
        ttk.Label(options, text="Readings").pack(side="left")
        source = ttk.Combobox(options, values=("Normal", "Unknown", "Frozen"),
                              textvariable=self.source_mode, state="readonly", width=10)
        source.pack(side="left", padx=(7, 18))
        source.bind("<<ComboboxSelected>>", self._source_changed)
        ttk.Checkbutton(options, text="Party identity confirmed", variable=self.identity,
                        command=self._manual_change).pack(side="left")

    def _entry(self, parent, label, variable, row, column, width=22):
        ttk.Label(parent, text=label, style="Muted.TLabel").grid(row=row, column=column, sticky="w", pady=(4, 3))
        entry = ttk.Entry(parent, textvariable=variable, width=width)
        entry.grid(row=row + 1, column=column, sticky="ew", padx=(0, 12), pady=(0, 5))
        return entry

    def _settings(self):
        info = ttk.Frame(self.settings_content)
        info.pack(fill="x")
        self.profile_vars = {name: tk.StringVar() for name in
                             ("name", "character_class", "role", "party_name", "buff_name", "cooldown_name", "level")}
        for variable in self.profile_vars.values():
            variable.trace_add("write", lambda *_args: self._mark_dirty() if not self.updating else None)
        for col in range(3):
            info.columnconfigure(col, weight=1, uniform="profile")
        self._entry(info, "Profile name", self.profile_vars["name"], 0, 0)
        for col, (key, label, values) in enumerate([
                ("character_class", "Class (optional)", CLASSES), ("role", "Role", ROLES)], 1):
            ttk.Label(info, text=label, style="Muted.TLabel").grid(row=0, column=col, sticky="w", pady=(4, 3))
            ttk.Combobox(info, textvariable=self.profile_vars[key], values=values,
                          state="readonly").grid(row=1, column=col, sticky="ew", padx=(0, 12), pady=(0, 5))
        for col, (key, label) in enumerate([("party_name", "Party member label"),
                                           ("buff_name", "Buff label"), ("cooldown_name", "Cooldown label")]):
            self._entry(info, label, self.profile_vars[key], 2, col)
        self.level_entry = self._entry(info, "Character level (optional)", self.profile_vars["level"], 4, 0)
        ttk.Label(info, text="Blank = Unknown · Manually entered", style="Muted.TLabel").grid(
            row=5, column=1, columnspan=2, sticky="w")
        actions = ttk.Frame(self.settings_content)
        actions.pack(fill="x", pady=(4, 12))
        ttk.Button(actions, text="New character", command=self.new_profile).pack(side="left")
        ttk.Button(actions, text="Duplicate profile", command=lambda: self.new_profile(True)).pack(side="left", padx=8)
        self.save_button = ttk.Button(actions, text="Save profiles", style="Primary.TButton", command=self.save_profiles)
        self.save_button.pack(side="right")
        body = ttk.Frame(self.settings_content)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", padx=(0, 18))
        self.rule_tree = ttk.Treeview(left, columns=("on",), height=7, selectmode="browse")
        self.rule_tree.heading("#0", text="Reminder rules")
        self.rule_tree.column("#0", width=190, minwidth=140)
        self.rule_tree.heading("on", text="On")
        self.rule_tree.column("on", width=42, stretch=False)
        self.rule_tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(left, command=self.rule_tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.rule_tree.configure(yscrollcommand=scrollbar.set)
        self.rule_tree.bind("<<TreeviewSelect>>", self._rule_selected)
        editor = ttk.Frame(body)
        editor.pack(side="left", fill="both", expand=True)
        for col in range(3):
            editor.columnconfigure(col, weight=1)
        self.rule_vars = {key: tk.StringVar() for key in
                          ("name", "kind", "target", "threshold", "recovery", "delay", "repeat", "priority", "message", "binding")}
        self.rule_source = tk.StringVar()
        self.rule_gate = tk.StringVar()
        self.rule_enabled = tk.BooleanVar(value=True)
        self.rule_require_cd = tk.BooleanVar(value=False)
        self._entry(editor, "Rule name", self.rule_vars["name"], 0, 0)
        ttk.Label(editor, text="Trigger", style="Muted.TLabel").grid(row=0, column=1, sticky="w")
        trigger = ttk.Combobox(editor, textvariable=self.rule_vars["kind"], values=tuple(KINDS), state="readonly", width=18)
        trigger.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(0, 5))
        trigger.bind("<<ComboboxSelected>>", lambda _event: self._rule_fields())
        ttk.Label(editor, text="Tracked source", style="Muted.TLabel").grid(row=2, column=0, sticky="w")
        self.target_field = ttk.Combobox(editor, textvariable=self.rule_source,
                                         state="readonly", width=16)
        self.target_field.grid(row=3, column=0, sticky="ew", padx=(0, 12))
        self.numeric_fields = {}
        for row, items in [(2, [("threshold", "Below HP %", 1, 99), ("recovery", "Clear at HP %", 2, 100)]),
                           (4, [("delay", "Confirm seconds", 0, 60), ("repeat", "Repeat seconds", 0, 3600), ("priority", "Priority · 1 first", 1, 9)])]:
            offset = 1 if row == 2 else 0
            for col, (key, label, low, high) in enumerate(items, offset):
                ttk.Label(editor, text=label, style="Muted.TLabel").grid(row=row, column=col, sticky="w", pady=(6, 3))
                widget = ttk.Spinbox(editor, textvariable=self.rule_vars[key], from_=low, to=high,
                                      increment=0.5 if key == "delay" else 1, width=10)
                widget.grid(row=row + 1, column=col, sticky="ew", padx=(0, 12), pady=(0, 5))
                self.numeric_fields[key] = widget
        ttk.Label(editor, text="Reminder / proposed action", style="Muted.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 3))
        ttk.Entry(editor, textvariable=self.rule_vars["message"]).grid(row=7, column=0, columnspan=3, sticky="ew")
        ttk.Label(editor, text="Binding label · text only", style="Muted.TLabel").grid(row=8, column=0, columnspan=3, sticky="w", pady=(8, 3))
        ttk.Entry(editor, textvariable=self.rule_vars["binding"]).grid(row=9, column=0, columnspan=3, sticky="ew")
        ttk.Checkbutton(editor, text="Rule enabled", variable=self.rule_enabled).grid(row=10, column=0, sticky="w", pady=(10, 3))
        self.require_cd_field = ttk.Checkbutton(editor, text="Require tracked cooldown ready",
                                                variable=self.rule_require_cd, command=self._rule_gate_state)
        self.require_cd_field.grid(row=10, column=1, columnspan=2, sticky="w", pady=(10, 3))
        bottom = ttk.Frame(editor)
        self.gate_field = ttk.Combobox(editor, textvariable=self.rule_gate, state="disabled", width=24)
        self.gate_field.grid(row=11, column=1, columnspan=2, sticky="ew", pady=(3, 0))
        bottom.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.apply_rule_button = ttk.Button(bottom, text="Apply rule", style="Primary.TButton", command=self.apply_rule)
        self.apply_rule_button.pack(side="left")
        ttk.Button(bottom, text="Add rule", command=self.add_rule).pack(side="left", padx=8)
        ttk.Label(self.settings_content, text="Repeat 0 = once per episode. Apply rule, then Save profiles to keep your changes.",
                  style="Muted.TLabel").pack(anchor="w", pady=(10, 4))
        self.settings_notice = ttk.Label(self.settings_content, text="Profiles stay local. All spells and bindings are labels.",
                                          style="Muted.TLabel", wraplength=900)
        self.settings_notice.pack(anchor="w")

    def _reset_tracking(self):
        """Simulation values are session-only; each profile switch starts fresh."""
        self.tracker_values = {}
        self.primary_unknown = {"self": False, "party": False, "cooldown": False}
        for kind in ("party", "buff", "cooldown"):
            for index, tracker in enumerate(self.profile.trackers(kind)[1:], 1):
                self.tracker_values[(kind, tracker.id)] = {
                    "value": 90 - index * 8 if kind == "party" else "Present" if kind == "buff" else 15 + index * 10,
                    "identity": True, "remaining": 60.0}

    def _tracking(self):
        ttk.Label(self.tracking_content, text="Your character + four party members · Independent buff and cooldown trackers",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        panel = ttk.Frame(self.tracking_content)
        panel.pack(fill="both", expand=True)
        self.tracker_tree = ttk.Treeview(panel, columns=("kind", "reading"), height=8, selectmode="browse")
        self.tracker_tree.heading("#0", text="Tracker")
        self.tracker_tree.column("#0", width=250, minwidth=180)
        for key, label, width in (("kind", "Type", 95), ("reading", "Simulated reading", 450)):
            self.tracker_tree.heading(key, text=label)
            self.tracker_tree.column(key, width=width, minwidth=80, stretch=key == "reading")
        self.tracker_tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(panel, command=self.tracker_tree.yview)
        scroll.pack(side="right", fill="y")
        self.tracker_tree.configure(yscrollcommand=scroll.set)
        self.tracker_tree.bind("<<TreeviewSelect>>", self._tracker_selected)
        actions = ttk.Frame(self.tracking_content)
        actions.pack(fill="x", pady=(10, 7))
        ttk.Button(actions, text="Add buff", command=lambda: self.add_tracker("buff")).pack(side="left")
        ttk.Button(actions, text="Add cooldown", command=lambda: self.add_tracker("cooldown")).pack(side="left", padx=8)
        ttk.Button(actions, text="Add reminder for selected", command=self.add_tracker_rule).pack(side="left")
        ttk.Button(actions, text="Save profiles", style="Primary.TButton", command=self.save_profiles).pack(side="right")
        editor = ttk.Frame(self.tracking_content)
        editor.pack(fill="x")
        for col in range(3):
            editor.columnconfigure(col, weight=1)
        self.tracker_name = tk.StringVar()
        self.tracker_number = tk.StringVar()
        self.tracker_buff = tk.StringVar(value="Present")
        self.tracker_known = tk.BooleanVar(value=True)
        self.tracker_identity = tk.BooleanVar(value=True)
        self.tracker_name_field = self._entry(editor, "Display name", self.tracker_name, 0, 0)
        self.tracker_value_label = ttk.Label(editor, text="HP %", style="Muted.TLabel")
        self.tracker_value_label.grid(row=0, column=1, sticky="w", pady=(4, 3))
        self.tracker_number_field = ttk.Spinbox(editor, textvariable=self.tracker_number, from_=0, to=100, width=15)
        self.tracker_number_field.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(0, 5))
        self.tracker_buff_field = ttk.Combobox(editor, textvariable=self.tracker_buff,
                                               values=("Present", "Missing", "Unknown"), state="readonly")
        self.tracker_buff_field.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(0, 5))
        self.tracker_known_field = ttk.Checkbutton(editor, text="Reading known", variable=self.tracker_known)
        self.tracker_known_field.grid(row=0, column=2, sticky="w", pady=(4, 3))
        self.tracker_identity_field = ttk.Checkbutton(editor, text="Identity confirmed", variable=self.tracker_identity)
        self.tracker_identity_field.grid(row=1, column=2, sticky="w")
        bottom = ttk.Frame(self.tracking_content)
        bottom.pack(fill="x", pady=(8, 7))
        ttk.Button(bottom, text="Apply tracker / reading", command=self.apply_tracker,
                   style="Primary.TButton").pack(side="left")
        ttk.Button(bottom, text="Reload current reading", command=self._tracker_selected).pack(side="left", padx=8)
        self.tracking_notice = ttk.Label(self.tracking_content, text="Names and rule sources save with profiles. Readings are session-only.",
                                          style="Muted.TLabel", wraplength=900)
        self.tracking_notice.pack(anchor="w")

    def _load_trackers(self, selected=None):
        self.tracker_tree.delete(*self.tracker_tree.get_children())
        self.tracker_rows.clear()
        self.tracker_tree.insert("", "end", iid="self/primary", text="Your HP", values=("You", ""))
        for kind in ("party", "buff", "cooldown"):
            for tracker in self.profile.trackers(kind):
                self.tracker_tree.insert("", "end", iid=f"{kind}/{tracker.id}", text=tracker.name,
                                         values=(kind.capitalize(), ""))
        selected = selected if selected and self.tracker_tree.exists(selected) else "self/primary"
        self.tracker_tree.selection_set(selected)
        self.tracker_tree.focus(selected)
        self._tracker_selected()

    def _tracker_selected(self, _event=None):
        selection = self.tracker_tree.selection()
        if not selection:
            return
        kind, tracker_id = selection[0].split("/", 1)
        if kind == "self":
            label, value, identity = "Your HP", self.own_hp.get(), True
        elif tracker_id == "primary":
            label = self.profile.trackers(kind)[0].name
            value = {"party": self.party_hp, "buff": self.buff, "cooldown": self.cooldown}[kind].get()
            identity = self.identity.get()
        else:
            label = next(t.name for t in self.profile.trackers(kind) if t.id == tracker_id)
            reading = self.tracker_values[(kind, tracker_id)]
            value, identity = reading["value"], reading["identity"]
        known = value is not None and not (tracker_id == "primary" and self.primary_unknown.get(kind, False))
        self.tracker_name.set(label)
        self.tracker_name_field.configure(state="disabled" if kind == "self" else "normal")
        self.tracker_number.set("0" if value is None or kind == "buff" else f"{value:g}")
        self.tracker_buff.set(value if kind == "buff" else "Present")
        self.tracker_known.set(known)
        self.tracker_identity.set(identity)
        self.tracker_identity_field.configure(state="normal" if kind == "party" else "disabled")
        self.tracker_known_field.configure(state="disabled" if kind == "buff" else "normal")
        self.tracker_value_label.configure(text="Buff state" if kind == "buff" else "Cooldown seconds" if kind == "cooldown" else "HP %")
        if kind == "buff":
            self.tracker_number_field.grid_remove()
            self.tracker_buff_field.grid()
        else:
            self.tracker_buff_field.grid_remove()
            self.tracker_number_field.grid()
            self.tracker_number_field.configure(to=3600 if kind == "cooldown" else 100)

    def apply_tracker(self):
        selection = self.tracker_tree.selection()
        if not selection:
            return False
        kind, tracker_id = selection[0].split("/", 1)
        try:
            name = text(self.tracker_name.get(), "Tracker name")
            value = self.tracker_buff.get() if kind == "buff" else (
                number(float(self.tracker_number.get()), "Simulated reading", 0, 3600 if kind == "cooldown" else 100)
                if self.tracker_known.get() else None)
            if kind == "buff" and value not in ("Present", "Missing", "Unknown"):
                raise ValueError("Choose a listed buff state.")
            candidate = deepcopy(self.profile)
            if kind != "self":
                if tracker_id == "primary":
                    setattr(candidate, {"party": "party_name", "buff": "buff_name", "cooldown": "cooldown_name"}[kind], name)
                else:
                    next(t for t in getattr(candidate, {"party": "party_members", "buff": "buffs", "cooldown": "cooldowns"}[kind])
                         if t.id == tracker_id).name = name
            candidate.validate()
        except ValueError as exc:
            self._error(exc)
            return False
        if candidate != self.profile:
            self.profiles[self.profiles.index(self.profile)] = candidate
            self.profile = candidate
            if tracker_id == "primary" and kind != "self":
                self.profile_vars[{"party": "party_name", "buff": "buff_name", "cooldown": "cooldown_name"}[kind]].set(name)
            self._mark_dirty()
            self.engine.reset()
            self.previous_codes.clear()
        self._manual_change()
        if tracker_id == "primary":
            if kind == "buff":
                self.buff.set(value)
                self.buff_remaining = 60 if value == "Present" else 0
            else:
                self.primary_unknown[kind] = value is None
                if value is not None:
                    {"self": self.own_hp, "party": self.party_hp, "cooldown": self.cooldown}[kind].set(value)
                if kind == "party":
                    self.identity.set(self.tracker_identity.get())
        else:
            self.tracker_values[(kind, tracker_id)].update(value=value, identity=self.tracker_identity.get(), remaining=60 if value == "Present" else 0)
        self._load_trackers(selection[0])
        self._rule_fields()
        configure_changed(self.tracking_notice, text="Tracker applied. Save profiles to keep names and rules; readings stay in this session.", foreground=ACCENT)
        return True

    def add_tracker(self, kind):
        extras = getattr(self.profile, "buffs" if kind == "buff" else "cooldowns")
        if len(extras) >= 7:
            self._error(ValueError("This preview supports up to eight trackers in each buff/cooldown category."))
            return
        tracker = Tracker(uuid4().hex, f"{'Buff' if kind == 'buff' else 'Ability'} {len(extras) + 2}")
        extras.append(tracker)
        self.tracker_values[(kind, tracker.id)] = {"value": "Unknown" if kind == "buff" else None,
                                                   "identity": True, "remaining": 0}
        self._mark_dirty()
        self._load_trackers(f"{kind}/{tracker.id}")
        self._rule_fields()

    def add_tracker_rule(self):
        selection = self.tracker_tree.selection()
        if not selection:
            return
        if len(self.profile.rules) >= 30:
            self._error(ValueError("This profile already has 30 rules."))
            return
        kind, tracker_id = selection[0].split("/", 1)
        label = "Your HP" if kind == "self" else next(t.name for t in self.profile.trackers(kind) if t.id == tracker_id)
        trigger = "health" if kind in ("self", "party") else kind
        rule = Rule(uuid4().hex, f"{label[:60]} reminder", trigger, target="party" if kind == "party" else "self",
                    tracker_id=tracker_id, delay=3 if kind == "buff" else 0 if kind == "cooldown" else 0.5,
                    message=f"Check {label[:100]}")
        self.profile.rules.append(rule)
        self._load_rules(rule.id)
        self.engine.reset()
        self._mark_dirty()
        if not self.advanced:
            self.advanced = True
            self._apply_view()
        self.tabs.select(self.settings)

    def _source_choices(self, kind):
        choices = {"Your HP": ("self", "primary")} if kind == "health" else {}
        group = "party" if kind == "health" else kind
        choices.update({f"{index} · {tracker.name[:40]}": ("party" if kind == "health" else "self", tracker.id)
                        for index, tracker in enumerate(self.profile.trackers(group), 1)})
        return choices

    def _rule_gate_state(self):
        self.gate_field.configure(state="readonly" if self.rule_require_cd.get() and self.rule_vars["kind"].get() != "Cooldown finished" else "disabled")

    def _render_tracking(self, observation, valid, reason):
        rows = [("self/primary", "Your HP", "You", "Unknown" if not valid or observation.own_hp is None else f"{observation.own_hp:g}%")]
        for kind in ("party", "buff", "cooldown"):
            for tracker in self.profile.trackers(kind):
                if kind == "party":
                    reading = observation.party_value(tracker.id)
                    value = "Identity needs confirmation" if not reading.identity_confirmed else "Unknown" if not valid or reading.hp is None else f"{reading.hp:g}%"
                elif kind == "buff":
                    value = observation.buff_value(tracker.id) if valid else "Unknown"
                    remaining = self.buff_remaining if tracker.id == "primary" else self.tracker_values[(kind, tracker.id)]["remaining"]
                    if value == "Present":
                        value += f" · {duration(remaining)}"
                else:
                    cooldown = observation.cooldown_value(tracker.id)
                    value = "Unknown" if not valid or cooldown is None else "Cooldown ready · castability unknown" if cooldown == 0 else f"Cooling down · {duration(cooldown)}"
                if not valid:
                    value = reason
                rows.append((f"{kind}/{tracker.id}", tracker.name, kind.capitalize(), value))
        for row_id, label, kind, value in rows:
            presentation = (label, kind, value)
            if self.tracker_rows.get(row_id) != presentation:
                self.tracker_tree.item(row_id, text=label, values=(kind, value))
                self.tracker_rows[row_id] = presentation
        party = [observation.party_value(t.id) for t in self.profile.trackers("party")]
        known_hp = [reading.hp for reading in party if valid and reading.identity_confirmed and reading.hp is not None]
        missing = sum(observation.buff_value(t.id) == "Missing" for t in self.profile.trackers("buff"))
        unknown_buffs = sum(observation.buff_value(t.id) not in ("Present", "Missing") for t in self.profile.trackers("buff"))
        ready = sum(observation.cooldown_value(t.id) == 0 for t in self.profile.trackers("cooldown"))
        unknown_cooldowns = sum(observation.cooldown_value(t.id) is None for t in self.profile.trackers("cooldown"))
        summary = (f"Party: {len(known_hp)}/{len(party)} confirmed · Lowest HP: {min(known_hp):g}%" if known_hp else "Party HP unavailable")
        summary += f" · Buffs missing: {missing} ({unknown_buffs} unknown) · Cooldowns ready: {ready} ({unknown_cooldowns} unknown)" if valid else " · Buffs and cooldowns unavailable"
        configure_changed(self.tracker_summary, text=summary)

    def _activity(self):
        ttk.Label(self.activity, text="Recent reminder and state changes · kept for this session only",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        panel = ttk.Frame(self.activity)
        panel.pack(fill="both", expand=True)
        self.log_tree = ttk.Treeview(panel, columns=("rule", "state", "detail"), show="headings")
        for key, label, width in [("rule", "Rule / source", 150), ("state", "State", 95), ("detail", "Details", 650)]:
            self.log_tree.heading(key, text=label)
            self.log_tree.column(key, width=width, minwidth=70, stretch=key == "detail")
        self.log_tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(panel, command=self.log_tree.yview)
        bar.pack(side="right", fill="y")
        self.log_tree.configure(yscrollcommand=bar.set)
        ttk.Label(self.activity, text="Only changes are logged, up to 200 rows. No game, screen or network data is read.",
                  style="Muted.TLabel").pack(anchor="w", pady=(10, 0))

    def _log(self, source, state, detail):
        row = self.log_tree.insert("", "end", values=(source, state, detail))
        self.log_rows.append(row)
        if len(self.log_rows) > 200:
            self.log_tree.delete(self.log_rows.pop(0))
        self.log_tree.see(row)

    def _mark_dirty(self):
        self.dirty = True
        self.unsaved.configure(text="Unsaved profiles")

    def _load_profile_form(self):
        was_updating = self.updating
        self.updating = True
        try:
            for key, variable in self.profile_vars.items():
                value = getattr(self.profile, key)
                variable.set("" if value is None else value)
        finally:
            self.updating = was_updating
        self.role_label.configure(text=self._profile_summary())
        self._load_trackers()
        self.profession_pages.refresh()
        self.inventory_page.refresh()
        self.gear_page.refresh()
        self.price_journal.refresh()
        self.support_page.refresh()

    def _apply_metadata(self):
        values = {k: text_value.get().strip() for k, text_value in self.profile_vars.items()}
        level = values.pop("level")
        if level and (not level.isascii() or not level.isdecimal() or len(level) > 4):
            raise ValueError("Character level must be a whole number from 1 to 1000, or blank for Unknown.")
        candidate = replace(self.profile, **values, level=int(level) if level else None)
        candidate.validate()
        if any(p.id != candidate.id and p.name.casefold() == candidate.name.casefold() for p in self.profiles):
            raise ValueError("Use a different name for each character profile.")
        changed = candidate != self.profile
        if changed:
            index = self.profiles.index(self.profile)
            self.profiles[index] = candidate
            self.profile = candidate
            self._mark_dirty()
        self.profile_selector.configure(values=[p.name for p in self.profiles])
        self.profile_selector.current(self.profiles.index(self.profile))
        self.role_label.configure(text=self._profile_summary())
        self._load_trackers(self.tracker_tree.selection()[0] if self.tracker_tree.selection() else None)
        if changed:
            self.root.event_generate("<<ProfileMetadataChanged>>")

    def _profile_summary(self):
        level = self.profile.level if self.profile.level is not None else "Unknown"
        return f"{self.profile.character_class} · {self.profile.role} · Level {level}"

    def _switch_profile(self, _event=None):
        selected = self.profile_selector.current()
        try:
            self._apply_metadata()
        except ValueError as exc:
            self._error(exc)
            self.profile_selector.current(self.profiles.index(self.profile))
            return
        self.profile = self.profiles[selected]
        self.profile_selector.current(selected)
        self.select_scenario("Calm")
        self._load_profile_form()
        self._load_rules()
        self.engine.reset()
        self.previous_codes.clear()
        self._log("Profile", "Selected", self.profile.name)

    def new_profile(self, duplicate=False):
        try:
            self._apply_metadata()
        except ValueError as exc:
            self._error(exc)
            return
        if len(self.profiles) >= 100:
            self._error(ValueError("The preview supports up to 100 characters."))
            return
        from model import default_profile
        profile = deepcopy(self.profile) if duplicate else default_profile()
        profile.id = uuid4().hex
        base = self.profile.name[:65] + " copy" if duplicate else "New character"
        name, index = base, 2
        existing = {p.name.casefold() for p in self.profiles}
        while name.casefold() in existing:
            name = f"{base[:65]} {index}"
            index += 1
        profile.name = name[:80]
        self.profiles.append(profile)
        self.profile = profile
        self.profile_selector.configure(values=[p.name for p in self.profiles])
        self.profile_selector.current(len(self.profiles) - 1)
        self.select_scenario("Calm")
        self._load_profile_form()
        self._load_rules()
        self._mark_dirty()
        self.engine.reset()
        self.previous_codes.clear()

    def _load_rules(self, selected=None):
        self.rule_tree.delete(*self.rule_tree.get_children())
        self.decision_tree.delete(*self.decision_tree.get_children())
        self.rendered_rows.clear()
        self.rendered_order = ()
        for rule in self.profile.rules:
            self.rule_tree.insert("", "end", iid=rule.id, text=rule.name,
                                   values=("Yes" if rule.enabled else "No",))
        if self.profile.rules:
            selected = selected if selected in {r.id for r in self.profile.rules} else self.profile.rules[0].id
            self.rule_tree.selection_set(selected)
            self.rule_tree.focus(selected)
            self._rule_selected()

    def _rule_selected(self, _event=None):
        selection = self.rule_tree.selection()
        if not selection:
            return
        rule = next(r for r in self.profile.rules if r.id == selection[0])
        for key, variable in self.rule_vars.items():
            value = getattr(rule, key)
            if key == "kind":
                value = next(label for label, kind in KINDS.items() if kind == value)
            elif key == "target":
                value = "Your HP" if value == "self" else "Party HP"
            elif isinstance(value, (float, int)):
                value = f"{value:g}"
            variable.set(value)
        self.rule_enabled.set(rule.enabled)
        self.rule_require_cd.set(rule.require_cooldown)
        self._rule_fields((rule.target, rule.tracker_id), rule.cooldown_id)

    def _rule_fields(self, source=None, gate=None):
        kind = KINDS.get(self.rule_vars["kind"].get(), "health")
        health = kind == "health"
        previous = getattr(self, "source_choices", {}).get(self.rule_source.get())
        self.source_choices = self._source_choices(kind)
        wanted = source or previous
        self.target_field.configure(values=tuple(self.source_choices), state="readonly")
        self.rule_source.set(next((label for label, item in self.source_choices.items() if item == wanted), next(iter(self.source_choices))))
        previous_gate = getattr(self, "gate_choices", {}).get(self.rule_gate.get())
        self.gate_choices = {label: item[1] for label, item in self._source_choices("cooldown").items()}
        self.gate_field.configure(values=tuple(self.gate_choices))
        self.rule_gate.set(next((label for label, tracker_id in self.gate_choices.items() if tracker_id == (gate or previous_gate)), next(iter(self.gate_choices))))
        for key in ("threshold", "recovery"):
            self.numeric_fields[key].configure(state="normal" if health else "disabled")
        self.require_cd_field.configure(state="disabled" if self.rule_vars["kind"].get() == "Cooldown finished" else "normal")
        self._rule_gate_state()

    def apply_rule(self):
        selection = self.rule_tree.selection()
        if not selection:
            self._error(ValueError("Select a rule first."))
            return False
        try:
            values = {k: v.get().strip() for k, v in self.rule_vars.items()}
            kind = KINDS[values["kind"]]
            target, tracker_id = self.source_choices[self.rule_source.get()]
            rule = Rule(selection[0], values["name"], kind, enabled=self.rule_enabled.get(),
                        target=target, tracker_id=tracker_id,
                        threshold=float(values["threshold"]), recovery=float(values["recovery"]),
                        delay=float(values["delay"]), repeat=float(values["repeat"]),
                        priority=int(values["priority"]),
                        require_cooldown=self.rule_require_cd.get() if kind != "cooldown" else False,
                        message=values["message"], binding=values["binding"],
                        cooldown_id=self.gate_choices[self.rule_gate.get()])
            rule.validate()
            candidate = replace(self.profile, rules=[rule if r.id == rule.id else r for r in self.profile.rules])
            candidate.validate()
        except (ValueError, KeyError) as exc:
            self._error(exc)
            return False
        index = self.profiles.index(self.profile)
        self.profiles[index] = candidate
        self.profile = candidate
        self._load_rules(rule.id)
        self._mark_dirty()
        self.engine.reset()
        self.previous_codes.clear()
        self.settings_notice.configure(text="Rule applied to this session. Save profiles to keep it.", foreground=ACCENT)
        self._log(rule.name, "Edited", "Rule updated; confirmation timers restarted.")
        return True

    def add_rule(self):
        if len(self.profile.rules) >= 30:
            self._error(ValueError("This profile already has 30 rules. Disable or edit an existing rule."))
            return
        rule = Rule(uuid4().hex, "New reminder", "health", enabled=False)
        self.profile.rules.append(rule)
        self._load_rules(rule.id)
        self._mark_dirty()

    def save_profiles(self):
        if not self.apply_rule():
            return False
        try:
            self._apply_metadata()
            self.store.save(self.profiles, self.profile.id)
        except (OSError, ValueError) as exc:
            self._error(exc)
            return False
        self.dirty = False
        self.saved_profile_ids = {p.id for p in self.profiles}
        self.unsaved.configure(text="")
        self.settings_notice.configure(text="Profiles saved locally. The previous save is kept as a backup.", foreground=ACCENT)
        self._log("Settings", "Saved", "Character profiles and rules saved locally.")
        return True

    def ensure_plan_profile(self):
        """An explicit plan save also retains a newly created character identity."""
        if self.profile.id in self.saved_profile_ids:
            return True
        try:
            self._apply_metadata()
            self.store.save(self.profiles, self.profile.id)
        except (OSError, ValueError) as exc:
            self._error(exc)
            return False
        self.saved_profile_ids = {p.id for p in self.profiles}
        self.dirty = False
        self.unsaved.configure(text="")
        return True

    def _error(self, exc):
        self.settings_notice.configure(text=f"Not applied: {exc}", foreground=RED)
        self.tracking_notice.configure(text=f"Not applied: {exc}", foreground=RED)
        self._log("Settings", "Invalid", str(exc))

    def _manual_change(self, _value=None):
        if self.updating:
            return
        self.playing = False
        self.play_button.configure(text="Play demo")
        self.scenario.set("Custom")
        if self.buff.get() == "Present" and self.buff_remaining <= 0:
            self.buff_remaining = 60

    def _manual_slider(self, kind, value):
        if not self.updating:
            self.primary_unknown[kind] = False
        self._manual_change(value)

    def _source_changed(self, _event=None):
        self._manual_change()
        self.frozen_at = time.monotonic() if self.source_mode.get() == "Frozen" else None

    def select_scenario(self, scenario):
        self.playing = False
        self.play_button.configure(text="Play demo")
        self.updating = True
        try:
            self.scenario.set(scenario)
            self.own_hp.set(100)
            self.party_hp.set(82)
            self.cooldown.set(15)
            self.buff.set("Present")
            self.buff_remaining = 60
            self.source_mode.set("Normal")
            self.identity.set(True)
            self.frozen_at = None
            self._reset_tracking()
            if scenario == "Low HP":
                self.own_hp.set(32)
                self.party_hp.set(28)
                for index, tracker in enumerate(self.profile.party_members):
                    self.tracker_values[("party", tracker.id)]["value"] = (22, 48, 65)[index]
            elif scenario == "Missing buff":
                self.buff.set("Missing")
                self.buff_remaining = 0
                for tracker in self.profile.buffs:
                    self.tracker_values[("buff", tracker.id)]["value"] = "Missing"
            elif scenario == "Cooldown ending":
                self.cooldown.set(3)
                self.playing = True
                self.play_started = time.monotonic()
                for index, tracker in enumerate(self.profile.cooldowns):
                    self.tracker_values[("cooldown", tracker.id)]["value"] = 3 + (index + 1) * 2
            elif scenario == "Uncertain readings":
                self.source_mode.set("Unknown")
        finally:
            self.updating = False
        self.engine.reset()
        self.previous_codes.clear()
        self._log("Simulation", "Scenario", scenario)
        self.play_button.configure(text="Stop playback" if self.playing else "Play demo")

    def toggle_demo(self):
        if self.playing:
            self.playing = False
            self.scenario.set("Custom")
            self.play_button.configure(text="Play demo")
            return
        self.select_scenario("Calm")
        self.scenario.set("Demo sequence")
        self.playing = True
        self.play_started = time.monotonic()
        self.play_button.configure(text="Stop playback")

    def _advance_demo(self, now):
        if not self.playing:
            return
        self.updating = True
        try:
            elapsed = now - self.play_started
            if self.scenario.get() == "Cooldown ending":
                set_changed(self.cooldown, max(0, 3 - elapsed))
                for index, tracker in enumerate(self.profile.cooldowns):
                    self.tracker_values[("cooldown", tracker.id)]["value"] = max(0, 3 + (index + 1) * 2 - elapsed)
                if elapsed >= 3 + len(self.profile.cooldowns) * 2:
                    self.playing = False
                    self.play_button.configure(text="Play demo")
                return
            t = elapsed % 40
            if t < 6:
                own, party, buff, source = 100, 82, "Present", "Normal"
            elif t < 14:
                own, party, buff, source = 32, 28, "Present", "Normal"
            elif t < 23:
                own, party, buff, source = 72, 66, "Missing", "Normal"
            elif t < 28:
                own, party, buff, source = 72, 66, "Unknown", "Unknown"
            else:
                own, party, buff, source = 90, 92, "Present", "Normal"
            set_changed(self.own_hp, own)
            set_changed(self.party_hp, party)
            set_changed(self.buff, buff)
            set_changed(self.source_mode, source)
            self.buff_remaining = max(0, 60 - t) if buff == "Present" else 0
            set_changed(self.cooldown, max(0, 15 - t) if t < 34 else 46 - t)
            for index, tracker in enumerate(self.profile.party_members):
                self.tracker_values[("party", tracker.id)]["value"] = (22, 48, 65)[index] if 6 <= t < 14 else 82 + index * 5
            for index, tracker in enumerate(self.profile.buffs):
                state = "Missing" if 14 + index * 2 <= t < 23 else "Present"
                self.tracker_values[("buff", tracker.id)].update(value=state, remaining=max(0, 60 - t) if state == "Present" else 0)
            for index, tracker in enumerate(self.profile.cooldowns):
                self.tracker_values[("cooldown", tracker.id)]["value"] = max(0, 19 + index * 4 - t) if t < 34 else 50 + index * 4 - t
        finally:
            self.updating = False

    def toggle_pause(self):
        self.paused.set(not self.paused.get())
        self.pause_button.configure(text="Resume reminders" if self.paused.get() else "Pause reminders")
        self.engine.reset()
        self.previous_codes.clear()
        self._log("Reminders", "Paused" if self.paused.get() else "Resumed", "Confirmation timers restarted; old proposals discarded.")

    def toggle_advanced(self):
        # Compatibility for older local callers; all enabled tabs remain visible.
        self._apply_view()

    def _apply_view(self):
        self.advanced = True
        self.rule_panel.grid()
        self.manual_panel.pack(fill="x")
        self.tracker_summary.pack(anchor="w", pady=(6, 0))
        self.role_label.pack(side="left")
        self.simulation_panel.grid()
        configure_changed(self.intro, text="Offline preview · Simulated combat and manual character plans")
        configure_changed(self.reminder_heading, text="HIGHEST PRIORITY REMINDER")

    def _resize_text(self):
        # Kept for old layout checks; user-facing text sizes live in Settings.
        size = 12 if self.large_text.get() else getattr(self, "text_size", 10)
        self.style.configure(".", font=("Segoe UI", size))
        self.style.configure("Treeview", rowheight=size * 2 + 9)
        self.profession_pages.ingredients.configure(font=("Segoe UI", size))
        self.root.minsize(900, 640)

    def _render_reminder(self, decisions, valid):
        detailed = self.advanced
        active = [d for d in decisions if d.code == "active"] if valid and not self.paused.get() else []
        if active:
            first = active[0]
            configure_changed(self.proposal, text=f"{first.name}: {first.message}", foreground=getattr(self, "theme_accent", ACCENT))
            detail = f"{first.detail} · Binding: {first.binding or 'not configured'} (display only)" if detailed else "Reminder only · you decide when to act."
        else:
            message = "Reminders paused" if self.paused.get() else "Readings unavailable" if not valid else (
                "Some readings are unknown" if any(d.code == "blocked" for d in decisions) else "No reminder right now")
            configure_changed(self.proposal, text=message, foreground=getattr(self, "theme_muted", MUTED))
            detail = "No keys are sent. Rules below explain their current state." if detailed else "Reminders appear here when your configured conditions are met."
        configure_changed(self.proposal_detail, text=detail)

    def _tick(self):
        now = time.monotonic()
        self._advance_demo(now)
        mode = self.source_mode.get()
        if mode == "Frozen" and self.frozen_at is None:
            self.frozen_at = now
        if mode != "Frozen":
            self.frozen_at = None
        observed = self.frozen_at if mode == "Frozen" else now
        observation = Observation(observed,
                                  own_hp=None if self.primary_unknown["self"] else round(self.own_hp.get()),
                                  party_hp=None if self.primary_unknown["party"] else round(self.party_hp.get()), buff=self.buff.get(),
                                  cooldown=None if self.primary_unknown["cooldown"] else max(0, self.cooldown.get()),
                                  identity_confirmed=self.identity.get(), available=mode != "Unknown",
                                  party_readings={t.id: PartyReading(self.tracker_values[("party", t.id)]["value"], self.tracker_values[("party", t.id)]["identity"])
                                                  for t in self.profile.party_members},
                                  buff_readings={t.id: self.tracker_values[("buff", t.id)]["value"] for t in self.profile.buffs},
                                  cooldown_readings={t.id: self.tracker_values[("cooldown", t.id)]["value"] for t in self.profile.cooldowns})
        self.last_observation = observation
        valid = observation.available and observation.is_fresh(now)
        # Timers are checked at most 10 times/second during playback. Significant
        # input changes (HP, ready boundary, pause, uncertainty) are handled now.
        # The rule engine uses raw values, independent of presentation cadence.
        rule_key = (self.profile.id, observation.own_hp, observation.party_hp,
                    observation.buff, observation.cooldown == 0,
                    observation.identity_confirmed, observation.available, valid,
                    self.paused.get(), observation.cooldown is None,
                    tuple(observation.party_readings.items()), tuple(observation.buff_readings.items()),
                    tuple((key, value is None, value == 0) for key, value in observation.cooldown_readings.items()))
        if self.engine.last_time is None or rule_key != self.last_rule_key or now >= self.next_rule_check:
            decisions, notices = self.engine.evaluate(self.profile.rules, observation, now, self.paused.get())
            self.last_rule_key = rule_key
            self.next_rule_check = now + RULE_CHECK_SECONDS
        else:
            decisions, notices = self.last_decisions, []
        self.last_decisions, self.last_notices = decisions, notices
        reason = "Simulated HP" if valid else "Unavailable" if not observation.available else "Stale simulated reading"
        self.own_meter.update_reading("YOUR HP", observation.own_hp if valid else None, reason)
        self._render_tracking(observation, valid, reason)
        self.party_meter.update_reading(self.profile.party_name.upper(), observation.party_hp if valid and self.identity.get() else None,
                                       reason if self.identity.get() else "Identity needs confirmation")
        configure_changed(self.buff_title, text=self.profile.buff_name)
        buff_text = observation.buff if valid else "Unknown"
        if buff_text == "Present":
            buff_text += f" · {duration(self.buff_remaining)}"
        configure_changed(self.buff_status, text=buff_text, foreground=AMBER if buff_text == "Missing" else FG)
        configure_changed(self.cooldown_title, text=self.profile.cooldown_name)
        configure_changed(self.cooldown_status, text="Unknown" if not valid or observation.cooldown is None else
                          "Cooldown ready" if observation.cooldown == 0 else f"Cooling down · {duration(observation.cooldown)}",
                          foreground=ACCENT if valid and observation.cooldown == 0 else FG)
        self._render_reminder(decisions, valid)
        order = tuple(d.rule_id for d in decisions)
        for decision in decisions:
            values = (decision.code.capitalize(), decision.detail)
            presentation = (decision.name, values, decision.code)
            previous = self.rendered_rows.get(decision.rule_id)
            if previous is None:
                self.decision_tree.insert("", "end", iid=decision.rule_id, text=decision.name, values=values, tags=(decision.code,))
            elif previous != presentation:
                self.decision_tree.item(decision.rule_id, text=decision.name, values=values, tags=(decision.code,))
            self.rendered_rows[decision.rule_id] = presentation
            if self.previous_codes.get(decision.rule_id) != decision.code:
                self._log(decision.name, decision.code.capitalize(), decision.detail)
                self.previous_codes[decision.rule_id] = decision.code
        if order != self.rendered_order:
            for index, rule_id in enumerate(order):
                self.decision_tree.move(rule_id, "", index)
            self.rendered_order = order
        for notice in notices:
            self.notice_count += 1
            configure_changed(self.latest, text=f"Latest reminder · {notice.name} · {self.notice_count} this session")
            self._log(notice.name, "Reminder", notice.message)
        if notices and self.sound.get() and now - self.last_sound >= 3:
            self.preferences.play_sound()
            self.last_sound = now
        status = (f"{'Playback' if self.playing else 'Manual simulation'} · {mode} readings · No input backend"
                  if self.advanced else f"Simulated data · {'Demo playing' if self.playing else 'Readings unavailable' if not valid else 'Demo stopped'}")
        if self.tabs.select() in (str(self.gathering), str(self.crafting)):
            status = "Manual planning · Material counts entered by you"
        elif self.tabs.select() == str(self.inventory):
            status = "Manual inventory · Saved records, not live game data"
        elif self.tabs.select() == str(self.gear):
            status = "Manual gear goals · Your BiS labels · No stat ranking"
        if self.store.error:
            status = "Saved profiles unavailable · Preview defaults in use · Open Profiles & Rules for details"
        configure_changed(self.data_status, text=status, foreground=AMBER if not valid or self.store.error else getattr(self, "theme_muted", MUTED))
        interval = (PLAYBACK_FRAME_MS if self.playing else IDLE_FRAME_MS) / 1000
        # Anchor to the preceding deadline instead of accumulating Windows timer
        # rounding and callback work. Skip missed frames; never run a catch-up loop.
        if self.frame_interval != interval or self.next_frame_at is None:
            next_frame = now + interval
        else:
            next_frame = self.next_frame_at + interval
            if next_frame <= now or next_frame > now + interval:
                next_frame = now + interval
        self.frame_interval = interval
        self.next_frame_at = next_frame
        delay_ms = max(1, round((next_frame - time.monotonic()) * 1000))
        self.after_id = self.root.after(delay_ms, self._tick)

    def _callback_error(self, exc_type, exc, tb):
        self.playing = False
        self.paused.set(True)
        self.engine.reset()
        self.pause_button.configure(text="Resume reminders")
        self.proposal.configure(text="Preview paused after an error", foreground=RED)
        self.proposal_detail.configure(text="Open Activity for details. Close and reopen the preview if needed.")
        self._log("Preview", "Error", str(exc))
        try:
            self.store.directory.mkdir(parents=True, exist_ok=True)
            (self.store.directory / "error.log").write_text("".join(traceback.format_exception(exc_type, exc, tb)), encoding="utf-8")
        except OSError:
            pass

    def close(self):
        # Profile/item saves remain explicit; picker preferences save separately.
        self.window_placement.close()
        self.price_journal.close()
        self.preferences.close()
        self.gear_page.close()
        self.inventory_page.close()
        self.profession_pages.close()
        self.catalogue.close()
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="WoW Forever offline simulation preview")
    parser.add_argument("--state-dir", type=Path, default=Path(__file__).resolve().parent / "state",
                        help="Local profile directory; useful for isolated checks")
    args = parser.parse_args()
    root = tk.Tk()
    PreviewApp(root, args.state_dir)
    root.mainloop()


if __name__ == "__main__":
    main()
