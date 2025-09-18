#!/usr/bin/env python3
"""
Rack Designer – cross-platform 10" / 19" equipment-rack planner
Dark mode by default, drag-and-drop, snap-to-U, PNG+PDF export, JSON save/load.
Single runnable file – no external assets required.
Python 3.10+  |  Author:  <you>
"""

from __future__ import annotations
import json, math, os, uuid, tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas

# ---------- constants -------------------------------------------------------
APP_NAME = "Rack Designer"
VERSION = "1.0"
DEFAULT_RACK_HEIGHT_U = 20
DEFAULT_RACK_WIDTH = 19  # or 10
MIN_U, MAX_U = 6, 40

U_HEIGHT_PX = 90  # 1U drawn height at 100 % zoom
RAIL_WIDTH_PX = 20
CANVAS_BG = "#1e1e1e"
GRID_colour_odd = "#2d2d2d"
GRID_colour_even = "#252525"
RAIL_colour = "#555"
TEXT_colour = "#dedede"
SELECTION_colour = "#00aaff"
ERROR_colour = "#ff4d4d"

# ---------- model -----------------------------------------------------------
class WidthClass(Enum):
    BOTH = "both"
    TEN = "10"
    NINETEEN = "19"


@dataclass
class Item:
    id: str
    type: str
    u_top: int
    u_height: int
    name: str
    width_class: WidthClass
    style: str = "#3f8fdf"  # hex colour
    locked: bool = False

    def intersects(self, other: "Item") -> bool:
        """Return True if U ranges overlap."""
        s1, e1 = self.u_top, self.u_top + self.u_height
        s2, e2 = other.u_top, other.u_top + other.u_height
        return s1 < e2 and s2 < e1


@dataclass
class TextNote:
    id: str
    x: float
    y: float
    text: str
    font_size: int = 12
    rotation: int = 0  # 0 or 90
    style: str = "#cccccc"


@dataclass
class RackModel:
    width: int  # 10 or 19
    height_u: int
    items: List[Item] = field(default_factory=list)
    texts: List[TextNote] = field(default_factory=list)

    # ---------- geometry helpers --------------------------------------------
    def u_to_pixels(self, u: float, zoom: float) -> float:
        return u * U_HEIGHT_PX * zoom

    def pixels_to_u(self, px: float, zoom: float) -> float:
        return px / (U_HEIGHT_PX * zoom)

    def rack_width_pixels(self, zoom: float) -> float:
        return self.width * zoom  # 19" -> 19 px * zoom (simplistic but scales)

    # ---------- CRUD ---------------------------------------------------------
    def add_item(self, item: Item) -> bool:
        for it in self.items:
            if it.intersects(item):
                return False
        self.items.append(item)
        return True

    def remove_item(self, item_id: str):
        self.items = [it for it in self.items if it.id != item_id]

    def move_item(self, item_id: str, new_u: int) -> bool:
        it = next((i for i in self.items if i.id == item_id), None)
        if not it or it.locked:
            return False
        old_u = it.u_top
        it.u_top = new_u
        for other in self.items:
            if other.id != item_id and other.intersects(it):
                it.u_top = old_u
                return False
        return True

    def rename_item(self, item_id: str, name: str):
        for it in self.items:
            if it.id == item_id:
                it.name = name

    def change_item_height(self, item_id: str, u_height: int) -> bool:
        it = next((i for i in self.items if i.id == item_id), None)
        if not it or it.locked or u_height <= 0:
            return False
        old = it.u_height
        it.u_height = u_height
        for other in self.items:
            if other.id != item_id and other.intersects(it):
                it.u_height = old
                return False
        return True

    # ---------- serialization -----------------------------------------------
    def to_json(self) -> str:
        data = {
            "version": VERSION,
            "width": self.width,
            "height_u": self.height_u,
            "items": [asdict(it) for it in self.items],
            "texts": [asdict(t) for t in self.texts],
        }
        return json.dumps(data, indent=2)

    @staticmethod
    def from_json(s: str) -> "RackModel":
        data = json.loads(s)
        # Basic version check
        if data.get("version") != VERSION:
            messagebox.showwarning(
                "Version mismatch",
                "Project file was created with a different version; loading anyway.",
            )
        width = data["width"]
        height_u = data["height_u"]
        items = [
            Item(
                id=it["id"],
                type=it["type"],
                u_top=it["u_top"],
                u_height=it["u_height"],
                name=it["name"],
                width_class=WidthClass(it["width_class"]),
                style=it.get("style", "#3f8fdf"),
                locked=it.get("locked", False),
            )
            for it in data["items"]
        ]
        texts = [
            TextNote(
                id=t["id"],
                x=t["x"],
                y=t["y"],
                text=t["text"],
                font_size=t.get("font_size", 12),
                rotation=t.get("rotation", 0),
                style=t.get("style", "#cccccc"),
            )
            for t in data["texts"]
        ]
        return RackModel(width=width, height_u=height_u, items=items, texts=texts)


