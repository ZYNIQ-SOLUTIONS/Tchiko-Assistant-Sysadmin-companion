"""Visual Learning & Experiences dashboard for Tchiko Desktop GTK3 (`tchiko/experiences_view.py`).

Displays:
- Learning Curve visualization (`LearningCurveChart`, rendered via PyCairo) plotting
  cumulative learned Python Experience tools alongside rolling execution success rate.
- Live KPI strip (Total Tools, Hardened/Verified, Success Rate RingGauge, Self-Recoveries).
- Searchable, maturity-filterable Experience library with master-detail Python code inspector,
  dry-run / run / approve / toggle / rollback / delete controls, and evolution/run history.
"""

from __future__ import annotations

from datetime import datetime
import html
import math
import threading
from typing import Any, Callable, Dict, List, Optional

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from . import ui_theme as ui
from .agent_engine import TchikoAgentEngine
from .experiences import (
    Experience,
    MATURITY_DRAFT,
    MATURITY_HARDENED,
    MATURITY_NEEDS_REPAIR,
    MATURITY_VERIFIED,
)


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0


def _maturity_css(maturity: str) -> str:
    return {
        MATURITY_HARDENED: "hardened",
        MATURITY_VERIFIED: "verified",
        MATURITY_DRAFT: "draft",
        MATURITY_NEEDS_REPAIR: "repair",
    }.get(maturity, "draft")


