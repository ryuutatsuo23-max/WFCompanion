"""Manual price history and derived shopping estimates."""

from copy import deepcopy
from datetime import date
import tkinter as tk
from tkinter import ttk

from catalogue import item_key
from item_lookup_ui import ItemLookup
from local_journal import LocalStore, coin_price, estimate, money, validate_journal
from ui_layout import ScrollPage


class PriceJournalUI:
    def __init__(self, host):
        self.host = host
        self.store = LocalStore(host.store.directory, "auction_prices.json",
                               {"version": 1, "characters": {}}, validate_journal)
        self.page = ttk.Frame(host.tabs)
        host.tabs.add(self.page, text="Auction Journal")
        self.scroll = ScrollPage(self.page)
        self.scroll.pack(fill="both", expand=True)
        p = self.scroll.inner
        ttk.Label(p, text="Auction Price Journal", style="Title.TLabel").pack(anchor="w")
        ttk.Label(p, text="Manual unit prices per character. Leave all three coin fields blank for Unknown. "
                  "History is retained; latest observation date wins within the named market.",
                  style="Muted.TLabel", wraplength=750).pack(anchor="w", pady=8)
        saved = self.store.data["characters"].get(host.profile.id, [])
        self.market = tk.StringVar(value=saved[-1]["market"] if saved else "My realm / faction")
        self.name = tk.StringVar()
        self.gold = tk.StringVar()
        self.silver = tk.StringVar()
        self.copper = tk.StringVar()
        self.date = tk.StringVar(value=date.today().isoformat())
        self.lookup = ItemLookup(host, p, self.name)
        for label, var in (("Market / realm / faction", self.market), ("Item name", self.name),
                           ("Observed date · YYYY-MM-DD", self.date)):
            ttk.Label(p, text=label).pack(anchor="w")
            ttk.Entry(p, textvariable=var).pack(fill="x", pady=(0, 5))
        coins = ttk.Frame(p)
        coins.pack(fill="x", pady=6)
        for col, (label, var) in enumerate((("Gold", self.gold), ("Silver · 0–99", self.silver),
                                            ("Copper · 0–99", self.copper))):
            coins.columnconfigure(col, weight=1, uniform="coins")
            ttk.Label(coins, text=label).grid(row=0, column=col, sticky="w")
            ttk.Entry(coins, textvariable=var, width=12).grid(row=1, column=col, sticky="ew", padx=(0, 8))
        self.price_preview = ttk.Label(p, text="Unit price: Unknown", style="Muted.TLabel")
        self.price_preview.pack(anchor="w")
        for var in (self.gold, self.silver, self.copper):
            var.trace_add("write", self.preview_price)
        self.save_button = ttk.Button(p, text="Save price observation", command=self.save, style="Primary.TButton")
        self.save_button.pack(anchor="w", pady=6)
        self.notice = ttk.Label(p, wraplength=750, style="Muted.TLabel")
        self.notice.pack(anchor="w")
        table = host.profession_pages._table
        self.history = table(p, (("name", "Item", 240), ("market", "Market", 170),
                                 ("date", "Observed", 110), ("price", "Unit price", 140)))
        self.history.configure(height=4)
        ttk.Label(p, text="Shopping cost estimate · selected market", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=8)
        self.costs = table(p, (("name", "Material", 220), ("quantity", "Still needed", 100),
                             ("price", "Unit price", 120), ("date", "Price date", 110), ("cost", "Estimate", 140)))
        self.total = ttk.Label(p, wraplength=750, style="Muted.TLabel")
        self.total.pack(anchor="w", pady=8)
        ttk.Label(p, text="All shortages are valued, including Gather goals. Estimates exclude fees and availability. "
                  "Older dates remain visible; these are not live quotes. Linked items require matching item IDs; "
                  "manual names only match other manual names.", wraplength=750, style="Muted.TLabel").pack(anchor="w")
        self.active = host.profile.id
        self.drafts = {}
        self.market.trace_add("write", lambda *_: self.refresh_costs())
        host.root.bind("<<InventoryStockChanged>>", lambda _: self.refresh_costs(), add="+")
        if self.store.error:
            self.save_button.state(["disabled"])
            self.notice.configure(text=self.store.error)
        self.refresh()

    def refresh(self):
        if self.active != self.host.profile.id:
            self.lookup.close()
            self.drafts[self.active] = (self.market.get(), self.name.get(), self.gold.get(), self.silver.get(),
                                       self.copper.get(), self.date.get(), self.lookup.reference)
            self.active = self.host.profile.id
            records = self.records()
            draft = self.drafts.get(self.active, (records[-1]["market"] if records else "My realm / faction",
                                                  "", "", "", "", date.today().isoformat(), None))
            for var, value in zip((self.market, self.name, self.gold, self.silver, self.copper, self.date), draft):
                var.set(value)
            self.lookup.load(draft[6])
        self.history.delete(*self.history.get_children())
        for record in reversed(self.records()):
            self.history.insert("", "end", values=(record["name"], record["market"], record["date"], money(record["copper"])))
        self.refresh_costs()

    def records(self):
        return self.store.data["characters"].get(self.host.profile.id, [])

    def preview_price(self, *_):
        try:
            value = money(coin_price(self.gold.get(), self.silver.get(), self.copper.get()))
            self.price_preview.configure(text=f"Unit price: {value}")
        except ValueError as exc:
            self.price_preview.configure(text=str(exc))

    def save(self):
        try:
            price = coin_price(self.gold.get(), self.silver.get(), self.copper.get())
            if price is None:
                raise ValueError("Price is Unknown. Enter at least one coin amount to save an observation.")
            record = dict(name=self.name.get().strip(), key=item_key(self.name.get(), self.lookup.reference),
                          market=self.market.get().strip(), copper=price, date=self.date.get().strip())
            candidate = deepcopy(self.store.data)
            candidate["characters"].setdefault(self.host.profile.id, []).append(record)
            validate_journal(candidate)
            if not self.host.ensure_plan_profile():
                return False
            self.store.save(candidate)
            self.refresh()
            self.notice.configure(text="Price saved locally. Previous observations retained.")
            return True
        except (ValueError, OSError) as exc:
            self.notice.configure(text=str(exc))
            return False

    def refresh_costs(self):
        rows = self.host.profession_pages.requirements()
        results = estimate(rows, self.records(), self.market.get())
        self.costs.delete(*self.costs.get_children())
        for row, price, cost in results:
            self.costs.insert("", "end", values=(row.name, "Unknown" if row.remaining is None else row.remaining,
                money(price["copper"]) if price else "Unknown", price["date"] if price else "Unknown", money(cost)))
        unknown = sum(cost is None for _, _, cost in results)
        subtotal = sum(cost or 0 for _, _, cost in results)
        message = (f"Known subtotal: {money(subtotal)} · {unknown} Unknown · Total: Unknown"
                   if unknown else f"Estimated total: {money(subtotal)}")
        if self.store.error:
            message = "Price journal unavailable · Total: Unknown · Original file preserved."
        self.total.configure(text=message)
        book = self.host.profession_pages.book_ui
        if hasattr(book, "price_summary"):
            book.price_summary.configure(text=f"Market: {self.market.get()} · {message}")

    def close(self):
        self.lookup.close()