# ---------- command pattern for undo/redo -----------------------------------
class Command:
    def do(self): raise NotImplementedError
    def undo(self): raise NotImplementedError


class AddItemCommand(Command):
    def __init__(self, model: RackModel, item: Item):
        self.model, self.item = model, item
    def do(self): return self.model.add_item(self.item)
    def undo(self): self.model.remove_item(self.item.id)


class RemoveItemCommand(Command):
    def __init__(self, model: RackModel, item: Item):
        self.model, self.item = model, item
    def do(self): self.model.remove_item(self.item.id)
    def undo(self): self.model.add_item(self.item)


class MoveItemCommand(Command):
    def __init__(self, model: RackModel, item_id: str, old_u: int, new_u: int):
        self.model, self.item_id, self.old_u, self.new_u = model, item_id, old_u, new_u
    def do(self): return self.model.move_item(self.item_id, self.new_u)
    def undo(self): self.model.move_item(self.item_id, self.old_u)


class RenameItemCommand(Command):
    def __init__(self, model: RackModel, item_id: str, old: str, new: str):
        self.model, self.item_id, self.old, self.new = model, item_id, old, new
    def do(self): self.model.rename_item(self.item_id, self.new)
    def undo(self): self.model.rename_item(self.item_id, self.old)


class ChangeItemHeightCommand(Command):
    def __init__(self, model: RackModel, item_id: str, old: int, new: int):
        self.model, self.item_id, self.old, self.new = model, item_id, old, new
    def do(self): return self.model.change_item_height(self.item_id, self.new)
    def undo(self): self.model.change_item_height(self.item_id, self.old)


class AddTextCommand(Command):
    def __init__(self, model: RackModel, text: TextNote):
        self.model, self.text = model, text
    def do(self): self.model.texts.append(self.text)
    def undo(self): self.model.texts = [t for t in self.model.texts if t.id != self.text.id]


class RemoveTextCommand(Command):
    def __init__(self, model: RackModel, text: TextNote):
        self.model, self.text = model, text
    def do(self): self.model.texts = [t for t in self.model.texts if t.id != self.text.id]
    def undo(self): self.model.texts.append(self.text)


class MoveTextCommand(Command):
    def __init__(self, text: TextNote, old: Tuple[float, float], new: Tuple[float, float]):
        self.text, self.old, self.new = text, old, new
    def do(self):
        self.text.x, self.text.y = self.new
    def undo(self):
        self.text.x, self.text.y = self.old


class CommandStack:
    def __init__(self, max_stack: int = 100):
        self.stack: List[Command] = []
        self.idx = -1
        self.max_stack = max_stack

    def do(self, cmd: Command) -> bool:
        ok = cmd.do()
        if not ok:
            return False
        self.stack = self.stack[: self.idx + 1]
        self.stack.append(cmd)
        if len(self.stack) > self.max_stack:
            self.stack.pop(0)
        else:
            self.idx += 1
        return True

    def undo(self):
        if self.idx >= 0:
            self.stack[self.idx].undo()
            self.idx -= 1

    def redo(self):
        if self.idx + 1 < len(self.stack):
            self.idx += 1
            self.stack[self.idx].do()


# ---------- component palette -----------------------------------------------
PALETTE = [
    {"type": "1U blank", "u": 1, "width": WidthClass.BOTH, "colour": "#444"},
    {"type": "2U blank", "u": 2, "width": WidthClass.BOTH, "colour": "#444"},
    {"type": "3U blank", "u": 3, "width": WidthClass.BOTH, "colour": "#444"},
    {"type": "1U patch", "u": 1, "width": WidthClass.NINETEEN, "colour": "#6f8faf"},
    {"type": "1U patch 10", "u": 1, "width": WidthClass.TEN, "colour": "#6f8faf"},
    {"type": "1U cable mgr", "u": 1, "width": WidthClass.BOTH, "colour": "#666"},
    {"type": "1U PDU 19", "u": 1, "width": WidthClass.NINETEEN, "colour": "#af6f6f"},
    {"type": "1U PDU 10", "u": 1, "width": WidthClass.TEN, "colour": "#af6f6f"},
    {"type": "1U switch", "u": 1, "width": WidthClass.NINETEEN, "colour": "#3f8fdf"},
    {"type": "2U UPS", "u": 2, "width": WidthClass.NINETEEN, "colour": "#dfaf5f"},
    {"type": "2U shelf", "u": 2, "width": WidthClass.BOTH, "colour": "#8a7a6f"},
    {"type": "2U server", "u": 2, "width": WidthClass.NINETEEN, "colour": "#5faf5f"},
    {"type": "Generic N-U", "u": 1, "width": WidthClass.BOTH, "colour": "#7f7f7f"},
]


