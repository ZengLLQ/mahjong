#!/usr/bin/env python3
"""
CLOUD DANCER & SANDSTONE MAHJONG SUITE (Single-File Edition)
============================================================
Includes:
  1. Classical 4-Player Table Mahjong (Player vs. 3 AI Opponents, Chow/Pung/Kong/Hu)
  2. 3D Layered Mahjong Solitaire (Turtle, Pyramid, & Fortress layouts with Undo/Shuffle/Hint)
  3. Gemini 3.8 Flash Sensei Advisor (via `google-genai` client.interactions.create + offline fallback)

Color Palette Constraint:
  Strictly uses Pantone 11-4201 Cloud Dancer (#F0EEE9), Warm Beige, and Layered Sandstones.
"""

from __future__ import annotations

import math
import os
import random
import threading
import time
import tkinter as tk
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

# Optional Google GenAI SDK (@gemini-skills-suite compliant)
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


# ============================================================================
# 1. STRICT COLOR PALETTE: CLOUD DANCER, WARM BEIGE & LAYERED SANDSTONES
# ============================================================================
@dataclass(frozen=True)
class Palette:
    # Cloud Dancer (Pantone 11-4201) & Ivory Highlight
    CLOUD_DANCER: str = "#F0EEE9"
    CLOUD_CREAM: str = "#F7F5F0"

    # Warm Beige Spectrum
    BEIGE_LIGHT: str = "#E6DEC8"
    BEIGE_MID: str = "#D8CCB8"
    BEIGE_DEEP: str = "#C7B79E"

    # Layered Sandstones (Stratified from Pale to Deep Umber)
    SAND_L1_PALE: str = "#B8A48A"
    SAND_L2_MID: str = "#9E876B"
    SAND_L3_WARM: str = "#856D52"
    SAND_L4_DEEP: str = "#6B543B"
    SAND_L5_UMBER: str = "#4A3826"

    @classmethod
    def layer_extrusion(cls, z: int) -> str:
        """Returns stratified sandstone shading based on 3D tile elevation."""
        ramp = [
            cls.SAND_L1_PALE,
            cls.SAND_L2_MID,
            cls.SAND_L3_WARM,
            cls.SAND_L4_DEEP,
            cls.SAND_L5_UMBER,
        ]
        return ramp[min(max(z, 0), len(ramp) - 1)]


P = Palette()


# ============================================================================
# 2. DOMAIN MODELS & TILE DEFINITIONS
# ============================================================================
class Suit(str, Enum):
    DOTS = "dots"          # Tong (Circles)
    BAMBOO = "bamboo"      # Suo (Sticks)
    CHARS = "chars"        # Wan (Characters)
    WINDS = "winds"        # East, South, West, North
    DRAGONS = "dragons"    # Zhong, Fa, Bai
    FLOWERS = "flowers"    # Seasons/Flowers (Solitaire bonus)