class LearningCurveChart(Gtk.DrawingArea):
    """PyCairo dual-metric learning curve: cumulative Experiences (crimson) + success rate (emerald)."""

    def __init__(self) -> None:
        super().__init__()
        self._points: List[Dict[str, Any]] = []
        self._by_maturity: Dict[str, int] = {}
        self.set_size_request(-1, 152)
        self.connect("draw", self._on_draw)

    def set_metrics(self, metrics: Dict[str, Any]) -> None:
        self._points = list(metrics.get("curve_points") or [])
        self._by_maturity = dict(metrics.get("by_maturity") or {})
        self.queue_draw()

    def _on_draw(self, _widget: Gtk.Widget, cr: cairo.Context) -> bool:
        alloc = self.get_allocation()
        w = max(120, alloc.width)
        h = max(100, alloc.height)

        # Background fill
        r, g, b = _hex_to_rgb(ui.SURFACE)
        cr.set_source_rgb(r, g, b)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        pad_l, pad_r, pad_t, pad_b = 38.0, 44.0, 26.0, 26.0
        plot_w = max(40.0, w - pad_l - pad_r)
        plot_h = max(30.0, h - pad_t - pad_b)

        # Legend in top header strip
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(10.0)
        br, bg, bb = _hex_to_rgb(ui.TEXT_MUTED)
        cr.set_source_rgb(br, bg, bb)
        cr.move_to(pad_l, 15.0)
        cr.show_text("LEARNING CURVE")

        # Legend dots
        ar, ag, ab = _hex_to_rgb(ui.ACCENT)
        sr, sg, sb = _hex_to_rgb(ui.SUCCESS)
        lx = w - pad_r - 220.0
        if lx > pad_l + 110.0:
            cr.set_source_rgb(ar, ag, ab)
            cr.arc(lx, 11.5, 3.5, 0, math.tau)
            cr.fill()
            cr.set_source_rgb(*_hex_to_rgb(ui.TEXT_SECONDARY))
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(9.5)
            cr.move_to(lx + 8.0, 14.5)
            cr.show_text("Learned Tools")

            lx2 = lx + 106.0
            cr.set_source_rgb(sr, sg, sb)
            cr.arc(lx2, 11.5, 3.5, 0, math.tau)
            cr.fill()
            cr.set_source_rgb(*_hex_to_rgb(ui.TEXT_SECONDARY))
            cr.move_to(lx2 + 8.0, 14.5)
            cr.show_text("Success Rate %")

        # Horizontal gridlines (0%, 50%, 100%)
        gr, gg, gb = _hex_to_rgb(ui.BORDER)
        cr.set_line_width(1.0)
        cr.set_font_size(8.5)
        for frac in (0.0, 0.5, 1.0):
            y = pad_t + plot_h * (1.0 - frac)
            cr.set_source_rgba(gr, gg, gb, 0.75)
            cr.move_to(pad_l, y)
            cr.line_to(pad_l + plot_w, y)
            cr.stroke()
            # Right axis: success %
            cr.set_source_rgba(sr, sg, sb, 0.72)
            cr.move_to(pad_l + plot_w + 6.0, y + 3.0)
            cr.show_text(f"{int(frac * 100)}%")

        pts = self._points
        if len(pts) < 2:
            cr.set_source_rgb(*_hex_to_rgb(ui.TEXT_MUTED))
            cr.set_font_size(10.5)
            cr.move_to(pad_l + 12.0, pad_t + plot_h * 0.5)
            cr.show_text("Run or learn an Experience to populate the learning curve.")
            return False

        max_cum = max(1, max(int(p.get("cumulative", 0)) for p in pts))
        # Left axis labels (tool count)
        cr.set_source_rgba(*_hex_to_rgb(ui.TEXT_MUTED), 0.9)
        cr.move_to(6.0, pad_t + 4.0)
        cr.show_text(str(max_cum))
        cr.move_to(6.0, pad_t + plot_h + 3.0)
        cr.show_text("0")

        n = len(pts)
        cum_coords: List[tuple[float, float]] = []
        rate_coords: List[tuple[float, float]] = []
        for i, pt in enumerate(pts):
            x = pad_l + (plot_w * i / max(1, n - 1))
            y_cum = pad_t + plot_h * (1.0 - float(pt.get("cumulative", 0)) / max_cum)
            y_rate = pad_t + plot_h * (1.0 - max(0.0, min(1.0, float(pt.get("success_rate", 1.0)))))
            cum_coords.append((x, y_cum))
            rate_coords.append((x, y_rate))

        # Crimson translucent area under cumulative curve
        cr.move_to(cum_coords[0][0], pad_t + plot_h)
        for x, y in cum_coords:
            cr.line_to(x, y)
        cr.line_to(cum_coords[-1][0], pad_t + plot_h)
        cr.close_path()
        grad = cairo.LinearGradient(0, pad_t, 0, pad_t + plot_h)
        grad.add_color_stop_rgba(0.0, ar, ag, ab, 0.28)
        grad.add_color_stop_rgba(1.0, ar, ag, ab, 0.02)
        cr.set_source(grad)
        cr.fill()

        # Cumulative tools stroke
        cr.set_source_rgb(ar, ag, ab)
        cr.set_line_width(2.0)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.move_to(*cum_coords[0])
        for x, y in cum_coords[1:]:
            cr.line_to(x, y)
        cr.stroke()

        # Success rate stroke (emerald)
        cr.set_source_rgb(sr, sg, sb)
        cr.set_line_width(2.0)
        cr.move_to(*rate_coords[0])
        for x, y in rate_coords[1:]:
            cr.line_to(x, y)
        cr.stroke()

        # Point markers
        for (cx, cy), (rx, ry) in zip(cum_coords, rate_coords, strict=False):
            cr.set_source_rgb(ar, ag, ab)
            cr.arc(cx, cy, 2.8, 0, math.tau)
            cr.fill()
            cr.set_source_rgb(sr, sg, sb)
            cr.arc(rx, ry, 2.6, 0, math.tau)
            cr.fill()

        # First / middle / last X-axis timestamp labels
        cr.set_source_rgb(*_hex_to_rgb(ui.TEXT_MUTED))
        cr.set_font_size(8.2)
        label_indices = sorted({0, n // 2, n - 1})
        for idx in label_indices:
            lbl = str(pts[idx].get("label") or "")
            x = cum_coords[idx][0]
            ext = cr.text_extents(lbl)
            draw_x = max(pad_l, min(pad_l + plot_w - ext.width, x - ext.width / 2.0))
            cr.move_to(draw_x, h - 7.0)
            cr.show_text(lbl)

        return False


class ExperiencesView(Gtk.Box):
    """Full visual Learning & Experiences tab mounted inside `TchikoAssistantWindow`."""

    def __init__(
        self,
        engine: TchikoAgentEngine,
        on_run_in_chat: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.engine = engine
        self.on_run_in_chat = on_run_in_chat
        self._selected_slug: str = ""
        self._maturity_filter: str = "ALL"
        self._search_query: str = ""
        self._rows_by_slug: Dict[str, Gtk.ListBoxRow] = {}
        self._filter_buttons: Dict[str, Gtk.RadioButton] = {}
        self._running_action = False

        for setter in (self.set_margin_start, self.set_margin_end):
            setter(24)
        self.set_margin_top(20)
        self.set_margin_bottom(20)

        self._build_ui()
        self.engine.experiences.subscribe(self._on_registry_event)
        self.refresh()

    # ── UI Construction ──────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        # Header
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.pack_start(ui.label("Learning & Experiences", "display"), False, False, 0)
        titles.pack_start(
            ui.label("Reusable, AST-validated Python tool scripts distilled from verified tasks.", "dim"),
            False,
            False,
            0,
        )
        head.pack_start(titles, True, True, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_valign(Gtk.Align.END)

        self.learn_btn = Gtk.Button(label="+ Learn from Last Task")
        self.learn_btn.get_style_context().add_class("tchiko-primary")
        self.learn_btn.connect("clicked", self._on_learn_last_clicked)
        btn_box.pack_start(self.learn_btn, False, False, 0)

        refresh_btn = ui.icon_button("view-refresh-symbolic", "Refresh experiences")
        refresh_btn.connect("clicked", lambda *_: self.refresh())
        btn_box.pack_start(refresh_btn, False, False, 0)
        head.pack_end(btn_box, False, False, 0)
        self.pack_start(head, False, False, 0)

        # KPI strip
        kpi_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)
        self.kpi_total_val = ui.label("0", "title")
        self.kpi_total_sub = ui.label("0 hardened · 0 verified", "dim")
        kpi_row.pack_start(self._kpi_card("EXPERIENCES", self.kpi_total_val, self.kpi_total_sub), True, True, 0)

        self.kpi_runs_val = ui.label("0", "title")
        self.kpi_runs_sub = ui.label("0 self-recoveries", "dim")
        kpi_row.pack_start(self._kpi_card("TOOL RUNS", self.kpi_runs_val, self.kpi_runs_sub), True, True, 0)

        # Success rate card with RingGauge
        rate_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        rate_card.get_style_context().add_class("tchiko-card")
        rate_card.get_style_context().add_class("tchiko-card-pad")
        self.rate_gauge = ui.RingGauge(54)
        rate_card.pack_start(self.rate_gauge, False, False, 0)
        rate_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        rate_text.set_valign(Gtk.Align.CENTER)
        rate_text.pack_start(ui.label("RELIABILITY", "caption"), False, False, 0)
        self.kpi_rate_val = ui.label("100%", "title")
        self.kpi_rate_sub = ui.label("rolling success rate", "dim")
        rate_text.pack_start(self.kpi_rate_val, False, False, 0)
        rate_text.pack_start(self.kpi_rate_sub, False, False, 0)
        rate_card.pack_start(rate_text, True, True, 0)
        kpi_row.pack_start(rate_card, True, True, 0)
        self.pack_start(kpi_row, False, False, 0)

        # Learning curve card
        chart_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        chart_card.get_style_context().add_class("tchiko-card")
        self.curve_chart = LearningCurveChart()
        chart_card.pack_start(self.curve_chart, True, True, 0)
        self.pack_start(chart_card, False, False, 0)

        # Filter + search bar
        filter_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Filter experiences by name, trigger, or category…")
        self.search_entry.get_style_context().add_class("tchiko-search")
        self.search_entry.connect("changed", self._on_search_changed)
        filter_row.pack_start(self.search_entry, True, True, 0)

        group: Optional[Gtk.RadioButton] = None
        for f_key, f_lbl in (
            ("ALL", "All"),
            (MATURITY_HARDENED, "Hardened"),
            (MATURITY_VERIFIED, "Verified"),
            (MATURITY_DRAFT, "Draft"),
            (MATURITY_NEEDS_REPAIR, "Repair"),
        ):
            btn = Gtk.RadioButton.new_with_label_from_widget(group, f_lbl)
            group = group or btn
            btn.set_mode(False)
            btn.get_style_context().add_class("tchiko-filter-btn")
            btn.connect("toggled", self._on_filter_toggled, f_key)
            self._filter_buttons[f_key] = btn
            filter_row.pack_start(btn, False, False, 0)
        self.pack_start(filter_row, False, False, 0)

        # Master-detail split
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(315)
        paned.set_wide_handle(False)

        # Left: Experience list
        list_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        list_card.get_style_context().add_class("tchiko-card")
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        list_scroll.get_style_context().add_class("tchiko-scroll")
        self.exp_list = Gtk.ListBox()
        self.exp_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.exp_list.get_style_context().add_class("tchiko-exp-list")
        self.exp_list.connect("row-selected", self._on_row_selected)
        empty = ui.label("No Experiences match this filter.", "muted", xalign=0.5)
        empty.set_margin_top(36)
        empty.show()
        self.exp_list.set_placeholder(empty)
        list_scroll.add(self.exp_list)
        list_card.pack_start(list_scroll, True, True, 0)
        paned.pack1(list_card, resize=False, shrink=False)

        # Right: Inspector
        insp_scroll = Gtk.ScrolledWindow()
        insp_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        insp_scroll.get_style_context().add_class("tchiko-scroll")

        insp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        insp.set_margin_start(12)

        detail_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        detail_card.get_style_context().add_class("tchiko-card")
        detail_card.get_style_context().add_class("tchiko-card-pad")

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.insp_title = ui.label("Select an Experience", "title")
        self.insp_badge = Gtk.Label(label="")
        self.insp_badge.get_style_context().add_class("tchiko-badge")
        top_row.pack_start(self.insp_title, True, True, 0)
        top_row.pack_end(self.insp_badge, False, False, 0)
        detail_card.pack_start(top_row, False, False, 0)

        self.insp_desc = ui.label("Pick a learned Python tool on the left to inspect its script and history.", "dim", wrap=True)
        detail_card.pack_start(self.insp_desc, False, False, 0)

        self.insp_meta = ui.label("", "muted", wrap=True)
        detail_card.pack_start(self.insp_meta, False, False, 0)

        # Action toolbar
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.btn_run = Gtk.Button(label="Run")
        self.btn_run.get_style_context().add_class("tchiko-primary")
        self.btn_run.connect("clicked", lambda *_: self._run_selected(dry_run=False))

        self.btn_dry = Gtk.Button(label="Dry-Run")
        self.btn_dry.get_style_context().add_class("tchiko-btn")
        self.btn_dry.connect("clicked", lambda *_: self._run_selected(dry_run=True))

        self.btn_approve = Gtk.Button(label="Approve")
        self.btn_approve.get_style_context().add_class("tchiko-btn")
        self.btn_approve.connect("clicked", self._on_approve_clicked)

        self.btn_toggle = Gtk.Button(label="Disable")
        self.btn_toggle.get_style_context().add_class("tchiko-btn")
        self.btn_toggle.connect("clicked", self._on_toggle_clicked)

        self.btn_rollback = Gtk.Button(label="Rollback")
        self.btn_rollback.get_style_context().add_class("tchiko-btn")
        self.btn_rollback.connect("clicked", self._on_rollback_clicked)

        self.btn_delete = Gtk.Button(label="Delete")
        self.btn_delete.get_style_context().add_class("tchiko-danger-btn")
        self.btn_delete.connect("clicked", self._on_delete_clicked)

        for b in (self.btn_run, self.btn_dry, self.btn_approve, self.btn_toggle, self.btn_rollback):
            actions.pack_start(b, False, False, 0)
        actions.pack_end(self.btn_delete, False, False, 0)
        detail_card.pack_start(actions, False, False, 0)

        # Live execution status/output area
        self.out_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.out_card.get_style_context().add_class("tchiko-code-card")
        self.out_card.set_no_show_all(True)
        out_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        out_head.get_style_context().add_class("tchiko-code-head")
        self.out_title = ui.label("LAST EXECUTION OUTPUT", "caption")
        out_head.pack_start(self.out_title, True, True, 0)
        self.out_card.pack_start(out_head, False, False, 0)
        out_body = Gtk.Box()
        out_body.get_style_context().add_class("tchiko-code-body")
        self.out_label = ui.label("", "tchiko-code-text", wrap=True, selectable=True)
        out_body.pack_start(self.out_label, True, True, 0)
        self.out_card.pack_start(out_body, False, False, 0)
        detail_card.pack_start(self.out_card, False, False, 0)

        insp.pack_start(detail_card, False, False, 0)

        # Python script code card
        code_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        code_card.get_style_context().add_class("tchiko-code-card")
        code_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        code_head.get_style_context().add_class("tchiko-code-head")
        self.code_path_lbl = ui.label("PYTHON SCRIPT  ·  tool.py", "caption")
        copy_btn = ui.icon_button("edit-copy-symbolic", "Copy Python script", pixel_size=14)
        copy_btn.connect("clicked", self._on_copy_script)
        code_head.pack_start(self.code_path_lbl, True, True, 0)
        code_head.pack_end(copy_btn, False, False, 0)
        code_card.pack_start(code_head, False, False, 0)

        code_scroll = Gtk.ScrolledWindow()
        code_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        code_scroll.set_min_content_height(210)
        code_scroll.get_style_context().add_class("tchiko-scroll")
        self.code_view = Gtk.TextView()
        self.code_view.set_editable(False)
        self.code_view.set_cursor_visible(False)
        self.code_view.set_left_margin(10)
        self.code_view.set_right_margin(10)
        self.code_view.set_top_margin(8)
        self.code_view.set_bottom_margin(8)
        self.code_view.get_style_context().add_class("tchiko-code-view")
        code_scroll.add(self.code_view)
        code_card.pack_start(code_scroll, True, True, 0)
        insp.pack_start(code_card, True, True, 0)

        # Evolution & run history card
        hist_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hist_card.get_style_context().add_class("tchiko-card")
        hist_card.get_style_context().add_class("tchiko-card-pad")
        hist_card.pack_start(ui.label("EVOLUTION & RECENT RUNS", "caption"), False, False, 0)
        self.hist_label = ui.label("No executions recorded yet.", "dim", wrap=True, selectable=True)
        hist_card.pack_start(self.hist_label, False, False, 0)
        insp.pack_start(hist_card, False, False, 0)

        insp_scroll.add(insp)
        paned.pack2(insp_scroll, resize=True, shrink=False)
        self.pack_start(paned, True, True, 0)

    @staticmethod
    def _kpi_card(caption: str, value_lbl: Gtk.Label, sub_lbl: Gtk.Label) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        card.get_style_context().add_class("tchiko-card")
        card.get_style_context().add_class("tchiko-card-pad")
        card.pack_start(ui.label(caption, "caption"), False, False, 0)
        card.pack_start(value_lbl, False, False, 0)
        card.pack_start(sub_lbl, False, False, 0)
        return card

    # ── Data Sync ────────────────────────────────────────────────────────────
    def _on_registry_event(self, _event: str, _exp: Optional[Experience]) -> None:
        GLib.idle_add(self.refresh)

    def select_slug(self, slug: str) -> None:
        self._selected_slug = slug
        self.refresh()

    def refresh(self) -> bool:
        metrics = self.engine.experiences.learning_metrics()
        by_mat = metrics.get("by_maturity", {})
        total = int(metrics.get("total", 0))
        hardened = int(by_mat.get(MATURITY_HARDENED, 0))
        verified = int(by_mat.get(MATURITY_VERIFIED, 0))
        draft = int(by_mat.get(MATURITY_DRAFT, 0))
        repair = int(by_mat.get(MATURITY_NEEDS_REPAIR, 0))
        runs = int(metrics.get("total_runs", 0))
        recoveries = int(metrics.get("total_recoveries", 0))
        rate = float(metrics.get("overall_success_rate", 1.0))

        self.kpi_total_val.set_text(str(total))
        self.kpi_total_sub.set_text(f"{hardened} hardened · {verified} verified · {draft} draft" + (f" · {repair} repair" if repair else ""))
        self.kpi_runs_val.set_text(str(runs))
        self.kpi_runs_sub.set_text(f"{recoveries} self-recover{'y' if recoveries == 1 else 'ies'}")
        self.rate_gauge.set_fraction(rate)
        self.kpi_rate_val.set_text(f"{int(round(rate * 100))}%")
        self.curve_chart.set_metrics(metrics)

        exps = self.engine.experiences.list_experiences()
        filtered: List[Experience] = []
        q = self._search_query.lower().strip()
        for e in exps:
            if self._maturity_filter != "ALL" and e.maturity != self._maturity_filter:
                continue
            if q:
                hay = f"{e.slug} {e.title} {e.description} {e.category} {' '.join(e.triggers)}".lower()
                if q not in hay:
                    continue
            filtered.append(e)

        for child in list(self.exp_list.get_children()):
            self.exp_list.remove(child)
        self._rows_by_slug.clear()

        for exp in filtered:
            row = Gtk.ListBoxRow()
            row._exp_slug = exp.slug  # type: ignore[attr-defined]
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            title_lbl = ui.label(exp.title, "tchiko-row-title")
            title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            badge = Gtk.Label(label=exp.maturity.replace("_", " "))
            badge.get_style_context().add_class("tchiko-badge")
            badge.get_style_context().add_class(_maturity_css(exp.maturity))
            top.pack_start(title_lbl, True, True, 0)
            top.pack_end(badge, False, False, 0)
            box.pack_start(top, False, False, 0)

            sub = Gtk.Label(xalign=0.0)
            sub.set_ellipsize(Pango.EllipsizeMode.END)
            pct = int(round(exp.success_rate * 100))
            state_tag = "" if exp.enabled else " · DISABLED"
            sub.set_markup(
                f"<span size='small' font_family='{ui.PANGO_MONO}' foreground='{ui.TEXT_MUTED}'>"
                f"{html.escape(exp.slug)} · v{exp.version} · {exp.runs} runs · {pct}%{state_tag}</span>"
            )
            box.pack_start(sub, False, False, 0)

            row.add(box)
            self.exp_list.add(row)
            self._rows_by_slug[exp.slug] = row

        self.exp_list.show_all()

        if self._selected_slug in self._rows_by_slug:
            self.exp_list.select_row(self._rows_by_slug[self._selected_slug])
            self._render_inspector(self._selected_slug)
        elif filtered:
            self._selected_slug = filtered[0].slug
            self.exp_list.select_row(self._rows_by_slug[self._selected_slug])
            self._render_inspector(self._selected_slug)
        else:
            self._selected_slug = ""
            self._render_inspector("")
        return False

    def _render_inspector(self, slug: str) -> None:
        exp = self.engine.experiences.get_experience(slug) if slug else None
        has_exp = exp is not None
        for b in (self.btn_run, self.btn_dry, self.btn_approve, self.btn_toggle, self.btn_rollback, self.btn_delete):
            b.set_sensitive(has_exp and not self._running_action)

        ctx = self.insp_badge.get_style_context()
        for c in ("hardened", "verified", "draft", "repair"):
            ctx.remove_class(c)

        if exp is None:
            self.insp_title.set_text("No Experience Selected")
            self.insp_badge.set_text("")
            self.insp_desc.set_text("Solve a multi-step task or click '+ Learn from Last Task' to create a Python Experience.")
            self.insp_meta.set_text("")
            self.code_path_lbl.set_text("PYTHON SCRIPT")
            self.code_view.get_buffer().set_text("")
            self.hist_label.set_text("No executions recorded yet.")
            return

        self.insp_title.set_text(exp.title)
        self.insp_badge.set_text(exp.maturity.replace("_", " "))
        ctx.add_class(_maturity_css(exp.maturity))
        self.insp_desc.set_text(exp.description)

        pct = int(round(exp.success_rate * 100))
        triggers = ", ".join(exp.triggers) or "none"
        self.insp_meta.set_markup(
            f"<span size='small' font_family='{ui.PANGO_MONO}' foreground='{ui.TEXT_SECONDARY}'>"
            f"slug: {html.escape(exp.slug)}  ·  v{exp.version}  ·  category: {html.escape(exp.category)}  ·  "
            f"risk: {html.escape(exp.risk_tier)}\n"
            f"runs: {exp.runs} ({pct}% ok)  ·  avg: {exp.avg_duration_ms}ms  ·  triggers: {html.escape(triggers)}</span>"
        )

        self.btn_approve.set_sensitive(exp.maturity in (MATURITY_DRAFT, MATURITY_NEEDS_REPAIR) and not self._running_action)
        self.btn_toggle.set_label("Disable" if exp.enabled else "Enable")
        versions = self.engine.experiences.get_versions(exp.slug)
        self.btn_rollback.set_sensitive(bool(versions) and not self._running_action)

        code = self.engine.experiences.get_script_source(exp.slug)
        self.code_path_lbl.set_text(f"PYTHON SCRIPT  ·  experiences/{exp.slug}/tool.py")
        self.code_view.get_buffer().set_text(code)

        lines: List[str] = []
        for note in exp.evolution_notes[-4:]:
            ts_s = datetime.fromtimestamp(float(note.get("ts") or 0)).strftime("%m/%d %H:%M") if note.get("ts") else ""
            lines.append(f"• v{note.get('version', '?')} [{ts_s}] — {note.get('note', '')}")
        hist = self.engine.experiences.get_history(exp.slug, limit=6)
        for h in reversed(hist):
            ts_s = datetime.fromtimestamp(float(h.get("ts") or 0)).strftime("%m/%d %H:%M") if h.get("ts") else ""
            icon = "✓" if h.get("ok") else "✕"
            lines.append(
                f"{icon} [{ts_s}] v{h.get('version', '?')} ({h.get('duration_ms', 0)}ms) — "
                f"{str(h.get('summary') or '').splitlines()[0][:110]}"
            )
        self.hist_label.set_text("\n".join(lines) if lines else "No runs recorded yet. Click 'Dry-Run' or 'Run' to test.")

    # ── Interactions ─────────────────────────────────────────────────────────
    def _on_search_changed(self, entry: Gtk.Entry) -> None:
        self._search_query = entry.get_text()
        self.refresh()

    def _on_filter_toggled(self, btn: Gtk.RadioButton, f_key: str) -> None:
        if btn.get_active():
            self._maturity_filter = f_key
            self.refresh()

    def _on_row_selected(self, _lb: Gtk.ListBox, row: Optional[Gtk.ListBoxRow]) -> None:
        if row is not None:
            slug = getattr(row, "_exp_slug", "")
            if slug:
                self._selected_slug = slug
                self._render_inspector(slug)

    def _show_output(self, title: str, text: str) -> None:
        self.out_title.set_text(title.upper())
        self.out_label.set_text(text[:2400])
        self.out_card.set_no_show_all(False)
        self.out_card.show_all()

    def _run_selected(self, dry_run: bool) -> None:
        if not self._selected_slug or self._running_action:
            return
        slug = self._selected_slug
        self._running_action = True
        self._render_inspector(slug)
        self._show_output(
            f"{'Dry-running' if dry_run else 'Running'} {slug}…",
            "Executing Python script…",
        )

        def _worker() -> None:
            res = self.engine.experiences.run_experience(slug, {}, dry_run=dry_run)

            def _done() -> bool:
                self._running_action = False
                prefix = "OK" if res.ok else "FAILED"
                self._show_output(
                    f"{res.title} · {prefix} ({res.duration_ms}ms)",
                    res.output,
                )
                self.refresh()
                return False

            GLib.idle_add(_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_approve_clicked(self, *_args: Any) -> None:
        if self._selected_slug:
            exp = self.engine.experiences.approve_experience(self._selected_slug)
            if exp:
                self._show_output("Approved", f"Experience `{exp.slug}` promoted to {exp.maturity}.")
                self.refresh()

    def _on_toggle_clicked(self, *_args: Any) -> None:
        if not self._selected_slug:
            return
        exp = self.engine.experiences.get_experience(self._selected_slug)
        if exp is None:
            return
        updated = self.engine.experiences.set_enabled(exp.slug, not exp.enabled)
        if updated:
            self._show_output("Updated", f"Experience `{updated.slug}` is now {'enabled' if updated.enabled else 'disabled'}.")
            self.refresh()

    def _on_rollback_clicked(self, *_args: Any) -> None:
        if not self._selected_slug:
            return
        ok, msg = self.engine.experiences.rollback_version(self._selected_slug)
        self._show_output("Rollback OK" if ok else "Rollback Notice", msg)
        self.refresh()

    def _on_delete_clicked(self, *_args: Any) -> None:
        if not self._selected_slug:
            return
        slug = self._selected_slug
        if self.engine.experiences.delete_experience(slug):
            self._selected_slug = ""
            self._show_output("Deleted", f"Removed Experience `{slug}`.")
            self.refresh()

    def _on_copy_script(self, btn: Gtk.Button) -> None:
        buf = self.code_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        if text:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
            ui.flash_button_icon(btn)

    def _on_learn_last_clicked(self, *_args: Any) -> None:
        ep = self.engine.last_episode
        if not ep and self.engine.memory.get("last_command"):
            ep = {
                "prompt": self.engine.memory.get("last_command", "learned-command"),
                "steps": [{"tool": "bash", "args_summary": self.engine.memory.get("last_command", ""), "ok": True}],
                "succeeded": True,
                "verified": True,
                "recoveries_succeeded": 0,
            }
        if not ep:
            self._show_output(
                "No Recent Episode",
                "Run a task in Chat first, then click '+ Learn from Last Task' (or type `/learn`).",
            )
            return

        exp, msg = self.engine.experiences.learn_from_episode(ep, force=True)
        if exp is None:
            self._show_output("Learning Skipped", msg)
            return
        self._selected_slug = exp.slug
        self._show_output("Experience Learned", msg)
        self.refresh()