# ---------- GUI -------------------------------------------------------------
class RackCanvasView(tk.Canvas):
    def __init__(self, parent, model: RackModel, cmd_stack: CommandStack, **kw):
        super().__init__(parent, bg=CANVAS_BG, highlightthickness=0, **kw)
        self.model, self.cmd_stack = model, cmd_stack
        self.zoom = 1.0
        self.pan_x = self.pan_y = 0
        self.selected_ids: List[str] = []  # ids of items OR texts
        self.drag_data: Optional[Dict] = None
        self.show_u_labels = True
        self.show_alternating = True
        self.show_rails = True
        self.snap_enabled = True
        self._scroll_start: Optional[Tuple[int, int]] = None
        self._init_ui()
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self.on_click)
        self.bind("<B1-Motion>", self.on_drag)
        self.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Button-3>", self.on_right_click)
        self.bind("<Delete>", self.on_delete)
        self.bind("<Control-MouseWheel>", self.on_zoom)
        self.bind("<Button-2>", self.on_pan_start)
        self.bind("<B2-Motion>", self.on_pan_move)
        self.bind("<Control-z>", lambda e: self.cmd_stack.undo() or self.redraw())
        self.bind("<Control-y>", lambda e: self.cmd_stack.redo() or self.redraw())
        self.dnd_enabled = True

    def _init_ui(self):
        self.itemconfigure("all")

    def to_canvas_coords(self, x: float, y: float) -> Tuple[float, float]:
        """Convert logical coords -> canvas coords (with zoom/pan)."""
        return x * self.zoom + self.pan_x, y * self.zoom + self.pan_y

    def from_canvas_coords(self, cx: float, cy: float) -> Tuple[float, float]:
        return (cx - self.pan_x) / self.zoom, (cy - self.pan_y) / self.zoom

    def u_to_y(self, u: float) -> float:
        return self.model.u_to_pixels(u, self.zoom) + self.pan_y

    def y_to_u(self, y: float) -> float:
        return self.model.pixels_to_u((y - self.pan_y), self.zoom)

    def redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10:
            return
        # draw background
        self.create_rectangle(0, 0, w, h, fill=CANVAS_BG, outline="")
        # draw rack
        self._draw_rack()
        self._draw_items()
        self._draw_texts()
        self._draw_selections()

    def _draw_rack(self):
        rw = self.model.rack_width_pixels(self.zoom)
        left = self.to_canvas_coords(RAIL_WIDTH_PX, 0)[0]
        right = self.to_canvas_coords(RAIL_WIDTH_PX + rw, 0)[0]
        top = self.u_to_y(0)
        bottom = self.u_to_y(self.model.height_u)
        # alternating U stripes
        if self.show_alternating:
            for u in range(self.model.height_u):
                y1 = self.u_to_y(u)
                y2 = self.u_to_y(u + 1)
                colour = GRID_colour_odd if u % 2 else GRID_colour_even
                self.create_rectangle(left, y1, right, y2, fill=colour, outline="")
        # rails
        if self.show_rails:
            self.create_line(left, top, left, bottom, fill=RAIL_colour, width=2)
            self.create_line(right, top, right, bottom, fill=RAIL_colour, width=2)
        # U labels
        if self.show_u_labels:
            for u in range(1, self.model.height_u + 1):
                y = self.u_to_y(u - 0.5)
                self.create_text(left - 10, y, text=str(u), fill=TEXT_colour, anchor="e")

    def _draw_items(self):
        for it in self.model.items:
            self._draw_one_item(it)

    def _draw_one_item(self, it: Item):
        rw = self.model.rack_width_pixels(self.zoom)
        left = self.to_canvas_coords(RAIL_WIDTH_PX, 0)[0]
        right = self.to_canvas_coords(RAIL_WIDTH_PX + rw, 0)[0]
        y1 = self.u_to_y(it.u_top)
        y2 = self.u_to_y(it.u_top + it.u_height)
        # width mismatch indicator
        colour = it.style
        if (self.model.width == 10 and it.width_class == WidthClass.NINETEEN) or (
            self.model.width == 19 and it.width_class == WidthClass.TEN
        ):
            colour = ERROR_colour
        rect = self.create_rectangle(left, y1, right, y2, fill=colour, outline="", tags=("item", it.id))
        self.create_text(
            (left + right) / 2,
            (y1 + y2) / 2,
            text=it.name,
            fill="white",
            font=("Segoe UI", 10),
            tags=("item", it.id),
        )

    def _draw_texts(self):
        for txt in self.model.texts:
            x, y = self.to_canvas_coords(txt.x, txt.y)
            self.create_text(
                x,
                y,
                text=txt.text,
                fill=txt.style,
                font=("Segoe UI", int(txt.font_size * self.zoom)),
                tags=("text", txt.id),
                angle=txt.rotation,
            )

    def _draw_selections(self):
        for oid in self.selected_ids:
            tags = self.gettags(oid)
            if not tags:
                continue
            if tags[0] == "item":
                self._highlight_item_bbox(oid)
            elif tags[0] == "text":
                self._highlight_text_bbox(oid)

    def _highlight_item_bbox(self, oid: str):
        it = next((i for i in self.model.items if i.id == oid), None)
        if not it:
            return
        rw = self.model.rack_width_pixels(self.zoom)
        left = self.to_canvas_coords(RAIL_WIDTH_PX, 0)[0]
        right = self.to_canvas_coords(RAIL_WIDTH_PX + rw, 0)[0]
        y1 = self.u_to_y(it.u_top)
        y2 = self.u_to_y(it.u_top + it.u_height)
        self.create_rectangle(
            left - 2, y1 - 2, right + 2, y2 + 2,
            outline=SELECTION_colour, width=2, tags="sel"
        )

    def _highlight_text_bbox(self, oid: str):
        txt = next((t for t in self.model.texts if t.id == oid), None)
        if not txt:
            return
        x, y = self.to_canvas_coords(txt.x, txt.y)
        bb = self.bbox(self.find_withtag(txt.id)[0])
        if bb:
            self.create_rectangle(*bb, outline=SELECTION_colour, width=2, tags="sel")

    def on_click(self, event: tk.Event):
        self.focus_set()
        cx, cy = event.x, event.y
        ids = self.find_closest(cx, cy)
        if not ids:
            self.selected_ids = []
            self.redraw()
            return
        tags = self.gettags(ids[0])
        if not tags:
            self.selected_ids = []
            self.redraw()
            return
        kind, oid = tags[0], tags[1]
        if kind in ("item", "text"):
            if event.state & 1:  # shift
                if oid not in self.selected_ids:
                    self.selected_ids.append(oid)
            else:
                self.selected_ids = [oid]
            self.drag_data = {"kind": kind, "oid": oid, "start_u": self.y_to_u(cy), "start_y": cy}
        self.redraw()

    def on_drag(self, event: tk.Event):
        if not self.drag_data:
            return
        kind, oid = self.drag_data["kind"], self.drag_data["oid"]
        if kind == "item":
            it = next((i for i in self.model.items if i.id == oid), None)
            if not it or it.locked:
                return
            new_u = int(round(self.y_to_u(event.y)))
            if self.snap_enabled:
                new_u = max(0, min(new_u, self.model.height_u - it.u_height))
            if new_u == it.u_top:
                return
            # preview
            it.u_top = new_u
            self.redraw()

    def on_release(self, event: tk.Event):
        if not self.drag_data:
            return
        kind, oid = self.drag_data["kind"], self.drag_data["oid"]
        if kind == "item":
            it = next((i for i in self.model.items if i.id == oid), None)
            if not it or it.locked:
                self.drag_data = None
                return
            new_u = int(round(self.y_to_u(event.y)))
            if self.snap_enabled:
                new_u = max(0, min(new_u, self.model.height_u - it.u_height))
            old_u = self.drag_data["start_u"]
            if new_u != old_u:
                cmd = MoveItemCommand(self.model, oid, old_u, new_u)
                # we already moved it in preview, so undo and redo cleanly
                self.cmd_stack.undo()
                self.cmd_stack.do(cmd)
        self.drag_data = None
        self.redraw()

    def on_right_click(self, event: tk.Event):
        cx, cy = event.x, event.y
        ids = self.find_closest(cx, cy)
        if not ids:
            return
        tags = self.gettags(ids[0])
        if not tags or tags[0] not in ("item", "text"):
            return
        kind, oid = tags[0], tags[1]
        menu = tk.Menu(self, tearoff=0)
        if kind == "item":
            it = next((i for i in self.model.items if i.id == oid), None)
            if not it:
                return
            menu.add_command(label="Rename", command=lambda: self.rename_item(it))
            menu.add_command(label="Duplicate", command=lambda: self.duplicate_item(it))
            menu.add_command(label="Lock" if not it.locked else "Unlock", command=lambda: self.toggle_lock(it))
            menu.add_separator()
            menu.add_command(label="Delete", command=lambda: self.delete_item(it))
        elif kind == "text":
            txt = next((t for t in self.model.texts if t.id == oid), None)
            if not txt:
                return
            menu.add_command(label="Edit", command=lambda: self.edit_text(txt))
            menu.add_command(label="Delete", command=lambda: self.delete_text(txt))
        menu.tk_popup(event.x_root, event.y_root)

    def rename_item(self, it: Item):
        new = simpledialog.askstring("Rename", "New name:", initialvalue=it.name)
        if new is not None and new != it.name:
            cmd = RenameItemCommand(self.model, it.id, it.name, new)
            self.cmd_stack.do(cmd)
            self.redraw()

    def duplicate_item(self, it: Item):
        new = Item(
            id=str(uuid.uuid4()),
            type=it.type,
            u_top=min(it.u_top + it.u_height, self.model.height_u - it.u_height),
            u_height=it.u_height,
            name=it.name + " copy",
            width_class=it.width_class,
            style=it.style,
            locked=False,
        )
        cmd = AddItemCommand(self.model, new)
        if self.cmd_stack.do(cmd):
            self.redraw()

    def toggle_lock(self, it: Item):
        it.locked = not it.locked
        self.redraw()

    def delete_item(self, it: Item):
        cmd = RemoveItemCommand(self.model, it)
        self.cmd_stack.do(cmd)
        self.selected_ids = [s for s in self.selected_ids if s != it.id]
        self.redraw()

    def delete_text(self, txt: TextNote):
        cmd = RemoveTextCommand(self.model, txt)
        self.cmd_stack.do(cmd)
        self.selected_ids = [s for s in self.selected_ids if s != txt.id]
        self.redraw()

    def edit_text(self, txt: TextNote):
        new = simpledialog.askstring("Edit text", "Text:", initialvalue=txt.text)
        if new is not None:
            txt.text = new
            self.redraw()

    def on_delete(self, event: tk.Event):
        for oid in self.selected_ids[:]:
            it = next((i for i in self.model.items if i.id == oid), None)
            if it:
                self.delete_item(it)
            txt = next((t for t in self.model.texts if t.id == oid), None)
            if txt:
                self.delete_text(txt)

    def on_zoom(self, event: tk.Event):
        delta = 1.1 if event.delta > 0 else 0.9
        new_zoom = max(0.3, min(3.0, self.zoom * delta))
        self.zoom = new_zoom
        self.redraw()

    def on_pan_start(self, event: tk.Event):
        self._scroll_start = (event.x, event.y)

    def on_pan_move(self, event: tk.Event):
        if not self._scroll_start:
            return
        dx = event.x - self._scroll_start[0]
        dy = event.y - self._scroll_start[1]
        self.pan_x += dx
        self.pan_y += dy
        self._scroll_start = (event.x, event.y)
        self.redraw()


