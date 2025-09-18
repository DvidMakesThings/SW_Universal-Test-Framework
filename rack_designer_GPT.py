#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rack Designer (dark mode) – single-file app
===========================================

Cross-platform rack layout tool for 10" and 19" racks.
- Python 3.10+
- GUI: customtkinter + tkinter.Canvas
- Export: Pillow (PNG), reportlab (PDF)
- Project save/load: JSON (.rackproj)
- Packaging: PyInstaller-friendly (single file)

Author: ChatGPT for Dave
License: MIT
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import uuid
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Tuple, Any

# GUI
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
try:
    import customtkinter as ctk
except Exception as e:
    raise SystemExit("customtkinter is required. pip install customtkinter") from e

# Images / export
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as e:
    raise SystemExit("Pillow is required. pip install Pillow") from e

# PDF export
try:
    from reportlab.lib.pagesizes import A4, letter
    from reportlab.lib import colors as rl_colors
    from reportlab.pdfgen import canvas as rl_canvas
except Exception as e:
    raise SystemExit("reportlab is required. pip install reportlab") from e


APP_VERSION = "1.0.0"
PROJECT_VERSION = 1  # increment for backward-compatible schema changes

# -----------------------------
# Model
# -----------------------------

WIDTH_10 = "10in"
WIDTH_19 = "19in"
WIDTH_BOTH = "both"

PALETTE_ITEMS = [
    # (type, default_u_height, width_class, default_name, color)
    ("Blank 1U", 1, WIDTH_BOTH, "1U Blank", "#444A50"),
    ("Blank 2U", 2, WIDTH_BOTH, "2U Blank", "#444A50"),
    ("Blank 3U", 3, WIDTH_BOTH, "3U Blank", "#444A50"),
    ("Patch Panel", 1, WIDTH_19, "Patch Panel 24p", "#2F7ED8"),
    ("Patch Panel (10\")", 1, WIDTH_10, "Patch Panel 12p", "#2F7ED8"),
    ("Cable Manager 1U", 1, WIDTH_BOTH, "Cable Manager 1U", "#7F8C8D"),
    ("Cable Manager 2U", 2, WIDTH_BOTH, "Cable Manager 2U", "#7F8C8D"),
    ("PDU 1U (19\")", 1, WIDTH_19, "PDU 1U (19\")", "#C0392B"),
    ("PDU 1U (10\")", 1, WIDTH_10, "PDU 1U (10\")", "#C0392B"),
    ("Switch 1U", 1, WIDTH_19, "Switch 1U", "#27AE60"),
    ("UPS 2U", 2, WIDTH_BOTH, "UPS 2U", "#8E44AD"),
    ("Shelf 2U", 2, WIDTH_BOTH, "Shelf 2U", "#95A5A6"),
    ("Server 2U", 2, WIDTH_19, "Server 2U", "#E67E22"),
    ("Generic N-U", 1, WIDTH_BOTH, "Generic", "#BDC3C7"),
]