@dataclass(frozen=True, order=True)
class TileKind:
    suit: Suit
    value: int  # 1..9 for suits, 1..4 for winds, 1..3 for dragons, 1..8 for flowers

    @property
    def short_label(self) -> str:
        if self.suit == Suit.DOTS:
            return f"{self.value}●"
        if self.suit == Suit.BAMBOO:
            return f"{self.value}║"
        if self.suit == Suit.CHARS:
            return f"{self.value}萬"
        if self.suit == Suit.WINDS:
            return {1: "E", 2: "S", 3: "W", 4: "N"}[self.value]
        if self.suit == Suit.DRAGONS:
            return {1: "中", 2: "發", 3: "白"}[self.value]
        return f"F{self.value}"

    @property
    def hanzi(self) -> str:
        if self.suit == Suit.CHARS:
            return {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九"}[self.value]
        if self.suit == Suit.WINDS:
            return {1: "東", 2: "南", 3: "西", 4: "北"}[self.value]
        if self.suit == Suit.DRAGONS:
            return {1: "中", 2: "發", 3: "白"}[self.value]
        if self.suit == Suit.FLOWERS:
            return {1: "梅", 2: "蘭", 3: "菊", 4: "竹", 5: "春", 6: "夏", 7: "秋", 8: "冬"}[self.value]
        return str(self.value)

    @property
    def display_name(self) -> str:
        if self.suit in (Suit.DOTS, Suit.BAMBOO, Suit.CHARS):
            suit_label = {"dots": "Dots", "bamboo": "Bamboo", "chars": "Characters"}[self.suit.value]
            return f"{self.value} of {suit_label}"
        if self.suit == Suit.WINDS:
            return {1: "East Wind", 2: "South Wind", 3: "West Wind", 4: "North Wind"}[self.value]
        if self.suit == Suit.DRAGONS:
            return {1: "Red Dragon (Zhong)", 2: "Green Dragon (Fa)", 3: "White Dragon (Bai)"}[self.value]
        return f"Flower {self.hanzi}"

    def matches_solitaire(self, other: TileKind) -> bool:
        """In Solitaire, any two Flower/Season tiles within the same quartet match."""
        if self.suit == Suit.FLOWERS and other.suit == Suit.FLOWERS:
            return (self.value <= 4 and other.value <= 4) or (self.value > 4 and other.value > 4)
        return self == other


def build_standard_34_kinds() -> list[TileKind]:
    kinds: list[TileKind] = []
    for s in (Suit.DOTS, Suit.BAMBOO, Suit.CHARS):
        for v in range(1, 10):
            kinds.append(TileKind(s, v))
    for v in range(1, 5):
        kinds.append(TileKind(Suit.WINDS, v))
    for v in range(1, 4):
        kinds.append(TileKind(Suit.DRAGONS, v))
    return kinds


def build_136_wall() -> list[TileKind]:
    wall = [k for k in build_standard_34_kinds() for _ in range(4)]
    random.shuffle(wall)
    return wall


# ============================================================================
# 3. GEMINI 3.8 FLASH SENSEI ADVISOR (@gemini-skills-suite)
# ============================================================================
class GeminiMahjongSensei:
    """
    Uses `google-genai` Interactions API (`client.interactions.create`) with
    `gemini-3.8-flash` and stateful `previous_interaction_id` for tactical coaching.
    Automatically falls back to deterministic local heuristics if offline/no API key.
    """

    def __init__(self) -> None:
        self.client: Optional[genai.Client] = None
        self.previous_interaction_id: Optional[str] = None
        self.online = False
        if HAS_GENAI and os.environ.get("GEMINI_API_KEY"):
            try:
                self.client = genai.Client()
                self.online = True
            except Exception:
                self.online = False

    def ask_sensei_async(
            self,
            prompt: str,
            fallback_fn: Callable[[], str],
            callback: Callable[[str], None],
    ) -> None:
        def _worker() -> None:
            if self.online and self.client is not None:
                try:
                    kwargs: dict = {
                        "model": "gemini-3.8-flash",
                        "input": (
                            "You are a concise, calm Mahjong Grandmaster Sensei. "
                            "Give a 1-to-2 sentence tactical recommendation based on this state:\n"
                            f"{prompt}"
                        ),
                    }
                    if self.previous_interaction_id:
                        kwargs["previous_interaction_id"] = self.previous_interaction_id
                    interaction = self.client.interactions.create(**kwargs)
                    self.previous_interaction_id = interaction.id
                    text = (interaction.output_text or "").strip()
                    if text:
                        callback(f"[Gemini 3.8 Flash Sensei] {text}")
                        return
                except Exception:
                    pass
            callback(f"[Local Heuristic Sensei] {fallback_fn()}")

        threading.Thread(target=_worker, daemon=True).start()


# ============================================================================
# 4. CLASSICAL MAHJONG HAND EVALUATOR & AI HEURISTICS
# ============================================================================
class MahjongRules:
    """Evaluates winning hands (4 Melds + 1 Pair, Seven Pairs, Thirteen Orphans)."""

    @staticmethod
    def can_hu(concealed: list[TileKind], exposed_meld_count: int = 0) -> bool:
        total_tiles = len(concealed) + exposed_meld_count * 3
        if total_tiles != 14:
            return False

        counts = Counter(concealed)

        # 1. Seven Pairs (only when 0 exposed melds)
        if exposed_meld_count == 0 and len(concealed) == 14:
            if sum(v // 2 for v in counts.values()) == 7:
                return True
            # 2. Thirteen Orphans
            orphans = {
                TileKind(Suit.DOTS, 1), TileKind(Suit.DOTS, 9),
                TileKind(Suit.BAMBOO, 1), TileKind(Suit.BAMBOO, 9),
                TileKind(Suit.CHARS, 1), TileKind(Suit.CHARS, 9),
                TileKind(Suit.WINDS, 1), TileKind(Suit.WINDS, 2),
                TileKind(Suit.WINDS, 3), TileKind(Suit.WINDS, 4),
                TileKind(Suit.DRAGONS, 1), TileKind(Suit.DRAGONS, 2),
                TileKind(Suit.DRAGONS, 3),
            }
            if orphans.issubset(counts.keys()) and any(counts[k] >= 2 for k in orphans):
                return True

        # 3. Standard 4 Melds + 1 Pair via recursive backtracking
        needed_melds = 4 - exposed_meld_count
        for pair_tile, cnt in list(counts.items()):
            if cnt >= 2:
                counts[pair_tile] -= 2
                if MahjongRules._can_form_melds(counts, needed_melds):
                    return True
                counts[pair_tile] += 2
        return False

    @staticmethod
    def _can_form_melds(counts: Counter[TileKind], melds_left: int) -> bool:
        if melds_left == 0:
            return all(v == 0 for v in counts.values())

        first: Optional[TileKind] = None
        for k in sorted(counts.keys()):
            if counts[k] > 0:
                first = k
                break
        if first is None:
            return False

        # Try Pung (Triplet)
        if counts[first] >= 3:
            counts[first] -= 3
            if MahjongRules._can_form_melds(counts, melds_left - 1):
                counts[first] += 3
                return True
            counts[first] += 3

        # Try Chow (Sequence) in numbered suits
        if first.suit in (Suit.DOTS, Suit.BAMBOO, Suit.CHARS) and first.value <= 7:
            t2 = TileKind(first.suit, first.value + 1)
            t3 = TileKind(first.suit, first.value + 2)
            if counts[t2] > 0 and counts[t3] > 0:
                counts[first] -= 1
                counts[t2] -= 1
                counts[t3] -= 1
                if MahjongRules._can_form_melds(counts, melds_left - 1):
                    counts[first] += 1
                    counts[t2] += 1
                    counts[t3] += 1
                    return True
                counts[first] += 1
                counts[t2] += 1
                counts[t3] += 1

        return False

    @staticmethod
    def score_tile_keep_value(hand: list[TileKind], tile: TileKind) -> float:
        """Scores how synergistic a tile is within a hand (lower = safer/better to discard)."""
        counts = Counter(hand)
        score = 0.0
        score += (counts[tile] - 1) * 4.0

        if tile.suit in (Suit.DOTS, Suit.BAMBOO, Suit.CHARS):
            score += (5 - abs(5 - tile.value)) * 0.35
            for delta in (-2, -1, 1, 2):
                neighbor = TileKind(tile.suit, tile.value + delta)
                if counts[neighbor] > 0:
                    score += 2.2 if abs(delta) == 1 else 1.1
        else:
            score += 0.2
        return score

    @classmethod
    def best_discard_index(cls, hand: list[TileKind]) -> int:
        best_idx = 0
        lowest_score = float("inf")
        for idx, t in enumerate(hand):
            val = cls.score_tile_keep_value(hand, t)
            if val < lowest_score:
                lowest_score = val
                best_idx = idx
        return best_idx

    @staticmethod
    def find_chow_options(hand: list[TileKind], discard: TileKind) -> list[tuple[TileKind, TileKind]]:
        """Returns valid pairs in `hand` that form a 3-tile sequence with `discard`."""
        if discard.suit not in (Suit.DOTS, Suit.BAMBOO, Suit.CHARS):
            return []
        counts = Counter(hand)
        v = discard.value
        s = discard.suit
        options: list[tuple[TileKind, TileKind]] = []
        for a, b in ((v - 2, v - 1), (v - 1, v + 1), (v + 1, v + 2)):
            if 1 <= a <= 9 and 1 <= b <= 9:
                ta, tb = TileKind(s, a), TileKind(s, b)
                if counts[ta] > 0 and counts[tb] > 0:
                    options.append((ta, tb))
        return options


# ============================================================================
# 5. VECTOR TILE RENDERER (STRICT PALETTE ARTWORK)
# ============================================================================
class VectorTileRenderer:
    """
    Draws isometric 3D Mahjong tiles and traditional motifs using strictly
    Cloud Dancer (#F0EEE9), Warm Beige, and Layered Sandstone hex codes.
    """

    @staticmethod
    def draw_tile(
            canvas: tk.Canvas,
            x: float,
            y: float,
            w: float,
            h: float,
            kind: Optional[TileKind],
            *,
            z_layer: int = 0,
            selected: bool = False,
            highlighted: bool = False,
            dimmed: bool = False,
            face_up: bool = True,
            tag: str = "",
    ) -> None:
        depth = max(4, min(8, int(w * 0.12)))
        tags = (tag, "tile") if tag else ("tile",)

        # 1. Soft Stratified Drop Shadow
        canvas.create_rectangle(
            x + depth + 2,
            y + depth + 3,
            x + w + depth + 2,
            y + h + depth + 3,
            fill=P.SAND_L4_DEEP if selected else P.BEIGE_DEEP,
            outline="",
            tags=tags,
            )

        # 2. 3D Sandstone Extrusion Base (Bottom-Right bevel)
        extrusion_color = P.layer_extrusion(z_layer + 1)
        poly_side = [
            x + w, y,
            x + w + depth, y + depth,
            x + w + depth, y + h + depth,
            x, y + h + depth,
            x, y + h,
            x + w, y + h,
            ]
        canvas.create_polygon(
            poly_side,
            fill=extrusion_color,
            outline=P.SAND_L5_UMBER,
            width=1,
            tags=tags,
        )

        # 3. Tile Face (Cloud Dancer if free/active, Warm Beige if dimmed or face-down)
        if not face_up:
            face_fill = P.SAND_L1_PALE
            border_col = P.SAND_L4_DEEP
        elif selected:
            face_fill = P.CLOUD_CREAM
            border_col = P.SAND_L5_UMBER
        elif highlighted:
            face_fill = P.CLOUD_CREAM
            border_col = P.SAND_L3_WARM
        elif dimmed:
            face_fill = P.BEIGE_MID
            border_col = P.SAND_L2_MID
        else:
            face_fill = P.CLOUD_DANCER
            border_col = P.SAND_L4_DEEP

        canvas.create_rectangle(
            x, y, x + w, y + h,
            fill=face_fill,
            outline=border_col,
            width=2 if (selected or highlighted) else 1,
            tags=tags,
                  )

        # Inner specular frame
        canvas.create_rectangle(
            x + 3, y + 3, x + w - 3, y + h - 3,
            fill="",
            outline=P.CLOUD_CREAM if face_up and not dimmed else P.BEIGE_LIGHT,
            width=1,
            tags=tags,
            )

        if not face_up or kind is None:
            canvas.create_rectangle(
                x + 6, y + 6, x + w - 6, y + h - 6,
                fill=P.BEIGE_DEEP,
                outline=P.SAND_L3_WARM,
                width=1,
                tags=tags,
                )
            return

        # 4. Corner Mini-Index for Instant Readability
        idx_color = P.SAND_L4_DEEP if not dimmed else P.SAND_L2_MID
        canvas.create_text(
            x + 6,
            y + 5,
            text=kind.short_label,
            anchor="nw",
            fill=idx_color,
            font=("Georgia", max(7, int(w * 0.16)), "bold"),
            tags=tags,
            )

        # 5. Suit-Specific Sandstone Vector Artwork
        cx, cy = x + w / 2, y + h / 2 + 3
        if kind.suit == Suit.DOTS:
            VectorTileRenderer._draw_dots(canvas, x, y + 6, w, h - 8, kind.value, dimmed, tags)
        elif kind.suit == Suit.BAMBOO:
            VectorTileRenderer._draw_bamboo(canvas, x, y + 6, w, h - 8, kind.value, dimmed, tags)
        elif kind.suit == Suit.CHARS:
            VectorTileRenderer._draw_chars(canvas, cx, cy, w, kind, dimmed, tags)
        elif kind.suit == Suit.WINDS:
            VectorTileRenderer._draw_wind(canvas, cx, cy, w, kind, dimmed, tags)
        elif kind.suit == Suit.DRAGONS:
            VectorTileRenderer._draw_dragon(canvas, cx, cy, w, h, kind, dimmed, tags)
        elif kind.suit == Suit.FLOWERS:
            VectorTileRenderer._draw_flower(canvas, cx, cy, w, kind, dimmed, tags)

    @staticmethod
    def _draw_dots(
            canvas: tk.Canvas, x: float, y: float, w: float, h: float, val: int, dimmed: bool, tags: tuple[str, ...]
    ) -> None:
        layouts: dict[int, list[tuple[float, float]]] = {
            1: [(0.5, 0.52)],
            2: [(0.5, 0.32), (0.5, 0.72)],
            3: [(0.30, 0.28), (0.5, 0.52), (0.70, 0.76)],
            4: [(0.32, 0.32), (0.68, 0.32), (0.32, 0.72), (0.68, 0.72)],
            5: [(0.30, 0.28), (0.70, 0.28), (0.5, 0.52), (0.30, 0.76), (0.70, 0.76)],
            6: [(0.33, 0.26), (0.67, 0.26), (0.33, 0.54), (0.67, 0.54), (0.33, 0.78), (0.67, 0.78)],
            7: [(0.26, 0.22), (0.50, 0.30), (0.74, 0.38), (0.34, 0.60), (0.66, 0.60), (0.34, 0.80), (0.66, 0.80)],
            8: [
                (0.34, 0.22), (0.66, 0.22),
                (0.34, 0.42), (0.66, 0.42),
                (0.34, 0.62), (0.66, 0.62),
                (0.34, 0.82), (0.66, 0.82),
            ],
            9: [
                (0.27, 0.25), (0.50, 0.25), (0.73, 0.25),
                (0.27, 0.53), (0.50, 0.53), (0.73, 0.53),
                (0.27, 0.80), (0.50, 0.80), (0.73, 0.80),
            ],
        }
        pts = layouts.get(val, layouts[1])
        r = w * (0.22 if val == 1 else (0.11 if val <= 4 else 0.085))
        outer_col = P.SAND_L3_WARM if val in (1, 5) else P.SAND_L4_DEEP
        if dimmed:
            outer_col = P.SAND_L2_MID
        for px, py in pts:
            cx, cy = x + px * w, y + py * h
            canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill=P.BEIGE_DEEP if val == 1 else outer_col,
                outline=P.SAND_L5_UMBER if not dimmed else P.SAND_L2_MID,
                width=1,
                tags=tags,
                )
            ir = r * 0.48
            canvas.create_oval(
                cx - ir, cy - ir, cx + ir, cy + ir,
                fill=P.CLOUD_DANCER,
                outline=outer_col,
                width=1,
                tags=tags,
                )

    @staticmethod
    def _draw_bamboo(
            canvas: tk.Canvas, x: float, y: float, w: float, h: float, val: int, dimmed: bool, tags: tuple[str, ...]
    ) -> None:
        col = P.SAND_L4_DEEP if not dimmed else P.SAND_L2_MID
        accent = P.SAND_L3_WARM if not dimmed else P.SAND_L1_PALE

        if val == 1:
            cx, cy = x + w * 0.5, y + h * 0.54
            r = w * 0.23
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=P.BEIGE_MID, outline=col, width=2, tags=tags)
            canvas.create_polygon(
                cx, cy - r * 0.65,
                    cx + r * 0.55, cy + r * 0.25,
                cx, cy + r * 0.65,
                    cx - r * 0.55, cy + r * 0.25,
                fill=accent, outline=P.SAND_L5_UMBER, width=1, tags=tags
            )
            return

        layouts: dict[int, list[tuple[float, float]]] = {
            2: [(0.5, 0.33), (0.5, 0.72)],
            3: [(0.5, 0.30), (0.33, 0.72), (0.67, 0.72)],
            4: [(0.34, 0.33), (0.66, 0.33), (0.34, 0.72), (0.66, 0.72)],
            5: [(0.28, 0.33), (0.72, 0.33), (0.5, 0.53), (0.28, 0.73), (0.72, 0.73)],
            6: [(0.28, 0.33), (0.5, 0.33), (0.72, 0.33), (0.28, 0.73), (0.5, 0.73), (0.72, 0.73)],
            7: [(0.5, 0.22), (0.28, 0.50), (0.5, 0.50), (0.72, 0.50), (0.28, 0.78), (0.5, 0.78), (0.72, 0.78)],
            8: [
                (0.26, 0.28), (0.42, 0.28), (0.58, 0.28), (0.74, 0.28),
                (0.26, 0.74), (0.42, 0.74), (0.58, 0.74), (0.74, 0.74),
            ],
            9: [
                (0.28, 0.24), (0.5, 0.24), (0.72, 0.24),
                (0.28, 0.52), (0.5, 0.52), (0.72, 0.52),
                (0.28, 0.80), (0.5, 0.80), (0.72, 0.80),
            ],
        }
        stalk_h = h * (0.25 if val <= 6 else 0.19)
        stalk_w = max(3.0, w * 0.075)
        for px, py in layouts.get(val, layouts[2]):
            cx, cy = x + px * w, y + py * h
            canvas.create_rectangle(
                cx - stalk_w / 2,
                cy - stalk_h / 2,
                cx + stalk_w / 2,
                cy + stalk_h / 2,
                fill=accent if (px == 0.5 and val in (5, 7, 9)) else col,
                outline=P.SAND_L5_UMBER if not dimmed else P.SAND_L2_MID,
                tags=tags,
                )
            canvas.create_line(
                cx - stalk_w * 0.8, cy, cx + stalk_w * 0.8, cy,
                fill=P.CLOUD_DANCER, width=1, tags=tags
            )

    @staticmethod
    def _draw_chars(
            canvas: tk.Canvas, cx: float, cy: float, w: float, kind: TileKind, dimmed: bool, tags: tuple[str, ...]
    ) -> None:
        top_col = P.SAND_L5_UMBER if not dimmed else P.SAND_L2_MID
        wan_col = P.SAND_L3_WARM if not dimmed else P.SAND_L2_MID
        canvas.create_text(
            cx, cy - w * 0.18,
            text=kind.hanzi,
            fill=top_col,
            font=("Georgia", max(10, int(w * 0.30)), "bold"),
            tags=tags,
                )
        canvas.create_text(
            cx, cy + w * 0.18,
            text="萬",
            fill=wan_col,
            font=("Georgia", max(10, int(w * 0.30)), "bold"),
            tags=tags,
                )

    @staticmethod
    def _draw_wind(
            canvas: tk.Canvas, cx: float, cy: float, w: float, kind: TileKind, dimmed: bool, tags: tuple[str, ...]
    ) -> None:
        col = P.SAND_L5_UMBER if not dimmed else P.SAND_L2_MID
        canvas.create_text(
            cx, cy + 2,
            text=kind.hanzi,
            fill=col,
            font=("Georgia", max(13, int(w * 0.42)), "bold"),
            tags=tags,
                )

    @staticmethod
    def _draw_dragon(
            canvas: tk.Canvas,
            cx: float,
            cy: float,
            w: float,
            h: float,
            kind: TileKind,
            dimmed: bool,
            tags: tuple[str, ...],
    ) -> None:
        if kind.value == 3:
            rw, rh = w * 0.54, h * 0.48
            canvas.create_rectangle(
                cx - rw / 2, cy - rh / 2, cx + rw / 2, cy + rh / 2,
                fill=P.CLOUD_CREAM,
                outline=P.SAND_L4_DEEP if not dimmed else P.SAND_L2_MID,
                width=2,
                tags=tags,
                )
            canvas.create_rectangle(
                cx - rw / 2 + 4, cy - rh / 2 + 4, cx + rw / 2 - 4, cy + rh / 2 - 4,
                fill="",
                outline=P.SAND_L2_MID,
                width=1,
                tags=tags,
                )
        else:
            col = P.SAND_L3_WARM if kind.value == 1 else P.SAND_L4_DEEP
            if dimmed:
                col = P.SAND_L2_MID
            canvas.create_text(
                cx, cy + 2,
                text=kind.hanzi,
                fill=col,
                font=("Georgia", max(13, int(w * 0.42)), "bold"),
                tags=tags,
                    )

    @staticmethod
    def _draw_flower(
            canvas: tk.Canvas, cx: float, cy: float, w: float, kind: TileKind, dimmed: bool, tags: tuple[str, ...]
    ) -> None:
        r = w * 0.28
        for angle_deg in range(0, 360, 45):
            rad = math.radians(angle_deg)
            px = cx + math.cos(rad) * (r * 0.55)
            py = cy + math.sin(rad) * (r * 0.55)
            pr = r * 0.42
            canvas.create_oval(
                px - pr, py - pr, px + pr, py + pr,
                fill=P.BEIGE_MID,
                outline=P.SAND_L3_WARM if not dimmed else P.SAND_L2_MID,
                tags=tags,
                )
        canvas.create_text(
            cx, cy,
            text=kind.hanzi,
            fill=P.SAND_L5_UMBER if not dimmed else P.SAND_L2_MID,
            font=("Georgia", max(10, int(w * 0.30)), "bold"),
            tags=tags,
        )