# ---------- inspector -------------------------------------------------------
class InspectorView(ctk.CTkFrame):
    def __init__(self, parent, canvas: RackCanvasView, model: RackModel, cmd_stack: CommandStack):
        super().__init__(parent, width=220)
        self.canvas, self.model, self.cmd_stack = canvas, model, cmd_stack
        self.title = ctk.CTkLabel(self, text="Inspector", font=ctk.CTkFont(size=14, weight="bold"))
        self.title.pack(pady=5)
        self.var_name = tk.StringVar()
        self.var_u_height = tk.StringVar()
        self.var_locked = tk.BooleanVar()
        self.var_style = tk.StringVar()
        self.build_ui()
        self.current_item: Optional[Item] = None
        self.after(200, self.poll)

    def build_ui(self):
        frm = ctk.CTkFrame(self)
        frm.pack(fill="both", expand=True, padx=10, pady=10)
        ctk.CTkLabel(frm, text="Name:").grid(row=0, column=0, sticky="w", pady=5)
        ctk.CTkEntry(frm, textvariable=self.var_name).grid(row=0, column=1, sticky="ew", padx=5)
        ctk.CTkLabel(frm, text="Height (U):").grid(row=1, column=0, sticky="w", pady=5)
        ctk.CTkEntry(frm, textvariable=self.var_u_height, width=60).grid(row=1, column=1, sticky="w", padx=5)
        ctk.CTkCheckBox(frm, text="Locked", variable=self.var_locked).grid(row=2, column=0, columnspan=2, pady=5)
        ctk.CTkLabel(frm, text="Colour:").grid(row=3, column=0, sticky="w", pady=5)
        ctk.CTkEntry(frm, textvariable=self.var_style, width=80).grid(row=3, column=1, sticky="w", padx=5)
        btn = ctk.CTkButton(frm, text="Apply", command=self.apply)
        btn.grid(row=4, column=0, columnspan=2, pady=10)

    def poll(self):
        """Update inspector based on canvas selection."""
        if not self.canvas.selected_ids:
            self.current_item = None
            self.var_name.set("")
            self.var_u_height.set("")
            self.var_locked.set(False)
            self.var_style.set("")
        else:
            oid = self.canvas.selected_ids[0]
            it = next((i for i in self.model.items if i.id == oid), None)
            if it and it != self.current_item:
                self.current_item = it
                self.var_name.set(it.name)
                self.var_u_height.set(str(it.u_height))
                self.var_locked.set(it.locked)
                self.var_style.set(it.style)
        self.after(200, self.poll)

    def apply(self):
        if not self.current_item:
            return
        new_name = self.var_name.get()
        if new_name != self.current_item.name:
            cmd = RenameItemCommand(self.model, self.current_item.id, self.current_item.name, new_name)
            self.cmd_stack.do(cmd)
        try:
            new_u = int(self.var_u_height.get())
            if new_u != self.current_item.u_height:
                cmd = ChangeItemHeightCommand(self.model, self.current_item.id, self.current_item.u_height, new_u)
                self.cmd_stack.do(cmd)
        except ValueError:
            pass
        self.current_item.locked = self.var_locked.get()
        self.current_item.style = self.var_style.get()
        self.canvas.redraw()