def gen_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Item:
    id: str
    type: str
    name: str
    u_top: int
    u_height: int
    color: str = "#888888"
    locked: bool = False
    width_class: str = WIDTH_BOTH   # 10in / 19in / both

    def bbox_u(self) -> Tuple[int, int]:
        return (self.u_top, self.u_top + self.u_height - 1)

    def to_json(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "Item":
        # Backward compatibility defaults
        return Item(
            id=d.get("id", gen_id()),
            type=d["type"],
            name=d.get("name", d["type"]),
            u_top=int(d["u_top"]),
            u_height=int(d["u_height"]),
            color=d.get("color", "#888888"),
            locked=bool(d.get("locked", False)),
            width_class=d.get("width_class", WIDTH_BOTH),
        )


@dataclass
class TextNote:
    id: str
    x: float
    y: float
    text: str
    font_size: int = 12
    rotation: int = 0  # 0 or 90
    color: str = "#DDDDDD"

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "TextNote":
        return TextNote(
            id=d.get("id", gen_id()),
            x=float(d["x"]), y=float(d["y"]),
            text=d.get("text", ""),
            font_size=int(d.get("font_size", 12)),
            rotation=int(d.get("rotation", 0)),
            color=d.get("color", "#DDDDDD"),
        )


@dataclass
class RackModel:
    width: str = WIDTH_19
    height_u: int = 20
    items: List[Item] = field(default_factory=list)
    notes: List[TextNote] = field(default_factory=list)

    def occupied_ranges(self, ignore_id: Optional[str]=None) -> List[Tuple[int,int]]:
        ranges = []
        for it in self.items:
            if ignore_id and it.id == ignore_id:
                continue
            ranges.append((it.u_top, it.u_top + it.u_height - 1))
        return ranges

    def is_range_free(self, u_top: int, u_height: int, ignore_id: Optional[str]=None) -> bool:
        ut1 = u_top
        ub1 = u_top + u_height - 1
        if ut1 < 1 or ub1 > self.height_u:
            return False
        for (ut2, ub2) in self.occupied_ranges(ignore_id):
            # overlap?
            if not (ub1 < ut2 or ub2 < ut1):
                return False
        return True

    def find_conflicts(self, u_top: int, u_height: int, ignore_id: Optional[str]=None) -> List[Item]:
        ut1 = u_top
        ub1 = u_top + u_height - 1
        conflicts = []
        for it in self.items:
            if ignore_id and it.id == ignore_id:
                continue
            ut2, ub2 = it.u_top, it.u_top + it.u_height - 1
            if not (ub1 < ut2 or ub2 < ut1):
                conflicts.append(it)
        return conflicts

    def add_item(self, it: Item) -> bool:
        if self.is_range_free(it.u_top, it.u_height):
            self.items.append(it)
            return True
        return False

    def remove_item(self, item_id: str) -> None:
        self.items = [i for i in self.items if i.id != item_id]

    def move_item(self, item_id: str, new_u_top: int) -> bool:
        it = self.get_item(item_id)
        if not it or it.locked:
            return False
        if self.is_range_free(new_u_top, it.u_height, ignore_id=item_id):
            it.u_top = new_u_top
            return True
        return False

    def get_item(self, item_id: str) -> Optional[Item]:
        for it in self.items:
            if it.id == item_id:
                return it
        return None

    def items_overflowing(self) -> List[Item]:
        offenders = []
        for it in self.items:
            if it.u_top + it.u_height - 1 > self.height_u:
                offenders.append(it)
        return offenders

    def reflow_pack(self) -> None:
        """Pack items from top to bottom without changing relative order."""
        # Sort by current u_top
        ordered = sorted(self.items, key=lambda i: i.u_top)
        next_free = 1
        for it in ordered:
            it.u_top = max(next_free, 1)
            next_free = it.u_top + it.u_height

    def to_json(self) -> Dict[str, Any]:
        return {
            "project_version": PROJECT_VERSION,
            "width": self.width,
            "height_u": self.height_u,
            "items": [it.to_json() for it in self.items],
            "notes": [n.to_json() for n in self.notes],
        }

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "RackModel":
        width = d.get("width", WIDTH_19) if d.get("width") in (WIDTH_10, WIDTH_19) else WIDTH_19
        height_u = int(d.get("height_u", 20))
        items = [Item.from_json(x) for x in d.get("items", [])]
        notes = [TextNote.from_json(x) for x in d.get("notes", [])]
        return RackModel(width=width, height_u=height_u, items=items, notes=notes)


# -----------------------------
# Command stack (undo/redo)
# -----------------------------

class Command:
    def do(self): ...
    def undo(self): ...

class CommandStack:
    def __init__(self, limit:int=50):
        self._undo: List[Command] = []
        self._redo: List[Command] = []
        self.limit = limit

    def push(self, cmd: Command):
        if cmd.do():
            self._undo.append(cmd)
            if len(self._undo) > self.limit:
                self._undo.pop(0)
            self._redo.clear()

    def undo(self):
        if not self._undo: return
        cmd = self._undo.pop()
        cmd.undo()
        self._redo.append(cmd)

    def redo(self):
        if not self._redo: return
        cmd = self._redo.pop()
        cmd.do()
        self._undo.append(cmd)

# Concrete commands
class AddItemCmd(Command):
    def __init__(self, model: RackModel, item: Item):
        self.model=model; self.item=item; self.added=False
    def do(self): 
        self.added = self.model.add_item(self.item)
        return self.added
    def undo(self):
        if self.added:
            self.model.remove_item(self.item.id)

class RemoveItemCmd(Command):
    def __init__(self, model: RackModel, item_id: str, snapshot: Optional[Item]=None):
        self.model=model; self.item_id=item_id; self.snapshot=snapshot
    def do(self):
        it = self.model.get_item(self.item_id)
        if it:
            self.snapshot = Item(**asdict(it))
            self.model.remove_item(self.item_id)
            return True
        return False
    def undo(self):
        if self.snapshot:
            self.model.add_item(self.snapshot)

class MoveItemCmd(Command):
    def __init__(self, model: RackModel, item_id: str, new_top: int):
        self.model=model; self.item_id=item_id; self.new_top=new_top; self.old_top=None
    def do(self):
        it = self.model.get_item(self.item_id)
        if not it: return False
        self.old_top = it.u_top
        ok = self.model.move_item(self.item_id, self.new_top)
        return ok
    def undo(self):
        if self.old_top is not None:
            self.model.move_item(self.item_id, self.old_top)

class EditItemCmd(Command):
    def __init__(self, model:RackModel, item_id:str, changes:Dict[str, Any]):
        self.model=model; self.item_id=item_id; self.changes=changes; self.prev={}
    def do(self):
        it = self.model.get_item(self.item_id)
        if not it: return False
        self.prev = {}
        for k,v in self.changes.items():
            self.prev[k]=getattr(it,k)
            setattr(it,k,v)
        return True
    def undo(self):
        it = self.model.get_item(self.item_id)
        if not it: return
        for k,v in self.prev.items():
            setattr(it,k,v)

class ReflowCmd(Command):
    def __init__(self, model:RackModel):
        self.model=model; self.snapshot=None
    def do(self):
        self.snapshot = json.loads(json.dumps(self.model.to_json()))
        self.model.reflow_pack()
        return True
    def undo(self):
        if self.snapshot:
            restored = RackModel.from_json(self.snapshot)
            self.model.width = restored.width
            self.model.height_u = restored.height_u
            self.model.items = restored.items
            self.model.notes = restored.notes


# -----------------------------
# Renderers (Tk / PNG / PDF)
# -----------------------------

class BaseRenderer:
    def __init__(self, u_px: int, rack_w_px: int, rack_h_u: int):
        self.u_px = u_px
        self.rack_w_px = rack_w_px
        self.rack_h_u = rack_h_u

    def draw_rect(self, *args, **kwargs): ...
    def draw_text(self, *args, **kwargs): ...
    def draw_line(self, *args, **kwargs): ...

    def draw_rack(self, model: RackModel, show_labels=True, alt_shading=True, show_rails=True, cable_guides=False, width=WIDTH_19):
        total_h = self.rack_h_u * self.u_px
        # Background
        self.draw_rect(0, 0, self.rack_w_px, total_h, fill="#111111", outline="#111111")
        # Alt U shading
        if alt_shading:
            for u in range(1, self.rack_h_u+1):
                if u % 2 == 0:
                    y0=(u-1)*self.u_px; y1=u*self.u_px
                    self.draw_rect(0, y0, self.rack_w_px, y1, fill="#141414", outline="")
        # Rails
        if show_rails:
            rail_w = 16
            self.draw_rect(0, 0, rail_w, total_h, fill="#2a2a2a", outline="#555555")
            self.draw_rect(self.rack_w_px-rail_w, 0, self.rack_w_px, total_h, fill="#2a2a2a", outline="#555555")
        # U markers
        if show_labels:
            for u in range(1, self.rack_h_u+1):
                y = u*self.u_px - 3
                self.draw_line(0, y, self.rack_w_px, y, fill="#222222")
                self.draw_text(4, y-12, f"U{u}", fill="#888888", anchor="nw", size=10)

        # Cable guides (simple vertical dotted lines)
        if cable_guides:
            for x in (40, self.rack_w_px-40):
                for y in range(0, total_h, 8):
                    self.draw_line(x, y, x, y+4, fill="#333333")

        # Items
        for it in sorted(model.items, key=lambda i: i.u_top):
            y0=(it.u_top-1)*self.u_px; y1=y0+it.u_height*self.u_px
            x0=24; x1=self.rack_w_px-24
            # width mismatch indicator
            mismatch = (it.width_class != WIDTH_BOTH and it.width_class != width)
            fill = it.color
            self.draw_rect(x0, y0+1, x1, y1-1, fill=fill, outline="#000000")
            self.draw_text(x0+6, (y0+y1)//2-7, it.name, fill="#111111", anchor="nw", size=12)
            if mismatch:
                # small corner triangle
                self.draw_rect(x1-14, y0+1, x1-1, y0+14, fill="#FFD166", outline="#111111")
                self.draw_text(x1-13, y0+1, "!", fill="#111111", anchor="nw", size=10)

        # Notes
        for n in model.notes:
            if n.rotation==0:
                self.draw_text(n.x, n.y, n.text, fill=n.color, anchor="nw", size=n.font_size)
            else:
                # crude rotation indicator – export paths handle 90° properly, Tk uses text + rotate via canvas method
                self.draw_text(n.x, n.y, n.text, fill=n.color, anchor="nw", size=n.font_size, rotate=90)


class TkRenderer(BaseRenderer):
    def __init__(self, canvas: tk.Canvas, u_px:int, rack_w_px:int, rack_h_u:int):
        super().__init__(u_px, rack_w_px, rack_h_u)
        self.canvas = canvas
        self.font_cache: Dict[Tuple[str,int], Any] = {}

    def draw_rect(self, x0,y0,x1,y1, fill="", outline=""):
        self.canvas.create_rectangle(x0,y0,x1,y1, fill=fill, outline=outline, width=1)

    def draw_text(self, x,y, text, fill="#FFFFFF", anchor="nw", size=12, rotate: Optional[int]=None):
        item = self.canvas.create_text(x,y, text=text, fill=fill, anchor=anchor, font=("Consolas", size))
        if rotate == 90:
            try:
                self.canvas.itemconfig(item, angle=90)
            except tk.TclError:
                # some Tk builds don't support angle, ignore
                pass

    def draw_line(self, x0,y0,x1,y1, fill="#FFFFFF"):
        self.canvas.create_line(x0,y0,x1,y1, fill=fill)


class PILRenderer(BaseRenderer):
    def __init__(self, img: Image.Image, u_px:int, rack_w_px:int, rack_h_u:int):
        super().__init__(u_px, rack_w_px, rack_h_u)
        self.img = img
        self.draw = ImageDraw.Draw(img)
        try:
            self.font_base = ImageFont.truetype("DejaVuSans.ttf", 12)
        except Exception:
            self.font_base = ImageFont.load_default()

    def _font(self, size:int):
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return self.font_base

    def draw_rect(self, x0,y0,x1,y1, fill="", outline=""):
        if fill:
            self.draw.rectangle([x0,y0,x1,y1], fill=fill, outline=outline if outline else None)
        else:
            self.draw.rectangle([x0,y0,x1,y1], outline=outline if outline else None)

    def draw_text(self, x,y, text, fill="#FFFFFF", anchor="nw", size=12, rotate: Optional[int]=None):
        font = self._font(size)
        if rotate == 90:
            # draw rotated via temp image
            bbox = self.draw.textbbox((0,0), text, font=font)
            w = bbox[2]-bbox[0]; h=bbox[3]-bbox[1]
            tmp = Image.new("RGBA", (w,h), (0,0,0,0))
            ImageDraw.Draw(tmp).text((0,0), text, fill=fill, font=font)
            tmp = tmp.rotate(90, expand=True)
            self.img.paste(tmp, (int(x), int(y)), tmp)
        else:
            self.draw.text((x,y), text, fill=fill, font=font)

    def draw_line(self, x0,y0,x1,y1, fill="#FFFFFF"):
        self.draw.line([x0,y0,x1,y1], fill=fill, width=1)


class PDFRenderer(BaseRenderer):
    def __init__(self, pdf: rl_canvas.Canvas, u_px:int, rack_w_px:int, rack_h_u:int, origin:Tuple[float,float]):
        super().__init__(u_px, rack_w_px, rack_h_u)
        self.pdf = pdf
        self.ox, self.oy = origin  # translate
        self.pdf.translate(self.ox, self.oy)

    def draw_rect(self, x0,y0,x1,y1, fill="", outline=""):
        w = x1-x0; h=y1-y0
        if fill:
            self.pdf.setFillColor(rl_colors.HexColor(fill))
        else:
            self.pdf.setFillColor(rl_colors.transparent)
        if outline:
            self.pdf.setStrokeColor(rl_colors.HexColor(outline))
        else:
            self.pdf.setStrokeColor(rl_colors.transparent)
        self.pdf.rect(x0, y0, w, h, fill=1 if fill else 0, stroke=1 if outline else 0)

    def draw_text(self, x,y, text, fill="#FFFFFF", anchor="nw", size=12, rotate: Optional[int]=None):
        self.pdf.setFillColor(rl_colors.HexColor(fill))
        self.pdf.setFont("Helvetica", size)
        if rotate == 90:
            self.pdf.saveState()
            self.pdf.translate(x, y)
            self.pdf.rotate(90)
            self.pdf.drawString(0, 0, text)
            self.pdf.restoreState()
        else:
            self.pdf.drawString(x, y, text)

    def draw_line(self, x0,y0,x1,y1, fill="#FFFFFF"):
        self.pdf.setStrokeColor(rl_colors.HexColor(fill))
        self.pdf.line(x0,y0,x1,y1)


# -----------------------------
# GUI Views
# -----------------------------

U_PX_DEFAULT = 22      # pixels per U (canvas base scale)
RACK_WIDTH_PX_19 = 460
RACK_WIDTH_PX_10 = 360

class RackCanvasView(ctk.CTkFrame):
    def __init__(self, master, model:RackModel, cmd:CommandStack, status_var:tk.StringVar, settings:Dict[str,bool]):
        super().__init__(master)
        self.model = model
        self.cmd = cmd
        self.settings = settings
        self.status_var = status_var

        self.scale = 1.0
        self.u_px = U_PX_DEFAULT
        self.canvas = tk.Canvas(self, bg="#111111", highlightthickness=0, confine=False)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_drop)

        # panning
        self.canvas.bind("<Button-2>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))

        # zoom
        self.canvas.bind("<Control-MouseWheel>", self.on_zoom)

        # selection
        self.selected: List[str] = []  # item ids; notes use "note:<id>"
        self.dragging: Optional[Tuple[str,int]] = None  # (id, start_u_top) for items or ("note:<id>", y0)
        self.drag_start = (0,0)
        self.drag_preview = None  # canvas rect for preview

        # Right-click menu
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Rename", command=self.rename_selected)
        self.menu.add_command(label="Duplicate", command=self.duplicate_selected)
        self.menu.add_command(label="Lock/Unlock", command=self.toggle_lock_selected)
        self.menu.add_separator()
        self.menu.add_command(label="Delete", command=self.delete_selected)
        self.canvas.bind("<Button-3>", self.on_right_click)

        # Keyboard
        self.bind_all("<Delete>", lambda e: self.delete_selected())
        self.bind_all("<Control-z>", lambda e: self.cmd.undo() or self.redraw())
        self.bind_all("<Control-y>", lambda e: self.cmd.redo() or self.redraw())

        self.redraw()

    # --- coords & drawing helpers ---
    def rack_w_px(self) -> int:
        return RACK_WIDTH_PX_19 if self.model.width == WIDTH_19 else RACK_WIDTH_PX_10

    def y_to_u(self, y: float) -> int:
        # canvas local Y to nearest U
        u = int(round(y / (self.u_px)))
        return max(1, min(self.model.height_u, u))

    def u_to_y(self, u: int) -> int:
        return int((u-1) * self.u_px)

    def _on_resize(self, _):
        self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        total_h = int(self.model.height_u * self.u_px)
        w = int(self.rack_w_px())
        self.canvas.config(scrollregion=(0,0,w,total_h))
        renderer = TkRenderer(self.canvas, self.u_px, w, self.model.height_u)
        renderer.draw_rack(self.model,
                           show_labels=self.settings.get("show_u_labels", True),
                           alt_shading=self.settings.get("alt_u_shading", True),
                           show_rails=self.settings.get("show_rails", True),
                           cable_guides=self.settings.get("cable_guides", False),
                           width=self.model.width)
        # selection outlines
        for sid in self.selected:
            if sid.startswith("note:"):
                nid = sid.split(":",1)[1]
                note = next((n for n in self.model.notes if n.id==nid), None)
                if note:
                    x,y = note.x, note.y
                    self.canvas.create_rectangle(x-4,y-4,x+200,y+24, outline="#55A7FF")
            else:
                it = self.model.get_item(sid)
                if it:
                    y0=self.u_to_y(it.u_top); y1=self.u_to_y(it.u_top+it.u_height)+self.u_px
                    x0=24; x1=self.rack_w_px()-24
                    self.canvas.create_rectangle(x0,y0+1,x1,y1-1, outline="#55A7FF", width=2)

    # --- selection helpers ---
    def clear_selection(self):
        self.selected.clear()
        self.status_var.set("Ready")
        self.redraw()

    def select_item_at(self, x: int, y: int, add: bool):
        # check notes first
        for n in reversed(self.model.notes):
            # loose bbox
            if n.x-6 <= x <= n.x+220 and n.y-10 <= y <= n.y+28:
                sid=f"note:{n.id}"
                if add:
                    if sid not in self.selected: self.selected.append(sid)
                else:
                    self.selected=[sid]
                self.status_var.set(f"Note: \"{n.text}\"")
                self.redraw()
                return

        # then items
        for it in sorted(self.model.items, key=lambda i: i.u_top, reverse=True):
            y0=self.u_to_y(it.u_top); y1=self.u_to_y(it.u_top+it.u_height)+self.u_px
            x0=24; x1=self.rack_w_px()-24
            if x0 <= x <= x1 and y0 <= y <= y1:
                if add:
                    if it.id not in self.selected: self.selected.append(it.id)
                else:
                    self.selected=[it.id]
                self.status_var.set(f"Selected: {it.name} @U{it.u_top}")
                self.redraw()
                return

        self.clear_selection()

    # --- mouse handlers ---
    def on_left_click(self, e):
        add = (e.state & 0x0001) != 0  # Shift
        self.select_item_at(e.x, e.y, add=add)
        self.drag_start = (e.x, e.y)
        if self.selected:
            self.dragging = (self.selected[0], self._selected_anchor_value())

    def _selected_anchor_value(self) -> int:
        sid = self.selected[0]
        if sid.startswith("note:"):
            nid = sid.split(":",1)[1]
            n = next((x for x in self.model.notes if x.id==nid), None)
            return int(n.y if n else 0)
        else:
            it = self.model.get_item(sid)
            return int(it.u_top if it else 0)

    def on_drag(self, e):
        if not self.dragging:
            return
        sid, anchor = self.dragging
        dx = e.x - self.drag_start[0]
        dy = e.y - self.drag_start[1]

        if sid.startswith("note:"):
            nid = sid.split(":",1)[1]
            note = next((n for n in self.model.notes if n.id==nid), None)
            if note:
                note.x += dx
                note.y += dy
                self.drag_start = (e.x, e.y)
                self.status_var.set(f"Moving note: {int(note.x)}, {int(note.y)}")
                self.redraw()
            return

        # items: snap to U
        it = self.model.get_item(sid)
        if not it or it.locked:
            return
        # proposed new U
        y_current = self.u_to_y(anchor) + dy
        u_new = self.y_to_u(y_current)
        # preview rectangle in red if conflicts
        conflicts = self.model.find_conflicts(u_new, it.u_height, ignore_id=it.id)
        if self.drag_preview:
            self.canvas.delete(self.drag_preview)
            self.drag_preview=None
        y0=self.u_to_y(u_new); y1=self.u_to_y(u_new+it.u_height)+self.u_px
        x0=24; x1=self.rack_w_px()-24
        outline = "#FF5555" if conflicts or (u_new<1 or u_new+it.u_height-1>self.model.height_u) else "#55FF88"
        self.drag_preview = self.canvas.create_rectangle(x0,y0+1,x1,y1-1, outline=outline, width=2, dash=(3,2))

    def on_drop(self, e):
        if not self.dragging:
            return
        sid, anchor = self.dragging
        self.dragging = None
        if self.drag_preview:
            self.canvas.delete(self.drag_preview); self.drag_preview=None

        if sid.startswith("note:"):
            # Note move already applied; add to undo stack as edit
            nid = sid.split(":",1)[1]
            self.cmd.push(EditItemCmdDummyNoteMove(self.model, nid))  # stores snapshot
            self.redraw()
            return

        it = self.model.get_item(sid)
        if not it or it.locked:
            return
        # compute final U
        dy = e.y - self.drag_start[1]
        y_current = self.u_to_y(anchor) + dy
        u_new = self.y_to_u(y_current)
        if self.model.is_range_free(u_new, it.u_height, ignore_id=it.id):
            self.cmd.push(MoveItemCmd(self.model, it.id, u_new))
            self.status_var.set(f"Moved to U{u_new}")
        else:
            self.status_var.set("Move blocked (collision or out-of-range).")
        self.redraw()

    # --- context actions ---
    def on_right_click(self, e):
        try:
            self.select_item_at(e.x, e.y, add=False)
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def rename_selected(self):
        if not self.selected: return
        sid = self.selected[0]
        if sid.startswith("note:"):
            nid = sid.split(":",1)[1]
            note = next((n for n in self.model.notes if n.id==nid), None)
            if note:
                new = simpledialog.askstring("Edit Note", "Text:", initialvalue=note.text, parent=self)
                if new is not None:
                    before = json.loads(json.dumps(self.model.to_json()))
                    note.text = new
                    self.cmd.push(EditModelSnapshotCmd(self.model, before))
                    self.redraw()
            return
        it = self.model.get_item(sid)
        if not it: return
        new = simpledialog.askstring("Rename", "Name:", initialvalue=it.name, parent=self)
        if new is not None:
            self.cmd.push(EditItemCmd(self.model, it.id, {"name": new}))
            self.redraw()

    def duplicate_selected(self):
        if not self.selected: return
        sid = self.selected[0]
        if sid.startswith("note:"):
            nid = sid.split(":",1)[1]
            note = next((n for n in self.model.notes if n.id==nid), None)
            if not note: return
            new_note = TextNote(id=gen_id(), x=note.x+10, y=note.y+10, text=note.text, font_size=note.font_size, rotation=note.rotation, color=note.color)
            before = json.loads(json.dumps(self.model.to_json()))
            self.model.notes.append(new_note)
            self.cmd.push(EditModelSnapshotCmd(self.model, before))
            self.redraw()
            return
        it = self.model.get_item(sid)
        if not it: return
        new_it = Item(id=gen_id(), type=it.type, name=it.name+" (copy)", u_top=min(self.model.height_u, it.u_top+it.u_height), u_height=it.u_height, color=it.color, locked=False, width_class=it.width_class)
        if self.model.is_range_free(new_it.u_top, new_it.u_height):
            self.cmd.push(AddItemCmd(self.model, new_it))
            self.redraw()

    def toggle_lock_selected(self):
        if not self.selected: return
        sid = self.selected[0]
        if sid.startswith("note:"):
            return
        it = self.model.get_item(sid); ifnot = it is None
        if it:
            self.cmd.push(EditItemCmd(self.model, it.id, {"locked": (not it.locked)}))
            self.redraw()

    def delete_selected(self):
        if not self.selected: return
        before = json.loads(json.dumps(self.model.to_json()))
        # remove all selected
        for sid in list(self.selected):
            if sid.startswith("note:"):
                nid = sid.split(":",1)[1]
                self.model.notes = [n for n in self.model.notes if n.id != nid]
            else:
                self.model.remove_item(sid)
        self.selected.clear()
        self.cmd.push(EditModelSnapshotCmd(self.model, before))
        self.redraw()

    def on_zoom(self, e):
        # e.delta: positive -> zoom in, negative -> out
        factor = 1.1 if e.delta>0 else 0.9
        self.u_px = max(10, min(60, int(self.u_px*factor)))
        self.redraw()


class EditModelSnapshotCmd(Command):
    """Generic snapshot-based edit (for complex multi changes)."""
    def __init__(self, model:RackModel, before_snapshot: Dict[str,Any]):
        self.model=model
        self.before=before_snapshot
        self.after=None
    def do(self):
        self.after = json.loads(json.dumps(self.model.to_json()))
        return True
    def undo(self):
        snap = self.before
        restored = RackModel.from_json(snap)
        self.model.width = restored.width
        self.model.height_u = restored.height_u
        self.model.items = restored.items
        self.model.notes = restored.notes

class EditItemCmdDummyNoteMove(Command):
    """Stores before/after for a note move already applied interactively."""
    def __init__(self, model:RackModel, note_id:str):
        self.model=model; self.note_id=note_id; self.before=None; self.after=None
    def do(self):
        self.after = json.loads(json.dumps(self.model.to_json()))
        return True
    def undo(self):
        if self.before:
            restored = RackModel.from_json(self.before)
            self.model.width = restored.width
            self.model.height_u = restored.height_u
            self.model.items = restored.items
            self.model.notes = restored.notes
    def set_before(self, snap):
        self.before = snap


# -----------------------------
# Palette & Inspector
# -----------------------------

class PaletteView(ctk.CTkFrame):
    def __init__(self, master, on_spawn):
        super().__init__(master, width=220)
        self.on_spawn = on_spawn
        ctk.CTkLabel(self, text="Components", anchor="w").pack(fill="x", padx=8, pady=(8,4))
        self.list = ctk.CTkScrollableFrame(self, width=200, height=400)
        self.list.pack(fill="both", expand=True, padx=6, pady=(0,8))
        for typ,u_h,width_cls,name,color in PALETTE_ITEMS:
            btn = ctk.CTkButton(self.list, text=f"{typ} ({width_cls})", command=lambda t=typ,uh=u_h,wc=width_cls,n=name,c=color: self.spawn(t,uh,wc,n,c))
            btn.pack(fill="x", padx=6, pady=4)

        # Text tool
        ctk.CTkButton(self, text="Text Label Tool", command=self.spawn_text).pack(fill="x", padx=6, pady=8)

    def spawn(self, typ, u_h, width_cls, name, color):
        self.on_spawn(typ, u_h, width_cls, name, color)

    def spawn_text(self):
        self.on_spawn("TEXT", 0, WIDTH_BOTH, "Text", "#DDDDDD")


class InspectorView(ctk.CTkFrame):
    def __init__(self, master, model:RackModel, canvas: RackCanvasView, cmd:CommandStack):
        super().__init__(master, width=260)
        self.model=model; self.canvas=canvas; self.cmd=cmd

        ctk.CTkLabel(self, text="Inspector", anchor="w").pack(fill="x", padx=8, pady=(8,4))
        self.name_var = tk.StringVar()
        self.u_top_var = tk.StringVar()
        self.u_height_var = tk.StringVar()
        self.color_var = tk.StringVar()
        self.lock_var = tk.BooleanVar()

        self.name_entry = ctk.CTkEntry(self, textvariable=self.name_var, placeholder_text="Name")
        self.name_entry.pack(fill="x", padx=8, pady=4)
        self.name_entry.bind("<Return>", lambda e: self.apply())

        row = ctk.CTkFrame(self); row.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(row, text="Top U").pack(side="left"); ctk.CTkEntry(row, width=60, textvariable=self.u_top_var).pack(side="left", padx=6)
        ctk.CTkLabel(row, text="Height U").pack(side="left"); ctk.CTkEntry(row, width=60, textvariable=self.u_height_var).pack(side="left", padx=6)

        ctk.CTkLabel(self, text="Color (hex)").pack(fill="x", padx=8)
        ctk.CTkEntry(self, textvariable=self.color_var).pack(fill="x", padx=8, pady=4)

        ctk.CTkCheckBox(self, text="Locked", variable=self.lock_var, command=self.apply).pack(anchor="w", padx=8, pady=4)

        ctk.CTkButton(self, text="Apply", command=self.apply).pack(fill="x", padx=8, pady=(6,12))

        # Settings toggles
        ctk.CTkLabel(self, text="View Settings", anchor="w").pack(fill="x", padx=8, pady=(8,4))
        self.view_toggles = {
            "show_u_labels": tk.BooleanVar(value=True),
            "alt_u_shading": tk.BooleanVar(value=True),
            "show_rails": tk.BooleanVar(value=True),
            "cable_guides": tk.BooleanVar(value=False),
        }
        for key, var in self.view_toggles.items():
            ctk.CTkCheckBox(self, text=key.replace("_"," ").title(), variable=var, command=self.on_view_changed).pack(anchor="w", padx=8, pady=2)

        # Light/Dark toggle
        self.mode_var = tk.StringVar(value=ctk.get_appearance_mode())
        ctk.CTkButton(self, text="Toggle Light/Dark", command=self.toggle_theme).pack(fill="x", padx=8, pady=(12,8))

        # Listen selection changes by polling (simple)
        self.after(200, self.refresh_ui)

    def on_view_changed(self):
        for k,v in self.view_toggles.items():
            self.canvas.settings[k] = bool(v.get())
        self.canvas.redraw()

    def toggle_theme(self):
        ctk.set_appearance_mode("Light" if ctk.get_appearance_mode()=="Dark" else "Dark")

    def refresh_ui(self):
        # update from selected item
        if self.canvas.selected:
            sid = self.canvas.selected[0]
            if sid.startswith("note:"):
                self.name_var.set("(Text Note)")
                self.u_top_var.set("-")
                self.u_height_var.set("-")
                self.color_var.set("")
                self.lock_var.set(False)
            else:
                it = self.model.get_item(sid)
                if it:
                    self.name_var.set(it.name)
                    self.u_top_var.set(str(it.u_top))
                    self.u_height_var.set(str(it.u_height))
                    self.color_var.set(it.color)
                    self.lock_var.set(it.locked)
        else:
            # clear fields
            # keep previous values for convenience
            pass
        self.after(250, self.refresh_ui)

    def apply(self):
        if not self.canvas.selected:
            return
        sid = self.canvas.selected[0]
        if sid.startswith("note:"):
            return
        it = self.model.get_item(sid)
        if not it: return
        changes = {}
        if self.name_var.get() != it.name:
            changes["name"]=self.name_var.get()
        try:
            new_top = int(self.u_top_var.get())
            if new_top != it.u_top:
                # use Move command for collision-aware apply
                if self.model.is_range_free(new_top, it.u_height, ignore_id=it.id):
                    self.cmd.push(MoveItemCmd(self.model, it.id, new_top))
                else:
                    messagebox.showwarning("Invalid", "Target U range is occupied or out of bounds.")
        except Exception:
            pass
        try:
            new_h = int(self.u_height_var.get())
            if new_h != it.u_height and new_h>=1:
                if self.model.is_range_free(it.u_top, new_h, ignore_id=it.id):
                    changes["u_height"]=new_h
                else:
                    messagebox.showwarning("Invalid", "New height overlaps with neighbors.")
        except Exception:
            pass
        col = self.color_var.get().strip()
        if col and col != it.color:
            changes["color"]=col
        if self.lock_var.get() != it.locked:
            changes["locked"]=bool(self.lock_var.get())
        if changes:
            self.cmd.push(EditItemCmd(self.model, it.id, changes))
        self.canvas.redraw()


# -----------------------------
# Main Application
# -----------------------------

class RackDesignerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_default_color_theme("dark-blue")
        ctk.set_appearance_mode("Dark")
        self.title("Rack Designer")
        self.geometry("1280x800")

        # Model
        self.model = RackModel(width=WIDTH_19, height_u=20)
        self.cmd = CommandStack(limit=100)
        self.settings = {"show_u_labels": True, "alt_u_shading": True, "show_rails": True, "cable_guides": False}

        # Status
        self.status_var = tk.StringVar(value="Ready")

        # Layout: left palette, center canvas, right inspector
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        # Toolbar
        toolbar = ctk.CTkFrame(self)
        toolbar.grid(row=0, column=0, columnspan=3, sticky="ew")
        for i in range(10): toolbar.columnconfigure(i, weight=0)
        toolbar.columnconfigure(9, weight=1)

        ctk.CTkButton(toolbar, text="New", command=self.new_project).grid(row=0, column=0, padx=6, pady=6)
        ctk.CTkButton(toolbar, text="Open", command=self.open_project).grid(row=0, column=1, padx=6, pady=6)
        ctk.CTkButton(toolbar, text="Save", command=self.save_project).grid(row=0, column=2, padx=6, pady=6)
        ctk.CTkButton(toolbar, text="Save As", command=self.save_project_as).grid(row=0, column=3, padx=6, pady=6)
        ctk.CTkButton(toolbar, text="Export PNG", command=self.export_png).grid(row=0, column=4, padx=6, pady=6)
        ctk.CTkButton(toolbar, text="Export PDF", command=self.export_pdf).grid(row=0, column=5, padx=6, pady=6)

        ctk.CTkLabel(toolbar, text="Width").grid(row=0, column=6, padx=(20,4))
        self.width_cmb = ctk.CTkComboBox(toolbar, values=[WIDTH_10, WIDTH_19], command=self.on_width_change)
        self.width_cmb.set(WIDTH_19); self.width_cmb.grid(row=0, column=7, padx=4, pady=6)

        ctk.CTkLabel(toolbar, text="Height (U)").grid(row=0, column=8, padx=(16,4))
        self.height_cmb = ctk.CTkComboBox(toolbar, values=[str(x) for x in range(6,41)], command=self.on_height_change, width=80)
        self.height_cmb.set("20"); self.height_cmb.grid(row=0, column=9, padx=4, pady=6, sticky="w")

        # Body
        self.palette = PaletteView(self, self.spawn_from_palette)
        self.palette.grid(row=1, column=0, sticky="nsw")

        self.canvas_view = RackCanvasView(self, self.model, self.cmd, self.status_var, self.settings)
        self.canvas_view.grid(row=1, column=1, sticky="nsew", padx=6, pady=6)

        self.inspector = InspectorView(self, self.model, self.canvas_view, self.cmd)
        self.inspector.grid(row=1, column=2, sticky="nse")

        # Status bar
        status = ctk.CTkFrame(self)
        status.grid(row=2, column=0, columnspan=3, sticky="ew")
        ctk.CTkLabel(status, textvariable=self.status_var, anchor="w").pack(fill="x", padx=8, pady=4)

        # File path
        self.current_path: Optional[str] = None

        # Shortcuts
        self.bind_all("<Control-n>", lambda e: self.new_project())
        self.bind_all("<Control-o>", lambda e: self.open_project())
        self.bind_all("<Control-s>", lambda e: self.save_project())
        self.bind_all("<Control-S>", lambda e: self.save_project_as())

        # New project dialog on start
        self.after(200, self.new_project)

    # --- Toolbar actions ---

    def new_project(self):
        dlg = NewProjectDialog(self, default_height=20, default_width=self.model.width)
        self.wait_window(dlg)
        if not dlg.result:
            return
        width, height = dlg.result
        before = json.loads(json.dumps(self.model.to_json()))
        self.model = RackModel(width=width, height_u=height)
        self.canvas_view.model = self.model
        self.inspector.model = self.model
        self.cmd = CommandStack(limit=100)
        self.canvas_view.cmd = self.cmd
        self.current_path = None
        self.width_cmb.set(self.model.width)
        self.height_cmb.set(str(self.model.height_u))
        self.canvas_view.redraw()

    def on_width_change(self, value):
        before = json.loads(json.dumps(self.model.to_json()))
        self.model.width = value
        self.cmd.push(EditModelSnapshotCmd(self.model, before))
        self.canvas_view.redraw()

    def on_height_change(self, value):
        new_h = int(value)
        before = json.loads(json.dumps(self.model.to_json()))
        self.model.height_u = new_h
        offenders = self.model.items_overflowing()
        self.cmd.push(EditModelSnapshotCmd(self.model, before))
        self.canvas_view.redraw()
        if offenders:
            self.handle_overflow(offenders)

    def handle_overflow(self, offenders: List[Item]):
        names = "\n".join([f"- {it.name} @U{it.u_top}-{it.u_top+it.u_height-1}" for it in offenders])
        msg = ("Some items overflow the new rack height:\n\n"
               f"{names}\n\n"
               "Options:\n"
               " - Reflow: pack items from top.\n"
               " - Keep: mark as overflow (hidden).")
        dlg = ctk.CTkInputDialog(text=msg, title="Overflow", placeholder_text="Type REFLOW or KEEP")
        ans = dlg.get_input()
        if ans and ans.strip().upper().startswith("REFLOW"):
            self.cmd.push(ReflowCmd(self.model))
            self.canvas_view.redraw()
        # KEEP -> do nothing (items visually cut off)

    def open_project(self):
        path = filedialog.askopenfilename(filetypes=[("Rack Project",".rackproj"),("JSON",".json"),("All","*.*")])
        if not path: return
        try:
            with open(path,"r",encoding="utf-8") as f:
                data=json.load(f)
            self.model = RackModel.from_json(data)
            self.canvas_view.model = self.model
            self.inspector.model = self.model
            self.cmd = CommandStack(limit=100)
            self.canvas_view.cmd = self.cmd
            self.current_path = path
            self.width_cmb.set(self.model.width)
            self.height_cmb.set(str(self.model.height_u))
            self.canvas_view.redraw()
            self.status_var.set(f"Loaded: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Open failed", str(e))

    def save_project(self):
        if not self.current_path:
            return self.save_project_as()
        try:
            with open(self.current_path,"w",encoding="utf-8") as f:
                json.dump(self.model.to_json(), f, indent=2)
            self.status_var.set("Saved.")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def save_project_as(self):
        path = filedialog.asksaveasfilename(defaultextension=".rackproj", filetypes=[("Rack Project",".rackproj")])
        if not path: return
        self.current_path = path
        self.save_project()

    def export_png(self):
        # Render to offscreen PIL at 2x scale
        scale = 2
        u_px = U_PX_DEFAULT * scale
        w = (RACK_WIDTH_PX_19 if self.model.width==WIDTH_19 else RACK_WIDTH_PX_10)
        w *= scale
        h = self.model.height_u * u_px
        img = Image.new("RGBA", (int(w), int(h)), (0,0,0,0))
        PILRenderer(img, u_px, int(w), self.model.height_u).draw_rack(
            self.model,
            show_labels=self.settings.get("show_u_labels", True),
            alt_shading=self.settings.get("alt_u_shading", True),
            show_rails=self.settings.get("show_rails", True),
            cable_guides=self.settings.get("cable_guides", False),
            width=self.model.width,
        )
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG",".png")])
        if not path: return
        img.save(path)
        self.status_var.set(f"PNG exported: {os.path.basename(path)}")

    def export_pdf(self):
        # Select page size
        choice = simpledialog.askstring("PDF Page", "A4 or Letter?", initialvalue="A4", parent=self)
        page = A4 if (choice and choice.strip().lower().startswith("a4")) else letter
        pw, ph = page

        # Desired rack drawing size preserving aspect
        w_px = (RACK_WIDTH_PX_19 if self.model.width==WIDTH_19 else RACK_WIDTH_PX_10)
        h_px = self.model.height_u * U_PX_DEFAULT
        aspect = w_px / h_px
        max_w = pw * 0.8; max_h = ph * 0.8
        if max_w / max_h > aspect:
            draw_h = max_h
            draw_w = draw_h * aspect
        else:
            draw_w = max_w
            draw_h = draw_w / aspect

        u_px = draw_h / self.model.height_u
        pdf = rl_canvas.Canvas(filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF",".pdf")]), pagesize=page)
        origin = ((pw-draw_w)/2, (ph-draw_h)/2)
        PDFRenderer(pdf, int(u_px), int(draw_w), self.model.height_u, origin).draw_rack(
            self.model,
            show_labels=self.settings.get("show_u_labels", True),
            alt_shading=self.settings.get("alt_u_shading", True),
            show_rails=self.settings.get("show_rails", True),
            cable_guides=self.settings.get("cable_guides", False),
            width=self.model.width,
        )
        pdf.showPage()
        pdf.save()
        self.status_var.set("PDF exported.")

    # --- Spawning from palette ---
    def spawn_from_palette(self, typ, u_h, width_cls, name, color):
        if typ == "TEXT":
            # place at center
            x=100; y=40
            note = TextNote(id=gen_id(), x=x, y=y, text="Note", font_size=12, rotation=0, color="#DDDDDD")
            before = json.loads(json.dumps(self.model.to_json()))
            self.model.notes.append(note)
            self.cmd.push(EditModelSnapshotCmd(self.model, before))
            self.canvas_view.redraw()
            return

        # default place at first free spot
        u_top = 1
        while u_top <= self.model.height_u:
            dummy = Item(id="temp", type=typ, name=name, u_top=u_top, u_height=u_h, color=color, locked=False, width_class=width_cls)
            if self.model.is_range_free(dummy.u_top, dummy.u_height, ignore_id="temp"):
                break
            u_top += 1
        if u_top + u_h - 1 > self.model.height_u:
            messagebox.showwarning("No space", "No free space in rack.")
            return
        new = Item(id=gen_id(), type=typ, name=name, u_top=u_top, u_height=u_h, color=color, locked=False, width_class=width_cls)
        # Check width compatibility – allow place but mark visually if mismatch
        if new.width_class != WIDTH_BOTH and new.width_class != self.model.width:
            messagebox.showinfo("Width mismatch", "Placing a component that doesn't match current rack width.\nIt will show an (!) marker.")
        self.cmd.push(AddItemCmd(self.model, new))
        self.canvas_view.redraw()


class NewProjectDialog(ctk.CTkToplevel):
    def __init__(self, master, default_height=20, default_width=WIDTH_19):
        super().__init__(master)
        self.title("New Project")
        self.geometry("360x180")
        self.grab_set()
        ctk.CTkLabel(self, text="Rack Width").pack(pady=(16,6))
        self.width_cmb = ctk.CTkComboBox(self, values=[WIDTH_10, WIDTH_19])
        self.width_cmb.set(default_width); self.width_cmb.pack()
        ctk.CTkLabel(self, text="Rack Height (U)").pack(pady=(12,6))
        self.height_cmb = ctk.CTkComboBox(self, values=[str(x) for x in range(6,41)])
        self.height_cmb.set(str(default_height)); self.height_cmb.pack()
        btn = ctk.CTkButton(self, text="Create", command=self.on_ok); btn.pack(pady=12)
        self.result=None

    def on_ok(self):
        self.result = (self.width_cmb.get(), int(self.height_cmb.get()))
        self.destroy()


def main():
    app = RackDesignerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