# ============================================================================
# 6. MODE A: 3D LAYERED MAHJONG SOLITAIRE ENGINE
# ============================================================================
@dataclass
class SolitaireSlot:
    slot_id: int
    gx: float
    gy: float
    gz: int
    kind: TileKind
    removed: bool = False


class SolitaireEngine:
    """Manages 3D tile coordinates, free-tile occlusion rules, Undo, Shuffle, and Hints."""

    def __init__(self, layout_name: str = "Turtle") -> None:
        self.layout_name = layout_name
        self.slots: list[SolitaireSlot] = []
        self.history: list[tuple[int, int]] = []
        self.score: int = 0
        self.combo: int = 0
        self.last_match_ts: float = 0.0
        self.build_board(layout_name)

    @staticmethod
    def _generate_layout_coords(name: str) -> list[tuple[float, float, int]]:
        coords: list[tuple[float, float, int]] = []
        if name == "Pyramid":
            for x in range(0, 18, 2):
                for y in range(0, 12, 2):
                    coords.append((float(x), float(y), 0))
            for x in range(2, 16, 2):
                for y in range(2, 10, 2):
                    coords.append((float(x), float(y), 1))
            for x in range(4, 14, 2):
                for y in range(2, 10, 2):
                    coords.append((float(x), float(y), 2))
            for x in range(6, 12, 2):
                for y in range(4, 8, 2):
                    coords.append((float(x), float(y), 3))
            coords.append((7.0, 5.0, 4))
            coords.append((9.0, 5.0, 4))
        elif name == "Fortress":
            for x in range(0, 16, 2):
                for y in range(0, 12, 2):
                    if not (6 <= x <= 8 and 4 <= y <= 6):
                        coords.append((float(x), float(y), 0))
            for x in (0, 2, 12, 14):
                for y in (0, 2, 8, 10):
                    coords.append((float(x), float(y), 1))
                    coords.append((float(x), float(y), 2))
            for x in range(4, 12, 2):
                for y in (0, 10):
                    coords.append((float(x), float(y), 1))
            for x in (6, 8):
                for y in (2, 8):
                    coords.append((float(x), float(y), 2))
        else:
            row_widths = {
                0: range(2, 26, 2),
                2: range(6, 22, 2),
                4: range(4, 24, 2),
                6: range(2, 26, 2),
                8: range(2, 26, 2),
                10: range(4, 24, 2),
                12: range(6, 22, 2),
                14: range(2, 26, 2),
            }
            for y, xs in row_widths.items():
                for x in xs:
                    coords.append((float(x), float(y), 0))
            coords.extend([(0.0, 7.0, 0), (26.0, 7.0, 0), (28.0, 7.0, 0)])
            for x in range(8, 20, 2):
                for y in range(2, 14, 2):
                    coords.append((float(x), float(y), 1))
            for x in range(10, 18, 2):
                for y in range(4, 12, 2):
                    coords.append((float(x), float(y), 2))
            for x in range(12, 16, 2):
                for y in range(6, 10, 2):
                    coords.append((float(x), float(y), 3))
            coords.append((13.0, 7.0, 4))

        if len(coords) % 2 == 1:
            coords.pop()
        return coords

    def build_board(self, layout_name: str) -> None:
        self.layout_name = layout_name
        coords = self._generate_layout_coords(layout_name)
        num_pairs = len(coords) // 2

        # Build 68 standard pairs + 4 Flower/Season pairs = 72 pairs (144 tiles)
        full_deck = build_136_wall()
        pair_pool: list[tuple[TileKind, TileKind]] = []
        by_kind: dict[TileKind, list[TileKind]] = {}
        for k in full_deck:
            by_kind.setdefault(k, []).append(k)
        for items in by_kind.values():
            while len(items) >= 2:
                pair_pool.append((items.pop(), items.pop()))

        # Pair Flowers (1-4) and Seasons (5-8) which match each other in Solitaire
        pair_pool.append((TileKind(Suit.FLOWERS, 1), TileKind(Suit.FLOWERS, 2)))
        pair_pool.append((TileKind(Suit.FLOWERS, 3), TileKind(Suit.FLOWERS, 4)))
        pair_pool.append((TileKind(Suit.FLOWERS, 5), TileKind(Suit.FLOWERS, 6)))
        pair_pool.append((TileKind(Suit.FLOWERS, 7), TileKind(Suit.FLOWERS, 8)))

        # Defensive guard if any layout ever exceeds 72 pairs
        while len(pair_pool) < num_pairs:
            extra = random.choice(build_standard_34_kinds())
            pair_pool.append((extra, extra))

        random.shuffle(pair_pool)
        selected_pairs = pair_pool[:num_pairs]

        # Reverse-solvable placement: peel free slots in pairs so board is solvable
        remaining = set(range(len(coords)))
        assigned: dict[int, TileKind] = {}

        def _is_temp_free(idx: int, active_set: set[int]) -> bool:
            gx, gy, gz = coords[idx]
            for o_idx in active_set:
                if o_idx == idx:
                    continue
                ox, oy, oz = coords[o_idx]
                if oz > gz and abs(gx - ox) < 2.0 and abs(gy - oy) < 2.0:
                    return False
            left_b = False
            right_b = False
            for o_idx in active_set:
                if o_idx == idx:
                    continue
                ox, oy, oz = coords[o_idx]
                if oz == gz and abs(gy - oy) < 2.0:
                    if -2.2 <= (ox - gx) < -0.5:
                        left_b = True
                    elif 0.5 < (ox - gx) <= 2.2:
                        right_b = True
            return not (left_b and right_b)

        for t1, t2 in selected_pairs:
            free_candidates = [i for i in remaining if _is_temp_free(i, remaining)]
            if len(free_candidates) >= 2:
                c1, c2 = random.sample(free_candidates, 2)
            else:
                c1, c2 = random.sample(list(remaining), 2)
            assigned[c1] = t1
            assigned[c2] = t2
            remaining.remove(c1)
            remaining.remove(c2)

        self.slots = [
            SolitaireSlot(slot_id=i, gx=coords[i][0], gy=coords[i][1], gz=coords[i][2], kind=assigned[i])
            for i in range(len(coords))
        ]
        self.history.clear()
        self.score = 0
        self.combo = 0

    def is_free(self, slot: SolitaireSlot) -> bool:
        if slot.removed:
            return False
        for other in self.slots:
            if other.removed or other.slot_id == slot.slot_id:
                continue
            if other.gz > slot.gz and abs(slot.gx - other.gx) < 2.0 and abs(slot.gy - other.gy) < 2.0:
                return False

        left_blocked = False
        right_blocked = False
        for other in self.slots:
            if other.removed or other.slot_id == slot.slot_id or other.gz != slot.gz:
                continue
            if abs(slot.gy - other.gy) < 2.0:
                dx = other.gx - slot.gx
                if -2.2 <= dx < -0.5:
                    left_blocked = True
                elif 0.5 < dx <= 2.2:
                    right_blocked = True
        return not (left_blocked and right_blocked)

    def available_moves(self) -> list[tuple[SolitaireSlot, SolitaireSlot]]:
        free_slots = [s for s in self.slots if not s.removed and self.is_free(s)]
        moves: list[tuple[SolitaireSlot, SolitaireSlot]] = []
        for i in range(len(free_slots)):
            for j in range(i + 1, len(free_slots)):
                if free_slots[i].kind.matches_solitaire(free_slots[j].kind):
                    moves.append((free_slots[i], free_slots[j]))
        return moves

    def remove_pair(self, s1: SolitaireSlot, s2: SolitaireSlot) -> None:
        s1.removed = True
        s2.removed = True
        self.history.append((s1.slot_id, s2.slot_id))
        now = time.time()
        if now - self.last_match_ts <= 6.0:
            self.combo += 1
        else:
            self.combo = 1
        self.last_match_ts = now
        self.score += 100 * self.combo

    def undo(self) -> bool:
        if not self.history:
            return False
        id1, id2 = self.history.pop()
        self.slots[id1].removed = False
        self.slots[id2].removed = False
        self.score = max(0, self.score - 50)
        self.combo = 0
        return True

    def shuffle_remaining(self) -> None:
        remaining_slots = [s for s in self.slots if not s.removed]
        kinds = [s.kind for s in remaining_slots]
        random.shuffle(kinds)
        for s, k in zip(remaining_slots, kinds):
            s.kind = k
        self.combo = 0

    def remaining_count(self) -> int:
        return sum(1 for s in self.slots if not s.removed)