# ---------- palette ---------------------------------------------------------
class PaletteView(ctk.CTkFrame):
    def __init__(self, parent, canvas: RackCanvasView, model: RackModel, cmd_stack: CommandStack):
        super().__init__(parent, width=200)
        self.canvas, self.model, self.cmd_stack = canvas, model, cmd_stack
        ctk.CTkLabel(self, text="Components", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5)
        self.build_ui()

    def build_ui(self):
        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        for spec in PALETTE:
            btn = ctk.CTkButton(
                scroll,
                text=spec["type"],
                fg_color=spec["colour"],
                text_color="white",
                anchor="w",
                command=lambda s=spec: self.on_drag_start(s),
            )
            btn.pack(fill="x", pady=2)
        # Text tool
        btn = ctk.CTkButton(scroll, text="Text annotation", command=self.place_text)
        btn.pack(fill="x", pady=(10, 2))

    def on_drag_start(self, spec: Dict):
        """Create a floating proxy and bind motion/release."""
        proxy = ctk.CTkToplevel(self)
        proxy.overrideredirect(True)
        proxy.attributes("-topmost", True)
        lbl = ctk.CTkLabel(proxy, text=spec["type"], fg_color=spec["colour"], text_color="white", width=100, height=30)
        lbl.pack()
        x, y = self.winfo_pointerxy()
        proxy.geometry(f"+{x}+{y}")

        def on_move(ev):
            proxy.geometry(f"+{ev.x_root}+{ev.y_root}")

        def on_drop(ev):
            proxy.destroy()
            # convert to canvas coords
            cx = self.canvas.winfo_rootx()
            cy = self.canvas.winfo_rooty()
            lx, ly = ev.x_root - cx, ev.y_root - cy
            u = int(round(self.canvas.y_to_u(ly)))
            u = max(0, min(u, self.model.height_u - spec["u"]))
            # width check
            if spec["width"] == WidthClass.TEN and self.model.width != 10:
                messagebox.showwarning("Width mismatch", "Cannot place 10\" component in 19\" rack.")
                return
            if spec["width"] == WidthClass.NINETEEN and self.model.width != 19:
                messagebox.showwarning("Width mismatch", "Cannot place 19\" component in 10\" rack.")
                return
            it = Item(
                id=str(uuid.uuid4()),
                type=spec["type"],
                u_top=u,
                u_height=spec["u"],
                name=spec["type"],
                width_class=spec["width"],
                style=spec["colour"],
            )
            cmd = AddItemCommand(self.model, it)
            if self.cmd_stack.do(cmd):
                self.canvas.redraw()
            else:
                messagebox.showwarning("Overlap", "Cannot place – overlap detected.")

        proxy.bind("<B1-Motion>", on_move)
        proxy.bind("<ButtonRelease-1>", on_drop)

    def place_text(self):
        txt = TextNote(id=str(uuid.uuid4()), x=100, y=100, text="Note")
        cmd = AddTextCommand(self.model, txt)
        self.cmd_stack.do(cmd)
        self.canvas.redraw()


# ---------- main window -----------------------------------------------------
class RackDesignerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}  ({VERSION})")
        self.geometry("1200x800")
        ctk.set_appearance_mode("dark")
        self.model = RackModel(width=DEFAULT_RACK_WIDTH, height_u=DEFAULT_RACK_HEIGHT_U)
        self.cmd_stack = CommandStack()
        self.current_file: Optional[Path] = None
        self.build_ui()
        self.bind("<Control-n>", lambda e: self.file_new())
        self.bind("<Control-o>", lambda e: self.file_open())
        self.bind("<Control-s>", lambda e: self.file_save())
        self.bind("<Control-Shift-s>", lambda e: self.file_save_as())

    def build_ui(self):
        # toolbar
        toolbar = ctk.CTkFrame(self)
        toolbar.pack(fill="x", pady=5)
        ctk.CTkButton(toolbar, text="New", width=60, command=self.file_new).pack(side="left", padx=5)
        ctk.CTkButton(toolbar, text="Open", width=60, command=self.file_open).pack(side="left", padx=5)
        ctk.CTkButton(toolbar, text="Save", width=60, command=self.file_save).pack(side="left", padx=5)
        ctk.CTkButton(toolbar, text="PNG", width=60, command=self.export_png).pack(side="left", padx=5)
        ctk.CTkButton(toolbar, text="PDF", width=60, command=self.export_pdf).pack(side="left", padx=5)
        ctk.CTkLabel(toolbar, text="Width:").pack(side="left", padx=(20, 5))
        self.cmb_width = ctk.CTkComboBox(
            toolbar, values=["10", "19"], command=self.on_width_changed, width=70
        )
        self.cmb_width.set(str(self.model.width))
        self.cmb_width.pack(side="left")
        ctk.CTkLabel(toolbar, text="Height (U):").pack(side="left", padx=(20, 5))
        self.cmb_height = ctk.CTkComboBox(
            toolbar, values=[str(i) for i in range(MIN_U, MAX_U + 1)], command=self.on_height_changed, width=70
        )
        self.cmb_height.set(str(self.model.height_u))
        self.cmb_height.pack(side="left")
        # main panes
        pan = ctk.CTkPanedWindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True, padx=10, pady=10)
        self.canvas = RackCanvasView(pan, self.model, self.cmd_stack)
        self.inspector = InspectorView(pan, self.canvas, self.model, self.cmd_stack)
        self.palette = PaletteView(pan, self.canvas, self.model, self.cmd_stack)
        pan.add(self.palette, width=200)
        pan.add(self.canvas, width=800)
        pan.add(self.inspector, width=220)
        # status
        self.status = ctk.CTkLabel(self, text="Ready", anchor="w")
        self.status.pack(side="bottom", fill="x", padx=10, pady=5)
        self.after(300, self.poll_status)

    def poll_status(self):
        msg = f" Rack: {self.model.width}\"  {self.model.height_u}U  |  Selected: {len(self.canvas.selected_ids)}"
        self.status.configure(text=msg)
        self.after(300, self.poll_status)

    def on_width_changed(self, _):
        w = int(self.cmb_width.get())
        if w == self.model.width:
            return
        self.model.width = w
        self.canvas.redraw()

    def on_height_changed(self, _):
        h = int(self.cmb_height.get())
        if h == self.model.height_u:
            return
        # overflow check
        overflow = [it for it in self.model.items if it.u_top + it.u_height > h]
        if overflow:
            msg = f"{len(overflow)} items exceed new height.\nUse 'Reflow' to pack them automatically?"
            if messagebox.askyesno("Overflow", msg):
                self.reflow_items(h)
        self.model.height_u = h
        self.canvas.redraw()

    def reflow_items(self, new_height: int):
        """Pack items from top down without changing order."""
        occupied = [False] * new_height
        for it in sorted(self.model.items, key=lambda x: x.u_top):
            # find first free slot
            start = 0
            while start <= new_height - it.u_height:
                if not any(occupied[start : start + it.u_height]):
                    # place
                    for k in range(it.u_height):
                        occupied[start + k] = True
                    it.u_top = start
                    break
                start += 1

    # ---------- file I/O ------------------------------------------------------
    def file_new(self):
        self.model = RackModel(width=DEFAULT_RACK_WIDTH, height_u=DEFAULT_RACK_HEIGHT_U)
        self.canvas.model = self.model
        self.inspector.model = self.model
        self.palette.model = self.model
        self.canvas.selected_ids = []
        self.cmd_stack = CommandStack()
        self.canvas.cmd_stack = self.cmd_stack
        self.inspector.cmd_stack = self.cmd_stack
        self.palette.cmd_stack = self.cmd_stack
        self.cmb_width.set(str(self.model.width))
        self.cmb_height.set(str(self.model.height_u))
        self.canvas.redraw()
        self.current_file = None
        self.title(APP_NAME)

    def file_open(self):
        path = filedialog.askopenfilename(
            title="Open project",
            filetypes=[("Rack projects", "*.rackproj"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.model = RackModel.from_json(f.read())
        except Exception as e:
            messagebox.showerror("Open failed", str(e))
            return
        self.canvas.model = self.model
        self.inspector.model = self.model
        self.palette.model = self.model
        self.canvas.selected_ids = []
        self.cmd_stack = CommandStack()
        self.canvas.cmd_stack = self.cmd_stack
        self.inspector.cmd_stack = self.cmd_stack
        self.palette.cmd_stack = self.cmd_stack
        self.cmb_width.set(str(self.model.width))
        self.cmb_height.set(str(self.model.height_u))
        self.canvas.redraw()
        self.current_file = Path(path)
        self.title(f"{APP_NAME} – {self.current_file.name}")

    def file_save(self):
        if not self.current_file:
            self.file_save_as()
            return
        try:
            with open(self.current_file, "w", encoding="utf-8") as f:
                f.write(self.model.to_json())
            self.title(f"{APP_NAME} – {self.current_file.name}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def file_save_as(self):
        path = filedialog.asksaveasfilename(
            title="Save project",
            defaultextension=".rackproj",
            filetypes=[("Rack projects", "*.rackproj"), ("All files", "*.*")],
        )
        if not path:
            return
        self.current_file = Path(path)
        self.file_save()

    # ---------- export --------------------------------------------------------
    def export_png(self):
        path = filedialog.asksaveasfilename(
            title="Export PNG",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.render_to_png(path, transparent=True, scale=2)
            messagebox.showinfo("Export", f"PNG saved to\n{path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def export_pdf(self):
        path = filedialog.asksaveasfilename(
            title="Export PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.render_to_pdf(path, pagesize=A4)
            messagebox.showinfo("Export", f"PDF saved to\n{path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def render_to_png(self, path: str, transparent: bool = True, scale: int = 2):
        """Render current canvas to PNG at higher resolution."""
        # compute size
        rw = self.model.rack_width_pixels(scale)
        rh = self.model.u_to_pixels(self.model.height_u, scale)
        img_w = int((RAIL_WIDTH_PX * 2 + rw) * scale)
        img_h = int(rh)
        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0) if transparent else (30, 30, 30))
        draw = ImageDraw.Draw(img)
        # simple rasterisation – replicate canvas drawing
        px_per_u = U_HEIGHT_PX * scale
        rail = RAIL_WIDTH_PX * scale
        left = rail
        right = rail + rw
        # stripes
        for u in range(self.model.height_u):
            y1 = int(u * px_per_u)
            y2 = int((u + 1) * px_per_u)
            colour = (45, 45, 45) if u % 2 else (37, 37, 37)
            draw.rectangle([left, y1, right, y2], fill=colour)
        # rails
        draw.line([left, 0, left, img_h], fill=(85, 85, 85), width=2)
        draw.line([right, 0, right, img_h], fill=(85, 85, 85), width=2)
        # items
        for it in self.model.items:
            y1 = int(it.u_top * px_per_u)
            y2 = int((it.u_top + it.u_height) * px_per_u)
            colour = it.style
            if (self.model.width == 10 and it.width_class == WidthClass.NINETEEN) or (
                self.model.width == 19 and it.width_class == WidthClass.TEN
            ):
                colour = "#ff4d4d"
            draw.rectangle([left, y1, right, y2], fill=colour)
            try:
                font = ImageFont.truetype("segoeui.ttf", int(10 * scale))
            except:
                font = ImageFont.load_default()
            draw.text(
                ((left + right) / 2, (y1 + y2) / 2),
                it.name,
                fill="white",
                font=font,
                anchor="mm",
            )
        # texts
        for txt in self.model.texts:
            try:
                font = ImageFont.truetype("segoeui.ttf", int(txt.font_size * scale))
            except:
                font = ImageFont.load_default()
            draw.text((txt.x * scale, txt.y * scale), txt.text, fill=txt.style, font=font)
        img.save(path)

    def render_to_pdf(self, path: str, pagesize: Tuple[float, float] = A4):
        """Render to PDF centred on page."""
        c = pdfcanvas.Canvas(path, pagesize=pagesize)
        width_pt, height_pt = pagesize
        # render canvas to PNG in memory
        import io
        buf = io.BytesIO()
        self.render_to_png(buf, transparent=False, scale=2)
        buf.seek(0)
        img = ImageReader(buf)
        iw, ih = img.getSize()
        scale = min((width_pt * 0.8) / iw, (height_pt * 0.8) / ih)
        dw = iw * scale
        dh = ih * scale
        x = (width_pt - dw) / 2
        y = (height_pt - dh) / 2
        c.drawImage(img, x, y, width=dw, height=dh)
        c.showPage()
        c.save()


# ---------- bootstrap -------------------------------------------------------
def main():
    app = RackDesignerApp()
    app.mainloop()


if __name__ == "__main__":
    main()