# ============================================================================
# 7. MODE B: CLASSICAL 4-PLAYER TABLE MAHJONG ENGINE
# ============================================================================
@dataclass
class Meld:
    meld_type: str  # "PUNG", "CHOW", "KONG"
    tiles: list[TileKind]


@dataclass
class PlayerSeat:
    name: str
    wind_label: str
    hand: list[TileKind] = field(default_factory=list)
    melds: list[Meld] = field(default_factory=list)
    discards: list[TileKind] = field(default_factory=list)
    score: int = 1000

    def sort_hand(self) -> None:
        self.hand.sort()


class TableMahjongEngine:
    """Manages 4-Player Classical Mahjong state, wall draws, claims, and AI decisions."""

    def __init__(self) -> None:
        self.seats: list[PlayerSeat] = [
            PlayerSeat("You (South Seat)", "東 East"),
            PlayerSeat("Sandstone AI (Right)", "南 South"),
            PlayerSeat("Dune AI (Top)", "西 West"),
            PlayerSeat("Ochre AI (Left)", "北 North"),
        ]
        self.wall: list[TileKind] = []
        self.current_turn: int = 0
        self.last_discard: Optional[TileKind] = None
        self.last_discard_from: Optional[int] = None
        self.awaiting_player_discard: bool = False
        self.awaiting_player_claim: bool = False
        self.claim_options: dict[str, object] = {}
        self.round_over: bool = False
        self.status_banner: str = ""
        self.start_new_hand()

    def start_new_hand(self) -> None:
        self.wall = build_136_wall()
        for seat in self.seats:
            seat.hand = [self.wall.pop() for _ in range(13)]
            seat.melds.clear()
            seat.discards.clear()
            seat.sort_hand()
        self.current_turn = 0
        self.last_discard = None
        self.last_discard_from = None
        self.round_over = False
        self.awaiting_player_claim = False
        self.claim_options.clear()
        self.draw_for_seat(0)

    def draw_for_seat(self, seat_idx: int) -> Optional[TileKind]:
        if not self.wall:
            self.round_over = True
            self.status_banner = "Wall Exhausted — Draw Hand (荒牌流局)"
            return None
        tile = self.wall.pop()
        self.seats[seat_idx].hand.append(tile)
        if seat_idx == 0:
            self.awaiting_player_discard = True
            if MahjongRules.can_hu(self.seats[0].hand, len(self.seats[0].melds)):
                self.status_banner = f"Drew {tile.display_name} — Winning Hand Ready! Click 'Declare Hu'!"
            else:
                self.status_banner = f"Drew {tile.display_name}. Click any tile in your hand to discard."
        return tile


# ============================================================================
# 8. UNIFIED ARCHITECTURAL UI APPLICATION
# ============================================================================
class SandstoneMahjongApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Mahjong — Cloud Dancer & Layered Sandstone Edition")
        self.root.geometry("1240x820")
        self.root.minsize(1060, 740)
        self.root.configure(bg=P.BEIGE_LIGHT)

        self.mode: str = "TABLE"  # "TABLE" or "SOLITAIRE"
        self.sensei = GeminiMahjongSensei()
        self.solitaire = SolitaireEngine("Turtle")
        self.table = TableMahjongEngine()

        self.selected_solitaire_slot: Optional[int] = None
        self.hint_pair_ids: tuple[Optional[int], Optional[int]] = (None, None)
        self.selected_hand_idx: Optional[int] = None
        self.sensei_message: str = (
            "Sensei Ready — Click 'Ask Sensei' for tactical analysis "
            f"({'Gemini 3.8 Flash Active' if self.sensei.online else 'Local Heuristic Mode'})."
        )

        self.canvas = tk.Canvas(
            self.root,
            bg=P.BEIGE_LIGHT,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.render())

        self.root.bind("<Key-h>", lambda _e: self.on_ask_sensei())
        self.root.bind("<Key-z>", lambda _e: self.on_solitaire_undo())

        self.render()

    def draw_button(
            self,
            x: float,
            y: float,
            w: float,
            h: float,
            label: str,
            callback: Callable[[], None],
            *,
            active: bool = False,
            primary: bool = False,
            tag_suffix: str = "",
    ) -> None:
        btn_tag = f"btn_{label}_{tag_suffix}".replace(" ", "_")
        if primary:
            bg = P.SAND_L4_DEEP
            fg = P.CLOUD_DANCER
            border = P.SAND_L5_UMBER
        elif active:
            bg = P.CLOUD_DANCER
            fg = P.SAND_L5_UMBER
            border = P.SAND_L4_DEEP
        else:
            bg = P.BEIGE_MID
            fg = P.SAND_L5_UMBER
            border = P.SAND_L2_MID

        self.canvas.create_rectangle(
            x + 2, y + 2, x + w + 2, y + h + 2,
            fill=P.BEIGE_DEEP, outline="", tags=(btn_tag,)
        )
        rect_id = self.canvas.create_rectangle(
            x, y, x + w, y + h,
            fill=bg, outline=border, width=2 if (active or primary) else 1, tags=(btn_tag,)
        )
        self.canvas.create_text(
            x + w / 2, y + h / 2,
            text=label,
            fill=fg,
            font=("Georgia", 10, "bold"),
            tags=(btn_tag,),
            )

        def _on_enter(_e: tk.Event) -> None:
            self.canvas.itemconfig(rect_id, fill=P.SAND_L3_WARM if primary else P.CLOUD_CREAM)

        def _on_leave(_e: tk.Event) -> None:
            self.canvas.itemconfig(rect_id, fill=bg)

        self.canvas.tag_bind(btn_tag, "<Enter>", _on_enter)
        self.canvas.tag_bind(btn_tag, "<Leave>", _on_leave)
        self.canvas.tag_bind(btn_tag, "<Button-1>", lambda _e: callback())

    def draw_chrome(self, width: int, height: int) -> None:
        self.canvas.create_rectangle(0, 0, width, 62, fill=P.SAND_L5_UMBER, outline="")
        self.canvas.create_line(0, 62, width, 62, fill=P.SAND_L2_MID, width=2)

        self.canvas.create_text(
            24, 22,
            text="雲舞麻雀  •  CLOUD DANCER MAHJONG",
            anchor="w",
            fill=P.CLOUD_DANCER,
            font=("Georgia", 15, "bold"),
        )
        self.canvas.create_text(
            24, 44,
            text="PANTONE 11-4201 CLOUD DANCER  |  LAYERED SANDSTONES  |  WARM BEIGE",
            anchor="w",
            fill=P.SAND_L1_PALE,
            font=("Georgia", 8, "bold"),
        )

        self.draw_button(
            width - 490, 14, 225, 34,
            "4-Player Table Mahjong",
            lambda: self.switch_mode("TABLE"),
            active=(self.mode == "TABLE"),
            tag_suffix="mode_table",
            )
        self.draw_button(
            width - 250, 14, 225, 34,
            "3D Mahjong Solitaire",
            lambda: self.switch_mode("SOLITAIRE"),
            active=(self.mode == "SOLITAIRE"),
            tag_suffix="mode_sol",
            )

        bar_y = height - 48
        self.canvas.create_rectangle(0, bar_y, width, height, fill=P.BEIGE_MID, outline=P.SAND_L2_MID, width=1)
        self.canvas.create_rectangle(
            18, bar_y + 9, 128, bar_y + 39,
            fill=P.SAND_L4_DEEP, outline=P.SAND_L5_UMBER
        )
        self.canvas.create_text(
            73, bar_y + 24,
            text="SENSEI INSIGHT",
            fill=P.CLOUD_DANCER,
            font=("Georgia", 8, "bold"),
                )
        self.canvas.create_text(
            144, bar_y + 24,
            text=self.sensei_message,
            anchor="w",
            fill=P.SAND_L5_UMBER,
            font=("Georgia", 10, "italic"),
                 )

    def switch_mode(self, new_mode: str) -> None:
        self.mode = new_mode
        self.render()

    def render(self) -> None:
        self.canvas.delete("all")
        w = max(self.canvas.winfo_width(), 1060)
        h = max(self.canvas.winfo_height(), 740)

        self.canvas.create_rectangle(14, 74, w - 14, h - 60, fill=P.BEIGE_LIGHT, outline=P.SAND_L2_MID, width=1)
        self.draw_chrome(w, h)

        if self.mode == "TABLE":
            self.render_table_mode(w, h)
        else:
            self.render_solitaire_mode(w, h)

    def render_table_mode(self, w: int, h: int) -> None:
        t = self.table

        self.canvas.create_rectangle(14, 64, w - 14, 110, fill=P.BEIGE_MID, outline=P.SAND_L2_MID)
        self.canvas.create_text(
            30, 87,
            text=f"Wall Remaining: {len(t.wall)} tiles   |   Player Score: {t.seats[0].score} pts",
            anchor="w",
            fill=P.SAND_L5_UMBER,
            font=("Georgia", 11, "bold"),
        )
        self.canvas.create_text(
            w / 2, 87,
            text=t.status_banner,
            fill=P.SAND_L4_DEEP,
            font=("Georgia", 11, "bold"),
            )

        self.draw_button(w - 295, 71, 130, 30, "Ask Sensei (H)", self.on_ask_sensei, primary=True, tag_suffix="t_s")
        self.draw_button(w - 155, 71, 125, 30, "New Hand", self.on_new_table_hand, tag_suffix="t_new")

        cx, cy = w / 2, (h + 50) / 2 - 20
        mat_w, mat_h = 460, 290
        self.canvas.create_rectangle(
            cx - mat_w / 2, cy - mat_h / 2, cx + mat_w / 2, cy + mat_h / 2,
            fill=P.BEIGE_DEEP, outline=P.SAND_L3_WARM, width=2
        )
        self.canvas.create_rectangle(
            cx - 56, cy - 36, cx + 56, cy + 36,
            fill=P.SAND_L5_UMBER, outline=P.SAND_L1_PALE, width=2
        )
        self.canvas.create_text(
            cx, cy - 10,
            text="東場 • EAST",
            fill=P.CLOUD_DANCER,
            font=("Georgia", 10, "bold"),
                )
        self.canvas.create_text(
            cx, cy + 12,
            text=f"{len(t.wall)} WALL",
            fill=P.BEIGE_MID,
            font=("Georgia", 9, "bold"),
                )

        self._draw_ai_seat_top(cx, 124, t.seats[2], is_turn=(t.current_turn == 2))
        self._draw_ai_seat_side(48, cy, t.seats[3], is_left=True, is_turn=(t.current_turn == 3))
        self._draw_ai_seat_side(w - 92, cy, t.seats[1], is_left=False, is_turn=(t.current_turn == 1))

        self._draw_discard_river(cx - 175, cy + 52, t.seats[0].discards, cols=9)
        self._draw_discard_river(cx - 175, cy - 125, t.seats[2].discards, cols=9)
        self._draw_discard_river(cx - 215, cy - 42, t.seats[3].discards, cols=4)
        self._draw_discard_river(cx + 75, cy - 42, t.seats[1].discards, cols=4)

        hand_y = h - 148
        player = t.seats[0]

        meld_x = 40.0
        for meld in player.melds:
            self.canvas.create_text(
                meld_x, hand_y - 18,
                text=meld.meld_type,
                anchor="w",
                fill=P.SAND_L4_DEEP,
                font=("Georgia", 8, "bold"),
                        )
            for mt in meld.tiles:
                VectorTileRenderer.draw_tile(self.canvas, meld_x, hand_y, 42, 58, mt, z_layer=1)
                meld_x += 46
            meld_x += 16

        tile_w, tile_h = 52.0, 72.0
        gap = 6.0
        total_hand_w = len(player.hand) * (tile_w + gap)
        start_x = max(meld_x + 20, (w - total_hand_w) / 2)

        for idx, tile_kind in enumerate(player.hand):
            tx = start_x + idx * (tile_w + gap) + (14 if idx == len(player.hand) - 1 and len(player.hand) % 3 == 2 else 0)
            is_sel = (self.selected_hand_idx == idx)
            ty = hand_y - (10 if is_sel else 0)
            tag = f"phand_{idx}"
            VectorTileRenderer.draw_tile(
                self.canvas,
                tx, ty, tile_w, tile_h,
                tile_kind,
                z_layer=2 if is_sel else 1,
                selected=is_sel,
                tag=tag,
            )
            self.canvas.tag_bind(tag, "<Button-1>", lambda _e, i=idx: self.on_player_hand_click(i))
            self.canvas.tag_bind(tag, "<Enter>", lambda _e, i=idx: self._hover_hand(i))

        self._draw_table_action_bar(cx, hand_y - 52)

    def _draw_ai_seat_top(self, cx: float, y: float, seat: PlayerSeat, is_turn: bool) -> None:
        badge_fill = P.SAND_L4_DEEP if is_turn else P.BEIGE_DEEP
        badge_fg = P.CLOUD_DANCER if is_turn else P.SAND_L5_UMBER
        self.canvas.create_rectangle(cx - 140, y, cx + 140, y + 24, fill=badge_fill, outline=P.SAND_L4_DEEP)
        self.canvas.create_text(
            cx, y + 12,
            text=f"{seat.name}  •  {seat.wind_label} ({len(seat.hand)} tiles)",
            fill=badge_fg,
            font=("Georgia", 9, "bold"),
                )
        tw, th = 28, 38
        start_x = cx - (len(seat.hand) * 31) / 2
        for i in range(len(seat.hand)):
            VectorTileRenderer.draw_tile(
                self.canvas, start_x + i * 31, y + 30, tw, th, None, face_up=False, z_layer=0
            )
        mx = start_x + len(seat.hand) * 31 + 18
        for meld in seat.melds:
            for mt in meld.tiles:
                VectorTileRenderer.draw_tile(self.canvas, mx, y + 30, tw, th, mt, face_up=True, z_layer=0)
                mx += 30
            mx += 8

    def _draw_ai_seat_side(self, x: float, cy: float, seat: PlayerSeat, is_left: bool, is_turn: bool) -> None:
        badge_fill = P.SAND_L4_DEEP if is_turn else P.BEIGE_DEEP
        badge_fg = P.CLOUD_DANCER if is_turn else P.SAND_L5_UMBER
        bx = x + (20 if is_left else -20)
        self.canvas.create_rectangle(bx - 68, cy - 195, bx + 68, cy - 171, fill=badge_fill, outline=P.SAND_L4_DEEP)
        self.canvas.create_text(
            bx, cy - 183,
            text=f"{seat.wind_label} AI",
            fill=badge_fg,
            font=("Georgia", 9, "bold"),
                )
        tw, th = 30, 24
        start_y = cy - 155
        for i in range(min(13, len(seat.hand))):
            VectorTileRenderer.draw_tile(
                self.canvas, x, start_y + i * 24, tw, th, None, face_up=False, z_layer=0
            )

    def _draw_discard_river(self, x: float, y: float, discards: list[TileKind], cols: int) -> None:
        tw, th = 32, 44
        for idx, d_kind in enumerate(discards[-18:]):
            r = idx // cols
            c = idx % cols
            VectorTileRenderer.draw_tile(
                self.canvas,
                x + c * (tw + 5),
                y + r * (th + 6),
                tw, th,
                d_kind,
                z_layer=0,
                )

    def _draw_table_action_bar(self, cx: float, y: float) -> None:
        t = self.table
        if t.round_over:
            self.draw_button(cx - 90, y, 180, 36, "Deal Next Round", self.on_new_table_hand, primary=True, tag_suffix="nr")
            return

        if t.awaiting_player_discard:
            btns: list[tuple[str, Callable[[], None]]] = []
            if MahjongRules.can_hu(t.seats[0].hand, len(t.seats[0].melds)):
                btns.append(("Declare Hu (Win!)", self.on_declare_tsumo))
            counts = Counter(t.seats[0].hand)
            for k, cnt in counts.items():
                if cnt == 4:
                    btns.append((f"Declare Kong ({k.short_label})", lambda kind=k: self.on_declare_concealed_kong(kind)))
            if btns:
                total_w = len(btns) * 175
                sx = cx - total_w / 2
                for idx, (lbl, fn) in enumerate(btns):
                    self.draw_button(sx + idx * 180, y, 170, 36, lbl, fn, primary=True, tag_suffix=f"self_{idx}")

        elif t.awaiting_player_claim and t.last_discard is not None:
            btns_claim: list[tuple[str, Callable[[], None], bool]] = []
            if t.claim_options.get("hu"):
                btns_claim.append((f"Hu / Win on {t.last_discard.short_label}!", self.on_claim_hu, True))
            if t.claim_options.get("pung"):
                btns_claim.append((f"Pung ({t.last_discard.short_label})", self.on_claim_pung, True))
            chow_list: list[tuple[TileKind, TileKind]] = t.claim_options.get("chow", [])  # type: ignore[assignment]
            for idx, pair in enumerate(chow_list):
                lbl = f"Chow ({pair[0].short_label}+{pair[1].short_label})"
                btns_claim.append((lbl, lambda p=pair: self.on_claim_chow(p), True))
            btns_claim.append(("Pass", self.on_claim_pass, False))

            total_w = len(btns_claim) * 165
            sx = cx - total_w / 2
            for idx, (lbl, fn, is_prim) in enumerate(btns_claim):
                self.draw_button(sx + idx * 170, y, 160, 36, lbl, fn, primary=is_prim, tag_suffix=f"clm_{idx}")

    def _hover_hand(self, idx: int) -> None:
        if self.selected_hand_idx != idx:
            self.selected_hand_idx = idx
            self.render()

    def on_player_hand_click(self, idx: int) -> None:
        t = self.table
        if not t.awaiting_player_discard or t.round_over:
            return
        if idx < 0 or idx >= len(t.seats[0].hand):
            return

        discarded = t.seats[0].hand.pop(idx)
        t.seats[0].sort_hand()
        t.seats[0].discards.append(discarded)
        t.last_discard = discarded
        t.last_discard_from = 0
        t.awaiting_player_discard = False
        self.selected_hand_idx = None
        t.status_banner = f"You discarded {discarded.display_name}."
        self.render()

        self.root.after(420, lambda: self.process_after_discard(0, discarded))

    def process_after_discard(self, discarder: int, discarded: TileKind) -> None:
        t = self.table
        if t.round_over:
            return

        for step in range(1, 4):
            seat_idx = (discarder + step) % 4
            if seat_idx == 0:
                continue
            ai = t.seats[seat_idx]
            if MahjongRules.can_hu(ai.hand + [discarded], len(ai.melds)):
                ai.hand.append(discarded)
                ai.sort_hand()
                ai.score += 250
                t.seats[discarder].score -= 250
                t.round_over = True
                t.status_banner = f"{ai.name} declares HU (Wins) on {discarded.display_name}!"
                self.render()
                return

        if discarder != 0:
            p_hand = t.seats[0].hand
            can_hu = MahjongRules.can_hu(p_hand + [discarded], len(t.seats[0].melds))
            can_pung = Counter(p_hand)[discarded] >= 2
            chow_opts = MahjongRules.find_chow_options(p_hand, discarded) if discarder == 3 else []

            if can_hu or can_pung or chow_opts:
                t.awaiting_player_claim = True
                t.claim_options = {"hu": can_hu, "pung": can_pung, "chow": chow_opts}
                t.status_banner = f"{t.seats[discarder].name} discarded {discarded.display_name} — Claim or Pass?"
                self.render()
                return

        for step in range(1, 4):
            seat_idx = (discarder + step) % 4
            if seat_idx == 0:
                continue
            ai = t.seats[seat_idx]
            if Counter(ai.hand)[discarded] >= 2:
                for _ in range(2):
                    ai.hand.remove(discarded)
                ai.melds.append(Meld("PUNG", [discarded, discarded, discarded]))
                t.seats[discarder].discards.pop()
                t.current_turn = seat_idx
                t.status_banner = f"{ai.name} claims PUNG on {discarded.display_name}!"
                self.render()
                self.root.after(550, lambda s=seat_idx: self.ai_discard_step(s))
                return

        next_seat = (discarder + 1) % 4
        t.current_turn = next_seat
        if next_seat == 0:
            t.draw_for_seat(0)
            self.render()
        else:
            self.root.after(420, lambda: self.ai_turn_step(next_seat))

    def ai_turn_step(self, seat_idx: int) -> None:
        t = self.table
        if t.round_over:
            return
        ai = t.seats[seat_idx]
        drawn = t.draw_for_seat(seat_idx)
        if drawn is None:
            self.render()
            return

        if MahjongRules.can_hu(ai.hand, len(ai.melds)):
            ai.score += 300
            for i, s in enumerate(t.seats):
                if i != seat_idx:
                    s.score -= 100
            t.round_over = True
            t.status_banner = f"{ai.name} wins by Self-Draw (Tsumo) with {drawn.display_name}!"
            self.render()
            return

        self.ai_discard_step(seat_idx)

    def ai_discard_step(self, seat_idx: int) -> None:
        t = self.table
        ai = t.seats[seat_idx]
        discard_idx = MahjongRules.best_discard_index(ai.hand)
        discarded = ai.hand.pop(discard_idx)
        ai.sort_hand()
        ai.discards.append(discarded)
        t.last_discard = discarded
        t.last_discard_from = seat_idx
        t.status_banner = f"{ai.name} discarded {discarded.display_name}."
        self.render()
        self.root.after(420, lambda: self.process_after_discard(seat_idx, discarded))

    def on_declare_tsumo(self) -> None:
        t = self.table
        t.seats[0].score += 450
        for s in t.seats[1:]:
            s.score -= 150
        t.round_over = True
        t.awaiting_player_discard = False
        t.status_banner = "VICTORY! You declared Self-Draw Hu (自摸)! +450 pts"
        self.render()

    def on_declare_concealed_kong(self, kind: TileKind) -> None:
        t = self.table
        p = t.seats[0]
        for _ in range(4):
            p.hand.remove(kind)
        p.melds.append(Meld("KONG", [kind, kind, kind, kind]))
        t.draw_for_seat(0)
        self.render()

    def on_claim_hu(self) -> None:
        t = self.table
        if t.last_discard is None or t.last_discard_from is None:
            return
        t.seats[0].hand.append(t.last_discard)
        t.seats[0].sort_hand()
        t.seats[0].score += 350
        t.seats[t.last_discard_from].score -= 350
        t.awaiting_player_claim = False
        t.round_over = True
        t.status_banner = f"VICTORY! You claimed {t.last_discard.display_name} for Hu (榮和)! +350 pts"
        self.render()

    def on_claim_pung(self) -> None:
        t = self.table
        if t.last_discard is None or t.last_discard_from is None:
            return
        d = t.last_discard
        p = t.seats[0]
        for _ in range(2):
            p.hand.remove(d)
        p.melds.append(Meld("PUNG", [d, d, d]))
        t.seats[t.last_discard_from].discards.pop()
        t.awaiting_player_claim = False
        t.current_turn = 0
        t.awaiting_player_discard = True
        t.status_banner = f"Formed PUNG of {d.display_name}. Select a tile from your hand to discard."
        self.render()

    def on_claim_chow(self, pair: tuple[TileKind, TileKind]) -> None:
        t = self.table
        if t.last_discard is None or t.last_discard_from is None:
            return
        d = t.last_discard
        p = t.seats[0]
        p.hand.remove(pair[0])
        p.hand.remove(pair[1])
        meld_tiles = sorted([pair[0], pair[1], d])
        p.melds.append(Meld("CHOW", meld_tiles))
        t.seats[t.last_discard_from].discards.pop()
        t.awaiting_player_claim = False
        t.current_turn = 0
        t.awaiting_player_discard = True
        t.status_banner = f"Formed CHOW ({' '.join(k.short_label for k in meld_tiles)}). Select a tile to discard."
        self.render()

    def on_claim_pass(self) -> None:
        t = self.table
        t.awaiting_player_claim = False
        discarder = t.last_discard_from or 0
        next_seat = (discarder + 1) % 4
        t.current_turn = next_seat
        self.render()
        if next_seat == 0:
            t.draw_for_seat(0)
            self.render()
        else:
            self.root.after(300, lambda: self.ai_turn_step(next_seat))

    def on_new_table_hand(self) -> None:
        self.table.start_new_hand()
        self.render()

    def render_solitaire_mode(self, w: int, h: int) -> None:
        s = self.solitaire
        moves = s.available_moves()
        rem = s.remaining_count()

        self.canvas.create_rectangle(14, 64, w - 14, 112, fill=P.BEIGE_MID, outline=P.SAND_L2_MID)
        status_txt = (
            f"Layout: {s.layout_name}   |   Tiles Left: {rem}   |   "
            f"Open Pairs: {len(moves)}   |   Score: {s.score} (Combo x{max(1, s.combo)})"
        )
        self.canvas.create_text(28, 88, text=status_txt, anchor="w", fill=P.SAND_L5_UMBER, font=("Georgia", 11, "bold"))

        for idx, lname in enumerate(("Turtle", "Pyramid", "Fortress")):
            self.draw_button(
                w - 690 + idx * 95, 72, 88, 30,
                lname,
                lambda n=lname: self.on_change_solitaire_layout(n),
                active=(s.layout_name == lname),
                tag_suffix=f"lay_{lname}",
                )
        self.draw_button(w - 390, 72, 82, 30, "Undo (Z)", self.on_solitaire_undo, tag_suffix="s_undo")
        self.draw_button(w - 300, 72, 85, 30, "Shuffle", self.on_solitaire_shuffle, tag_suffix="s_shuf")
        self.draw_button(w - 207, 72, 90, 30, "Hint Pair", self.on_solitaire_hint, tag_suffix="s_hint")
        self.draw_button(w - 109, 72, 85, 30, "Sensei", self.on_ask_sensei, primary=True, tag_suffix="s_sen")

        if rem == 0:
            self.canvas.create_text(
                w / 2, h / 2,
                text="BOARD CLEARED! ARCHITECTURAL HARMONY ACHIEVED",
                fill=P.SAND_L5_UMBER,
                font=("Georgia", 20, "bold"),
                )
            return

        active_slots = [slot for slot in s.slots if not slot.removed]
        min_gx = min(sl.gx for sl in active_slots)
        max_gx = max(sl.gx for sl in active_slots) + 2.0
        min_gy = min(sl.gy for sl in active_slots)
        max_gy = max(sl.gy for sl in active_slots) + 2.0

        board_avail_w = w - 120
        board_avail_h = h - 220
        half_w = min(board_avail_w / max(max_gx - min_gx, 1.0), 30.0)
        half_h = min(board_avail_h / max(max_gy - min_gy, 1.0), 40.0)
        half_w = min(half_w, half_h * 0.74)
        half_h = half_w / 0.74

        tile_w = half_w * 2.0
        tile_h = half_h * 2.0
        origin_x = (w - (max_gx - min_gx) * half_w) / 2 - min_gx * half_w
        origin_y = 128 + (board_avail_h - (max_gy - min_gy) * half_h) / 2 - min_gy * half_h

        ordered = sorted(active_slots, key=lambda sl: (sl.gz, sl.gy, sl.gx))
        for sl in ordered:
            free = s.is_free(sl)
            tx = origin_x + sl.gx * half_w - sl.gz * 5
            ty = origin_y + sl.gy * half_h - sl.gz * 6
            is_sel = (self.selected_solitaire_slot == sl.slot_id)
            is_hint = (sl.slot_id in self.hint_pair_ids)
            tag = f"sol_{sl.slot_id}"
            VectorTileRenderer.draw_tile(
                self.canvas,
                tx, ty, tile_w, tile_h,
                sl.kind,
                z_layer=sl.gz,
                selected=is_sel,
                highlighted=is_hint,
                dimmed=not free,
                tag=tag,
            )
            self.canvas.tag_bind(tag, "<Button-1>", lambda _e, sid=sl.slot_id: self.on_solitaire_click(sid))

    def on_solitaire_click(self, slot_id: int) -> None:
        s = self.solitaire
        clicked = s.slots[slot_id]
        if not s.is_free(clicked):
            self.sensei_message = (
                f"{clicked.kind.display_name} (Layer {clicked.gz + 1}) is locked by adjacent or upper sandstone tiles."
            )
            self.render()
            return

        self.hint_pair_ids = (None, None)
        if self.selected_solitaire_slot is None or self.selected_solitaire_slot == slot_id:
            self.selected_solitaire_slot = None if self.selected_solitaire_slot == slot_id else slot_id
            self.render()
            return

        prev = s.slots[self.selected_solitaire_slot]
        if prev.kind.matches_solitaire(clicked.kind):
            s.remove_pair(prev, clicked)
            self.selected_solitaire_slot = None
            self.sensei_message = f"Matched {clicked.kind.display_name}! (+{100 * s.combo} pts)"
        else:
            self.selected_solitaire_slot = slot_id
        self.render()

    def on_change_solitaire_layout(self, name: str) -> None:
        self.selected_solitaire_slot = None
        self.hint_pair_ids = (None, None)
        self.solitaire.build_board(name)
        self.render()

    def on_solitaire_undo(self) -> None:
        if self.mode == "SOLITAIRE" and self.solitaire.undo():
            self.selected_solitaire_slot = None
            self.hint_pair_ids = (None, None)
            self.render()

    def on_solitaire_shuffle(self) -> None:
        self.selected_solitaire_slot = None
        self.hint_pair_ids = (None, None)
        self.solitaire.shuffle_remaining()
        self.render()

    def on_solitaire_hint(self) -> None:
        moves = self.solitaire.available_moves()
        if not moves:
            self.sensei_message = "No open pairs remain! Click 'Shuffle' to rearrange the remaining sandstone tiles."
            self.hint_pair_ids = (None, None)
        else:
            moves.sort(key=lambda pair: pair[0].gz + pair[1].gz, reverse=True)
            best = moves[0]
            self.hint_pair_ids = (best[0].slot_id, best[1].slot_id)
            self.sensei_message = (
                f"Hint: Match {best[0].kind.display_name} on layers {best[0].gz + 1} & {best[1].gz + 1}."
            )
        self.render()

    def on_ask_sensei(self) -> None:
        self.sensei_message = "Sensei is contemplating the board state..."
        self.render()

        if self.mode == "TABLE":
            hand = self.table.seats[0].hand
            melds = [f"{m.meld_type}({m.tiles[0].short_label})" for m in self.table.seats[0].melds]
            hand_str = ", ".join(k.display_name for k in hand)
            prompt = (
                f"Mode: 4-Player Classical Mahjong. Player concealed hand: [{hand_str}]. "
                f"Exposed melds: {melds}. Recommend the single best tile to discard and why."
            )

            def _fallback() -> str:
                idx = MahjongRules.best_discard_index(hand)
                target = hand[idx]
                return (
                    f"Discard {target.display_name} ({target.short_label}) — it has the lowest sequence/pair "
                    "synergy in your current hand structure."
                )

            self.sensei.ask_sensei_async(prompt, _fallback, self._update_sensei_banner)
        else:
            moves = self.solitaire.available_moves()
            moves_desc = ", ".join(
                f"{a.kind.display_name} (layers {a.gz + 1}+{b.gz + 1})" for a, b in moves[:6]
            )
            prompt = (
                f"Mode: 3D Mahjong Solitaire ({self.solitaire.layout_name}). "
                f"Open matchable pairs: [{moves_desc or 'None'}]. Which pair should be cleared first?"
            )

            def _fallback_sol() -> str:
                if not moves:
                    return "No open pairs remain — use Shuffle to unlock buried layers."
                moves.sort(key=lambda p: p[0].gz + p[1].gz, reverse=True)
                top_a, top_b = moves[0]
                self.hint_pair_ids = (top_a.slot_id, top_b.slot_id)
                return (
                    f"Prioritize matching {top_a.kind.display_name} at elevation layers "
                    f"{top_a.gz + 1} & {top_b.gz + 1} to uncover the most buried tiles underneath."
                )

            self.sensei.ask_sensei_async(prompt, _fallback_sol, self._update_sensei_banner)

    def _update_sensei_banner(self, text: str) -> None:
        def _apply() -> None:
            self.sensei_message = text
            self.render()

        self.root.after(0, _apply)


def main() -> None:
    root = tk.Tk()
    SandstoneMahjongApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()