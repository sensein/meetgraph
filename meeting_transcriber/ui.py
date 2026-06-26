"""PyQt6 desktop UI for the meeting transcriber."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import threading

from PyQt6.QtCore import Qt, QObject, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QPixmap, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .audio import find_system_audio_device, list_input_devices
from .controller import TranscriptionController
from .transcript import Transcript, reveal_in_file_manager

SPEAKER_COLORS = {"You": "#2563eb", "Meeting": "#0d9488"}

# Cloud transcription providers (OpenAI-compatible /audio/transcriptions).
# key -> (label, base_url, default_model). Future-proof: providers without a
# speech-to-text API today can still be selected; transcription is attempted via
# the standard endpoint and just works once they add it.
COMPAT_PROVIDERS = {
    "openai": ("OpenAI", "https://api.openai.com/v1", "whisper-1"),
    "groq": ("Groq", "https://api.groq.com/openai/v1", "whisper-large-v3"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", ""),
    "anthropic": ("Anthropic (Claude)", "https://api.anthropic.com/v1", ""),
    "local": ("Local server (vLLM / LM Studio…)", "http://localhost:8000/v1", ""),
    "custom": ("Custom…", "", ""),
}

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"        # full lockup (icon + wordmark)
ICON_PATH = Path(__file__).parent / "assets" / "logo_icon.png"   # icon only (for header / app icon)


def app_icon() -> QIcon:
    p = ICON_PATH if ICON_PATH.exists() else LOGO_PATH
    return QIcon(str(p)) if p.exists() else QIcon()

STYLESHEET = """
* { font-family: -apple-system, "SF Pro Text", "Segoe UI", "Helvetica Neue", sans-serif; }
QWidget { background: #eef1f6; color: #1f2733; font-size: 13px; }

/* Soft gradient app background (shows through transparent tabs/pages) */
#Root {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #d7e6fb, stop:0.5 #e6ecf7, stop:1 #d6efe9);
}
QTabWidget { background: transparent; }
QTabWidget::pane { border: none; background: transparent; top: 4px; }
QTabBar { background: transparent; qproperty-drawBase: 0; }
QTabBar::tab {
    background: #ffffff;
    color: #475569;
    border: 1px solid #e2e8f0;
    padding: 8px 20px;
    margin-right: 6px;
    border-radius: 9px;
    font-weight: 600;
}
QTabBar::tab:selected { background: #2563eb; color: #ffffff; border-color: #2563eb; }
QTabBar::tab:hover:!selected { background: #f1f5f9; }
#ConfigPage, #RecordPage { background: transparent; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget { background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

#Header { background: transparent; }
#HeaderTitle { font-size: 22px; font-weight: 700; color: #0f172a; }
#HeaderSubtitle { font-size: 12px; color: #64748b; }

QGroupBox {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    margin-top: 16px;
    padding: 16px 16px 14px 16px;
    font-weight: 600;
    color: #334155;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 2px 8px;
    color: #475569;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.4px;
}

QLabel { background: transparent; color: #475569; }
QStackedWidget, QStackedWidget > QWidget { background: transparent; }

QLineEdit, QComboBox {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 7px 10px;
    color: #1f2733;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #2563eb; }
QLineEdit:disabled, QComboBox:disabled { background: #f1f5f9; color: #94a3b8; }
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: center right;
    border: none; width: 26px;
}
QComboBox::down-arrow {
    width: 0; height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #64748b;
    margin-right: 11px;
}
QComboBox::down-arrow:hover { border-top-color: #2563eb; }
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 3px;
    outline: none;
}
QComboBox QAbstractItemView::item {
    background: #ffffff;
    color: #1f2733;
    padding: 5px 10px;
    min-height: 22px;
    border-radius: 5px;
}
QComboBox QAbstractItemView::item:selected { background: #2563eb; color: #ffffff; }
QComboBox QAbstractItemView::item:hover { background: #eef2fb; color: #1f2733; }
/* Editable-combo completer popup */
QComboBox QListView { background: #ffffff; }

QPushButton {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 8px 15px;
    color: #334155;
    font-weight: 600;
}
QPushButton:hover { background: #f1f5f9; }
QPushButton:pressed { background: #e2e8f0; }
QPushButton:disabled { color: #94a3b8; background: #f8fafc; border-color: #e2e8f0; }

QPushButton#primary { background: #2563eb; border: 1px solid #2563eb; color: #ffffff; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:pressed { background: #1e40af; }
QPushButton#primary:disabled { background: #a8c2f4; border-color: #a8c2f4; color: #eef2ff; }

QPushButton#danger { background: #ffffff; border: 1px solid #fca5a5; color: #dc2626; }
QPushButton#danger:hover { background: #fef2f2; }
QPushButton#danger:disabled { color: #cbd5e1; border-color: #e2e8f0; background: #f8fafc; }

QCheckBox { spacing: 8px; background: transparent; color: #334155; font-weight: 600; }
QCheckBox::indicator {
    width: 17px; height: 17px;
    border: 1px solid #cbd5e1; border-radius: 5px; background: #ffffff;
}
QCheckBox::indicator:checked { background: #2563eb; border-color: #2563eb; }
QCheckBox::indicator:hover { border-color: #2563eb; }

QTextEdit#transcript {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 12px;
}

#statusBar {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    color: #64748b;
    padding: 8px 12px;
    font-size: 12px;
}

QScrollBar:vertical { background: transparent; width: 11px; margin: 3px; }
QScrollBar::handle:vertical { background: #cbd5e1; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #94a3b8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QDialog { background: #eef1f6; }
"""


class MainWindow(QWidget):
    def __init__(self, user_name: str = "", meeting_name: str = "", user_email: str = "") -> None:
        super().__init__()
        self.setWindowTitle("MeetGraph")
        self.setObjectName("Root")
        self.setWindowIcon(app_icon())
        self.resize(960, 840)
        self.setMinimumWidth(720)

        from .storage import Store

        self.transcript = Transcript()
        self.controller = TranscriptionController()
        self.devices = list_input_devices()
        self.store = Store()
        self.user = user_name.strip() or "local"
        self.user_email = (user_email or self.store.get_setting("user_email") or "").strip()
        self.speaker_self = user_name.strip() or "You"
        self._display_name = user_name.strip() or "Local"
        self.team_id = (self.store.get_setting("team.id") or "").strip()
        self.team_name = (self.store.get_setting("team.name") or "").strip()
        # Stable per-install id so meetings get globally-unique ids in a shared DB
        # (local autoincrement ids would otherwise collide across team members).
        self._node_id = (self.store.get_setting("node.id") or "").strip()
        if not self._node_id:
            import secrets
            self._node_id = secrets.token_hex(8)
            self.store.set_setting("node.id", self._node_id)
        # When the active team's key is revoked we drop to personal mode; the
        # team stays viewable read-only via the Summary 'Show' menu.
        self._team_readonly = False
        self._revoked_team_name = ""
        self.meeting_name = meeting_name.strip()
        self._started_at = None
        self._meeting_id = None
        self._last_summary_md = ""    # the live/current meeting's summary
        self._last_summary_json = ""
        self._view_md = ""            # detail view (Summary tab)
        self._view_json = ""
        self._summary_dirty = False   # new speech since last summary
        self._notes_busy = False      # a summary generation is in flight
        self._running_summary = None  # incremental live summary (merged across ticks)
        self._summarized_chars = 0    # transcript length already summarized
        self._processing: set = set()  # (meeting_id, stage) currently being enriched
        self._open_details: dict = {}  # meeting_id -> open MeetingDetailDialog (for live refresh)
        self._loading = True  # suppress config saves while widgets are built/loaded

        self._build_ui()
        self._wire_controller()
        self._load_config()
        self._wire_config_persistence()
        self._loading = False
        self._update_proc_status()
        self._update_using_labels()
        QTimer.singleShot(1500, self._resume_pending)  # finish any interrupted enrichment

    # ---------------------------------------------------------------- UI build
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        root.addLayout(self._build_header())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_record_tab(), "  ◉  Meeting  ")
        self.tabs.addTab(self._build_summary_tab(), "  ✦  Summary  ")
        self.tabs.addTab(self._build_config_tab(), "  ⚙  Configuration  ")
        self.tabs.addTab(self._build_about_tab(), "  ℹ  About  ")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("statusBar")
        root.addWidget(self.status_label)

        self._populate_devices()
        self._on_engine_changed()
        self._init_team_state()

    def _init_team_state(self) -> None:
        """On startup: make sure the active team has a membership record (migrates
        users who joined before multi-team support) and compute read-only status."""
        try:
            if self.team_id and not self.store.get_membership(self.team_id):
                self.store.add_membership(
                    self.team_id, self.team_name, "", "",
                    datetime.now().isoformat(timespec="seconds"))
            self._refresh_team_readonly()
            self._update_team_status()
        except Exception:
            pass

    # --------------------------------------------------------------- tabs
    def _build_record_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("RecordPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(2, 10, 2, 2)
        v.setSpacing(10)

        self.models_banner = QLabel("")
        self.models_banner.setWordWrap(True)
        self.models_banner.setText("")
        v.addWidget(self.models_banner)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        self.start_btn = QPushButton("● Start meeting")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._on_start)
        ctrl_row.addWidget(self.start_btn)

        self.pause_btn = QPushButton("❚❚ Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause_resume)
        ctrl_row.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.controller.stop)
        ctrl_row.addWidget(self.stop_btn)
        ctrl_row.addStretch()

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._on_clear)
        ctrl_row.addWidget(self.clear_btn)
        self.copy_btn = QPushButton("Copy Markdown")
        self.copy_btn.clicked.connect(self._on_copy)
        ctrl_row.addWidget(self.copy_btn)
        self.save_btn = QPushButton("Save .md")
        self.save_btn.clicked.connect(self._on_save)
        ctrl_row.addWidget(self.save_btn)
        self.share_btn = QPushButton("Share…")
        self.share_btn.clicked.connect(self._on_share)
        ctrl_row.addWidget(self.share_btn)
        v.addLayout(ctrl_row)

        _LABEL = "font-weight:700; font-size:11px; color:#475569; letter-spacing:0.4px;"
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        left = QWidget(); left.setObjectName("RecordPage")
        ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(6)
        tlabel = QLabel("Live transcript"); tlabel.setStyleSheet(_LABEL)
        ll.addWidget(tlabel)
        self.transcript_view = QTextEdit()
        self.transcript_view.setObjectName("transcript")
        self.transcript_view.setReadOnly(True)
        self.transcript_view.setFont(QFont("SF Mono, Menlo, monospace", 12))
        self.transcript_view.setPlaceholderText(
            "Transcribed speech will appear here, labelled by source (You / Meeting)…"
        )
        ll.addWidget(self.transcript_view, 1)
        split.addWidget(left)

        right = QWidget(); right.setObjectName("RecordPage")
        rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(6)
        srow = QHBoxLayout(); srow.setSpacing(8)
        slabel = QLabel("Live summary"); slabel.setStyleSheet(_LABEL)
        srow.addWidget(slabel); srow.addStretch()
        self.auto_refresh = QCheckBox("Auto")
        self.auto_refresh.setChecked(True)
        self.auto_refresh.setToolTip("On by default — the summary regenerates automatically as you talk. "
                                     "Uncheck only if you'd rather refresh manually with ⟳.")
        srow.addWidget(self.auto_refresh)
        self.summary_btn = QPushButton("⟳")
        self.summary_btn.setToolTip("Refresh the summary now (optional — Auto does this for you)")
        self.summary_btn.setMaximumWidth(40)
        self.summary_btn.clicked.connect(self._run_notes)
        srow.addWidget(self.summary_btn)
        self.live_copy_btn = QPushButton("Copy")
        self.live_copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self._last_summary_md))
        srow.addWidget(self.live_copy_btn)
        self.live_email_btn = QPushButton("Email…")
        self.live_email_btn.setToolTip("Email this summary to your team")
        self.live_email_btn.clicked.connect(self._email_live_summary)
        srow.addWidget(self.live_email_btn)
        rl.addLayout(srow)
        self.summary_view = QTextBrowser()
        self.summary_view.setObjectName("transcript")
        self.summary_view.setOpenExternalLinks(True)  # key terms link to Wikipedia
        self.summary_view.setFont(QFont("SF Pro Text", 13))
        self.summary_view.setPlaceholderText(
            "A live summary (topics · decisions · open questions · action items · key terms) "
            "appears here automatically as you talk — no button needed."
        )
        rl.addWidget(self.summary_view, 1)
        self.summary_hint = QLabel(
            "Generates automatically as you speak. With local models (Ollama / Whisper) "
            "the first summary can take a while depending on your hardware."
        )
        self.summary_hint.setWordWrap(True)
        self.summary_hint.setStyleSheet("color:#64748b; font-size:11px;")
        rl.addWidget(self.summary_hint)
        split.addWidget(right)
        split.setSizes([540, 430])
        v.addWidget(split, 1)

        # Live auto-summary timer (fires while recording + "Auto" on + new speech).
        self._summary_timer = QTimer(self)
        self._summary_timer.setInterval(15_000)
        self._summary_timer.timeout.connect(self._on_summary_tick)
        return page

    def _build_summary_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("RecordPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(2, 10, 2, 2)
        v.setSpacing(10)
        _LABEL = "font-weight:700; font-size:11px; color:#475569; letter-spacing:0.4px;"

        srow = QHBoxLayout(); srow.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔎  Search meetings — title, transcript, or notes…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._refresh_meetings)
        srow.addWidget(self.search_edit, 1)
        srow.addWidget(QLabel("Show:"))
        self.scope_combo = QComboBox()
        self.scope_combo.setToolTip("View your personal meetings (this device) or the shared "
                                    "meetings of any team you've joined.")
        self.scope_combo.currentIndexChanged.connect(self._refresh_meetings)
        self._populate_scope_combo()
        srow.addWidget(self.scope_combo)
        refresh = QPushButton("↻ Refresh")
        refresh.clicked.connect(self._refresh_meetings)
        srow.addWidget(refresh)
        send_btn = QPushButton("⇪ Send…")
        send_btn.setToolTip("Bulk send/sync these meetings to email, REST API, MCP, or your "
                            "external databases — skipping any already sent.")
        send_btn.clicked.connect(self._bulk_send)
        srow.addWidget(send_btn)
        graph_btn = QPushButton("⬡ Export graph")
        graph_btn.setToolTip("Export all meetings as one connected knowledge graph "
                             "(JSON-LD / Turtle) — key terms linked to Wikipedia/Wikidata, "
                             "meetings chained to their predecessors.")
        graph_btn.clicked.connect(self._export_graph)
        srow.addWidget(graph_btn)
        v.addLayout(srow)

        self.meetings_table = QTableWidget(0, 6)
        self.meetings_table.setHorizontalHeaderLabels(
            ["Meeting", "Team", "Date", "Participant", "Summary", "Status"])
        self.meetings_table.verticalHeader().setVisible(False)
        self.meetings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.meetings_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.meetings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.meetings_table.setSortingEnabled(True)
        self.meetings_table.setCursor(Qt.CursorShape.PointingHandCursor)
        hh = self.meetings_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3, 4, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.meetings_table.setStyleSheet(
            "QTableWidget{background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;gridline-color:#eef1f6;}"
            "QHeaderView::section{background:#f1f5f9;border:none;padding:8px;font-weight:700;color:#475569;}"
            "QTableWidget::item{padding:8px 6px;}"
            "QTableWidget::item:selected{background:#2563eb;color:#ffffff;}"
        )
        # Open a meeting's detail in its own window on click.
        self.meetings_table.cellClicked.connect(self._open_meeting_detail)
        v.addWidget(self.meetings_table, 1)

        self.meetings_count = QLabel("Click a meeting to open its details.")
        self.meetings_count.setStyleSheet("color:#64748b; font-size:12px;")
        v.addWidget(self.meetings_count)
        self._refresh_meetings()
        return page

    def _on_tab_changed(self, index: int) -> None:
        text = self.tabs.tabText(index).strip()
        if text.endswith("Summary"):
            self._refresh_meetings()
        # Leaving Configuration -> warm up the configured models so there's no
        # cold-start download when the user hits Start.
        if getattr(self, "_prev_tab_text", "").endswith("Configuration") and not text.endswith("Configuration"):
            self._maybe_prewarm()
        self._prev_tab_text = text

    # ----- meetings table (Summary tab) -----
    def _populate_scope_combo(self) -> None:
        """Fill the Summary 'Show:' selector with Personal + each joined team."""
        if not hasattr(self, "scope_combo"):
            return
        prev = self.scope_combo.currentData()
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        try:
            memberships = self.store.list_memberships()
            revoked = {k.get("key_id") for k in self.store.list_team_keys() if k.get("revoked")}
        except Exception:
            memberships, revoked = [], set()
        if memberships:
            self.scope_combo.addItem("All (personal + teams)", ("all", None))
        self.scope_combo.addItem("Personal (this device)", ("personal", None))
        for m in memberships:
            name = m.get("team_name") or m.get("team_id")
            ro = m.get("key_id") in revoked or (m.get("team_id") == self.team_id and self._team_readonly)
            label = f"Team · {name}" + ("  (read-only)" if ro else "")
            self.scope_combo.addItem(label, ("team", m.get("team_id")))
        # Restore previous selection, else default to the active team if joined.
        idx = self.scope_combo.findData(prev) if prev else -1
        if idx < 0 and self.team_id:
            idx = self.scope_combo.findData(("team", self.team_id))
        self.scope_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.scope_combo.blockSignals(False)

    def _team_name(self, team_id) -> str:
        if not team_id:
            return "Personal"
        try:
            for m in self.store.list_memberships():
                if m.get("team_id") == team_id:
                    return m.get("team_name") or team_id
        except Exception:
            pass
        return team_id

    def _collect_rows(self, kind: str, feed_team_id, query: str):
        """Gather meeting rows for the chosen scope.

        Each row carries 'source' (('local', None) or ('team', team_id)) and a
        'team_label' for the Team column. Remote rows whose id matches a synced
        local meeting are dropped so nothing shows twice."""
        notes: list[str] = []
        # Local meetings (this device), always available.
        try:
            local = self.store.search_meetings(query)
        except Exception as exc:
            return None, f"⚠ {exc}"
        local_rows = [{"id": m.id, "title": m.title, "user": m.user,
                       "started_at": m.started_at, "created_at": m.created_at,
                       "summary_md": m.summary_md, "team_id": m.team_id,
                       "source": ("local", None), "team_label": self._team_name(m.team_id)}
                      for m in local]
        local_gids = {self._gid(r["id"]) for r in local_rows}

        def team_rows(tid):
            rows, note = self._fetch_team_meetings(query, tid)
            if rows is None:
                if note:
                    notes.append(f"{self._team_name(tid)} — {note.lstrip('⚠ ')}")
                return []
            out = []
            for r in rows:
                if r.get("id") in local_gids:
                    continue  # already shown as the local copy
                r = dict(r)
                r["source"] = ("team", tid)
                r["team_label"] = self._team_name(tid)
                out.append(r)
            return out

        if kind == "personal":
            rows = local_rows
        elif kind == "team":
            rows = [r for r in local_rows if r.get("team_id") == feed_team_id] + team_rows(feed_team_id)
        else:  # "all" — personal + every joined team
            rows = list(local_rows)
            try:
                for m in self.store.list_memberships():
                    rows += team_rows(m.get("team_id"))
            except Exception:
                pass
        return rows, (" · ".join(notes) if notes else None)

    def _refresh_meetings(self) -> None:
        if not hasattr(self, "meetings_table"):
            return
        query = (self.search_edit.text() if hasattr(self, "search_edit") else "").strip().lower()
        scope = self.scope_combo.currentData() if hasattr(self, "scope_combo") else ("personal", None)
        kind, feed_team_id = scope if scope else ("personal", None)
        self._team_feed = kind in ("team", "all")
        self._feed_team_id = feed_team_id if kind == "team" else None

        rows, note = self._collect_rows(kind, feed_team_id, query)
        if rows is None:
            self.meetings_table.setRowCount(0)
            self.meetings_count.setText(note)
            return

        self.meetings_table.setSortingEnabled(False)
        self.meetings_table.setRowCount(0)
        for m in rows:
            r = self.meetings_table.rowCount()
            self.meetings_table.insertRow(r)
            when = (m.get("started_at") or m.get("created_at") or "")[:16].replace("T", " ")
            source = m.get("source") or ("local", None)
            title_item = QTableWidgetItem(m.get("title") or "Meeting")
            title_item.setData(Qt.ItemDataRole.UserRole, m.get("id"))
            title_item.setData(Qt.ItemDataRole.UserRole + 1, source)
            self.meetings_table.setItem(r, 0, title_item)
            self.meetings_table.setItem(r, 1, QTableWidgetItem(m.get("team_label") or "Personal"))
            self.meetings_table.setItem(r, 2, QTableWidgetItem(when))
            self.meetings_table.setItem(r, 3, QTableWidgetItem(m.get("user") or ""))
            self.meetings_table.setItem(r, 4, QTableWidgetItem("✦ yes" if m.get("summary_md") else "—"))
            status = self._meeting_status(m.get("id")) if source[0] == "local" else ""
            self.meetings_table.setItem(r, 5, QTableWidgetItem(status))
        self.meetings_table.setSortingEnabled(True)
        self.meetings_table.sortItems(2, Qt.SortOrder.DescendingOrder)  # latest meeting on top
        scope_label = {"personal": "personal", "all": "personal + team"}.get(
            kind, f"team “{self._team_name(feed_team_id)}”")
        prefix = (note + " · ") if note else ""
        self.meetings_count.setText(
            prefix + f"{len(rows)} {scope_label} meeting(s)"
            + (f" matching “{query}”" if query else "") + " · click a row to open")

    def _meeting_status(self, meeting_id) -> str:
        """Per-meeting enrichment status for the Summary table."""
        if meeting_id is None:
            return ""
        try:
            jobs = self.store.jobs_for(meeting_id)
        except Exception:
            return ""
        in_flight = any(mid == meeting_id for mid, _ in self._processing)
        if any(v == "pending" for v in jobs.values()) or in_flight:
            stages = {s for s, v in jobs.items() if v == "pending"}
            if "literature" in stages:
                return "⏳ literature…"
            if "summary" in stages:
                return "⏳ summarizing…"
            return "⏳ processing…"
        if not jobs:
            return ""  # not tracked (e.g. an older meeting) - don't claim "done"
        return "✓ done"

    def _feed_external_cfg(self, team_id):
        """Resolve the shared-DB config to read a team's meetings from. Uses that
        team's bundled key so you can view any joined team, not just the active one."""
        if team_id and team_id != self.team_id:
            from . import team
            m = self.store.get_membership(team_id)
            if m and m.get("key"):
                try:
                    return team.parse_team_key(m["key"])["external"]
                except Exception:
                    pass
        return self._current_external_cfg()

    def _fetch_team_meetings(self, query: str, team_id=None):
        """Return (rows, note). rows=None means the shared DB isn't available.

        Prefers the relational shared DB (richest). If only a graph database is
        configured for the team, read the meeting list from it over SPARQL."""
        team_id = team_id if team_id is not None else self.team_id
        ext = self._feed_external_cfg(team_id)
        self._feed_cfg = ext
        rel = ext.relational
        from .external import GraphSink, structured_sink
        if rel.enabled and rel.url:
            self._team_feed_source = "relational"
            try:
                rows = structured_sink(rel).list_meetings(team_id=team_id or None)
            except Exception as exc:
                return None, f"⚠ Shared DB: {exc}"
        elif ext.graph.enabled and ext.graph.query_url:
            self._team_feed_source = "graph"
            try:
                rows = GraphSink(ext.graph).list_meetings(team_id=team_id or None)
            except Exception as exc:
                qurl = ext.graph.query_url
                if "refused" in str(exc).lower() or "urlopen" in str(exc).lower():
                    return None, (f"⚠ Can't reach the shared graph database at {qurl} — check the "
                                  "server is running and the URL/port is correct (try Test connection "
                                  "in Configuration). [" + str(exc) + "]")
                return None, f"⚠ Shared graph DB ({qurl}): {exc}"
        else:
            return None, ("Enable a relational or graph shared database (with a query endpoint) "
                          "in Configuration to see team meetings.")
        if query:
            rows = [r for r in rows if query in (r.get("title") or "").lower()
                    or query in (r.get("summary_md") or "").lower()]
        return rows, None

    def _open_meeting_detail(self, row: int, _col: int = 0) -> None:
        cell = self.meetings_table.item(row, 0)
        mid = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if mid is None:
            return
        source = (cell.data(Qt.ItemDataRole.UserRole + 1) or ("local", None))
        if source[0] == "team":
            ext = self._feed_external_cfg(source[1])
            try:
                from .external import GraphSink, structured_sink
                if ext.relational.enabled and ext.relational.url:
                    rec = structured_sink(ext.relational).get_meeting(mid)
                elif ext.graph.enabled and ext.graph.query_url:
                    rec = GraphSink(ext.graph).get_meeting(mid)
                else:
                    rec = None
            except Exception as exc:
                QMessageBox.warning(self, "Shared DB", f"Could not load meeting: {exc}")
                return
            if rec:
                MeetingDetailDialog(self, rec, remote=True).exec()
            else:
                QMessageBox.information(self, "Shared DB", "Could not load this meeting.")
            return
        rec = self.store.get_meeting(mid)
        if not rec:
            QMessageBox.information(self, "Not found", "Meeting not found.")
            return
        dlg = MeetingDetailDialog(self, rec)
        self._open_details[mid] = dlg          # register for live refresh while enriching
        try:
            dlg.exec()
        finally:
            self._open_details.pop(mid, None)

    def _refresh_open_detail(self, meeting_id) -> None:
        dlg = self._open_details.get(meeting_id)
        if dlg is not None:
            dlg.reload()

    def _bulk_send(self) -> None:
        """Bulk send/sync the meetings currently shown in the Summary table."""
        try:
            query = self.search_edit.text() if hasattr(self, "search_edit") else ""
            metas = (self.store.search_meetings(query) if query.strip()
                     else self.store.list_meetings(user=self.user or None, limit=5000))
            ids = [m.id for m in metas]
        except Exception:
            ids = []
        if not ids:
            QMessageBox.information(self, "Nothing to send", "No meetings to send yet.")
            return
        self._open_send_dialog(ids, f"Send / sync {len(ids)} meeting(s)")

    def _export_graph(self) -> None:
        """Export every meeting as one connected RDF knowledge graph."""
        from . import kg

        try:
            metas = self.store.list_meetings(user=self.user or None, limit=5000)
            records = [r for r in (self.store.get_meeting(m.id) for m in metas) if r]
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", f"Could not read meetings: {exc}")
            return
        if not records:
            QMessageBox.information(self, "Nothing to export", "No meetings recorded yet.")
            return
        path, selected = QFileDialog.getSaveFileName(
            self, "Export knowledge graph",
            f"meetgraph-knowledge-graph-{datetime.now():%Y%m%d}.jsonld",
            "JSON-LD (*.jsonld);;Turtle (*.ttl);;N-Quads (*.nq)",
        )
        if not path:
            return
        if path.endswith(".ttl"):
            fmt = "turtle"
        elif path.endswith(".nq"):
            fmt = "nquads"
        elif path.endswith((".jsonld", ".json")):
            fmt = "jsonld"
        else:
            fmt = {"Turtle (*.ttl)": "turtle", "N-Quads (*.nq)": "nquads"}.get(selected, "jsonld")
            path += kg.EXTENSIONS[fmt]
        try:
            data = kg.serialize_corpus(records, fmt=fmt)
            with open(path, "wb") as f:
                f.write(data)
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", f"Could not build graph: {exc}")
            return
        reveal_in_file_manager(path)

    def _build_config_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ConfigPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(2, 10, 2, 2)
        v.setSpacing(12)
        v.addWidget(self._build_ai_section())
        v.addWidget(self._build_engine_box())
        v.addWidget(self._build_sources_box())
        v.addWidget(self._build_external_box())
        v.addWidget(self._build_team_box())
        v.addWidget(self._build_email_box())
        v.addWidget(self._build_integrations_box())
        v.addWidget(self._build_pubmed_box())
        v.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        scroll.viewport().setStyleSheet("background: transparent;")
        return scroll

    def _build_about_tab(self) -> QWidget:
        view = QTextBrowser()
        view.setObjectName("transcript")
        view.setOpenExternalLinks(True)
        view.setHtml(self._about_html())
        return view

    def _about_html(self) -> str:
        return """
<style>
  body { font-family: -apple-system, 'Segoe UI', sans-serif; color:#1e293b; font-size:14px; line-height:1.55; }
  h1 { font-size:22px; margin:0 0 2px 0; }
  h2 { font-size:15px; color:#7c3aed; margin:22px 0 6px 0; }
  .tag { color:#64748b; font-size:13px; margin:0 0 4px 0; }
  ol, ul { margin:4px 0 4px 0; padding-left:22px; }
  li { margin:4px 0; }
  code { background:#f1f5f9; padding:1px 5px; border-radius:4px; font-size:12px; }
  .card { background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:12px 16px; margin-top:14px; }
  a { color:#2563eb; text-decoration:none; }
</style>

<h1>MeetGraph</h1>
<p class="tag">Turning meetings into a knowledge graph.</p>
<p>MeetGraph transcribes a meeting on your machine, writes faithful structured
notes with AI, and links the result into a queryable knowledge graph — with
provenance, team sharing, and optional links to prior meetings and scientific
literature.</p>

<h2>Getting started in 4 steps</h2>
<ol>
  <li><b>Configure once.</b> Open the <b>⚙ Configuration</b> tab. Pick a
      <b>Transcription engine</b> (local Whisper runs fully offline; OpenAI / any
      OpenAI-compatible endpoint needs an API key + base URL). Under <b>AI notes</b>,
      choose a provider and paste its API key. Use the <b>Test</b> buttons to confirm
      both work.</li>
  <li><b>Start a meeting.</b> Go to <b>◉ Meeting</b> and click
      <b>● Start meeting</b>. The banner at the top shows which models are in use and
      whether the API keys are set. Speak, or play the call audio.</li>
  <li><b>Watch it transcribe & summarize.</b> The <b>Live transcript</b> fills in on
      the left with on-device speaker labels (Speaker 1 / 2 / …). The
      <b>Live summary</b> on the right refreshes automatically (toggle <b>Auto</b>).
      Click <b>■ Stop</b> when done — a final summary is generated and saved.</li>
  <li><b>Review & share.</b> Open the <b>✦ Summary</b> tab to browse every saved
      meeting. Click one to read the notes + transcript, rename or edit it, find
      related papers, export RDF, or send it by email / REST / MCP.</li>
</ol>

<h2>What you get in the notes</h2>
<ul>
  <li><b>Key points, decisions, open questions and action items</b> — faithful to
      what was actually said (transcription errors are quietly corrected).</li>
  <li><b>Key terms</b> auto-linked to Wikipedia &amp; Wikidata.</li>
  <li><b>Related meetings</b> — an agent connects this meeting to earlier ones; click
      a link to open it.</li>
  <li><b>Scientific literature</b> (optional) — for research meetings, relevant
      PubMed papers (PMID/DOI) and research gaps, when PubMed is enabled.</li>
  <li><b>Provenance</b> — which transcription and notes models produced the result,
      recorded in the notes and in the knowledge graph.</li>
</ul>

<h2>Speakers &amp; the summary</h2>
<p>Speaker labels (Speaker 1, Speaker 2, …) appear in the <b>live transcript</b> only.
The <b>summary</b> describes <i>what was said</i>, not a per-person breakdown — it lists
participants by name only when a name is actually spoken.</p>

<h2>Teams &amp; storage</h2>
<ul>
  <li><b>Local first.</b> Everything is saved to a local database. Content and your
      API keys/secrets are kept in separate files.</li>
  <li><b>External databases.</b> Optionally mirror meetings to a relational DB
      (PostgreSQL / MySQL / MongoDB) and a graph DB (Oxigraph / GraphDB / Fuseki / …).
      MeetGraph derives the right endpoints from a base URL and auto-syncs changes.</li>
  <li><b>Teams.</b> Generate a team key so teammates write to one shared database;
      access is by key + name + email, with an activity log of who did what.</li>
</ul>

<h2>Privacy</h2>
<p>Local transcription and speaker labeling run entirely on your device. Audio is sent
to a cloud service only if you choose a cloud transcription or notes provider. API keys
are stored locally in a protected config file.</p>

<div class="card">
  <b>Developer</b><br>
  Tek Raj Chhetri &nbsp;·&nbsp; <a href="mailto:tekraj@mit.edu">tekraj@mit.edu</a>
</div>
"""

    def _build_engine_box(self) -> QGroupBox:
        engine_box = QGroupBox("Transcription engine")
        engine_layout = QVBoxLayout(engine_box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Engine:"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Local — Whisper (faster-whisper / Apple MLX)", "local")
        self.engine_combo.addItem("OpenAI API", "openai")
        self.engine_combo.addItem("OpenAI-compatible — Groq, local server, custom…", "compatible")
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        row.addWidget(self.engine_combo)
        row.addWidget(QLabel("Language:"))
        self.lang_edit = QLineEdit()
        self.lang_edit.setPlaceholderText("auto (e.g. en, es, fr)")
        self.lang_edit.setMaximumWidth(140)
        row.addWidget(self.lang_edit)
        row.addWidget(QLabel("Speakers:"))
        self.diarize_combo = QComboBox()
        self.diarize_combo.addItem("Label speakers (local)", "local")
        self.diarize_combo.addItem("Off (by source)", "off")
        self.diarize_combo.setToolTip(
            "Label distinct speakers (Speaker 1/2/…) on-device. Works out of the box with "
            "Resemblyzer (pip install resemblyzer — no token); pyannote.audio is an alternative. "
            "Cloud APIs (OpenAI) don't return speaker labels. Falls back to audio-source labels "
            "if no backend is installed.")
        row.addWidget(self.diarize_combo)
        row.addStretch()
        engine_layout.addLayout(row)

        self.engine_stack = QStackedWidget()

        local_w = QWidget()
        local_l = QHBoxLayout(local_w)
        local_l.setContentsMargins(0, 0, 0, 0)
        local_l.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)  # type any HuggingFace CTranslate2 Whisper id
        self.model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model_combo.addItems([
            "tiny", "base", "small", "medium", "large-v3",
            "deepdml/faster-whisper-large-v3-turbo-ct2",
        ])
        self.model_combo.setCurrentText("base")
        self.model_combo.setMinimumWidth(240)
        self.model_combo.setToolTip("Preset size or any HuggingFace CTranslate2 Whisper repo id")
        local_l.addWidget(self.model_combo, 1)
        local_l.addWidget(QLabel("Compute:"))
        self.compute_combo = QComboBox()
        self._populate_compute_combo()
        self.compute_combo.currentIndexChanged.connect(self._update_compute_label)
        local_l.addWidget(self.compute_combo)
        self._compute_label = QLabel("")
        self._compute_label.setStyleSheet("color:#64748b;")
        local_l.addWidget(self._compute_label)
        self.engine_stack.addWidget(local_w)

        openai_w = QWidget()
        openai_l = QHBoxLayout(openai_w)
        openai_l.setContentsMargins(0, 0, 0, 0)
        openai_l.addWidget(QLabel("API key (required):"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-…  (or set OPENAI_API_KEY)")
        self.api_key_edit.setText(os.environ.get("OPENAI_API_KEY", ""))
        openai_l.addWidget(self.api_key_edit)
        openai_l.addWidget(QLabel("Model:"))
        self.openai_model_combo = QComboBox()
        self.openai_model_combo.setEditable(True)  # type any model id
        self.openai_model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.openai_model_combo.addItems(
            ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"]
        )
        self.openai_model_combo.setToolTip("Pick or type any OpenAI transcription model id")
        self.openai_model_combo.setMinimumWidth(180)
        openai_l.addWidget(self.openai_model_combo)
        openai_l.addWidget(QLabel("Base URL:"))
        self.openai_base = QLineEdit()
        self.openai_base.setPlaceholderText("optional — default https://api.openai.com/v1 (Azure/proxy ok)")
        openai_l.addWidget(self.openai_base, 1)
        self.engine_stack.addWidget(openai_w)

        # OpenAI-compatible (Groq, OpenRouter, Anthropic, self-hosted, custom...)
        compat_w = QWidget()
        compat_l = QHBoxLayout(compat_w)
        compat_l.setContentsMargins(0, 0, 0, 0)
        compat_l.addWidget(QLabel("Provider:"))
        self.compat_provider = QComboBox()
        for key, (label, _url, _model) in COMPAT_PROVIDERS.items():
            self.compat_provider.addItem(label, key)
        self.compat_provider.currentIndexChanged.connect(self._on_compat_provider_changed)
        compat_l.addWidget(self.compat_provider)
        compat_l.addWidget(QLabel("Base URL:"))
        self.compat_base = QLineEdit()
        self.compat_base.setPlaceholderText("https://api.groq.com/openai/v1")
        compat_l.addWidget(self.compat_base, 1)
        compat_l.addWidget(QLabel("Key:"))
        self.compat_key = QLineEdit()
        self.compat_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.compat_key.setPlaceholderText("API key (blank for local servers)")
        compat_l.addWidget(self.compat_key, 1)
        compat_l.addWidget(QLabel("Model:"))
        self.compat_model = QComboBox()
        self.compat_model.setEditable(True)
        self.compat_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.compat_model.addItems(["whisper-large-v3", "whisper-large-v3-turbo", "distil-whisper-large-v3-en"])
        self.compat_model.setMinimumWidth(180)
        compat_l.addWidget(self.compat_model, 1)
        self.engine_stack.addWidget(compat_w)

        engine_layout.addWidget(self.engine_stack)

        engine_hint = QLabel(
            "Transcription (audio → text) runs on Local Whisper, OpenAI, or any "
            "OpenAI-compatible audio endpoint. Pick a provider above and MeetGraph "
            "calls its /audio/transcriptions API — so if Anthropic, OpenRouter, or "
            "another provider adds speech-to-text later, just select it here and enter "
            "your key; it works with no update. (Your notes provider is configured "
            "separately above.)"
        )
        engine_hint.setWordWrap(True)
        engine_hint.setStyleSheet("color:#64748b; font-size:11px;")
        engine_layout.addWidget(engine_hint)

        # HuggingFace token - optional; only used to download local Whisper models
        # faster / past anonymous rate limits.
        hf_row = QHBoxLayout()
        hf_row.addWidget(QLabel("HuggingFace token (optional):"))
        self.hf_token_edit = QLineEdit()
        self.hf_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.hf_token_edit.setPlaceholderText("hf_…  — speeds up local-model downloads (not required)")
        self.hf_token_edit.setText(os.environ.get("HF_TOKEN", os.environ.get("HUGGING_FACE_HUB_TOKEN", "")))
        hf_row.addWidget(self.hf_token_edit, 1)
        engine_layout.addLayout(hf_row)

        test_row = QHBoxLayout()
        test_btn = QPushButton("Test transcription")
        test_btn.setToolTip("Check the selected engine + model works (local models download on first run).")
        test_btn.clicked.connect(self._test_transcription)
        test_row.addWidget(test_btn)
        self.engine_test_status = QLabel("")
        self.engine_test_status.setStyleSheet("color:#64748b; font-size:11px;")
        test_row.addWidget(self.engine_test_status, 1)
        engine_layout.addLayout(test_row)

        self.engine_using_label = QLabel("")
        self.engine_using_label.setStyleSheet("color:#334155; font-size:11px; font-weight:600;")
        engine_layout.addWidget(self.engine_using_label)

        self._update_compute_label()
        return engine_box

    def _populate_compute_combo(self) -> None:
        from .transcribe import hardware_caps

        caps = hardware_caps()
        # (label, data, enabled, tooltip)
        items = [
            ("Auto", "auto", True, "Pick the best available device automatically"),
            ("CPU", "cpu", True, "Run on CPU"),
            ("GPU (NVIDIA CUDA)", "cuda", caps["cuda"],
             "Run on NVIDIA GPU" if caps["cuda"] else "No NVIDIA CUDA GPU detected"),
        ]
        if caps["apple"]:
            items.append((
                "GPU (Apple Silicon)", "mlx", caps["mlx"],
                "Run on the Apple GPU via MLX" if caps["mlx"]
                else "Install mlx-whisper to enable Apple-GPU transcription",
            ))
        self.compute_combo.clear()
        for label, data, enabled, tip in items:
            self.compute_combo.addItem(label, data)
            item = self.compute_combo.model().item(self.compute_combo.count() - 1)
            item.setEnabled(enabled)
            item.setToolTip(tip)

    def _update_compute_label(self) -> None:
        from .transcribe import compute_label

        choice = self.compute_combo.currentData()
        if choice == "auto":
            self._compute_label.setText(f"· auto → {compute_label('auto')}")
        else:
            self._compute_label.setText(f"· {compute_label(choice)}")

    def _build_sources_box(self) -> QGroupBox:
        src_box = QGroupBox("Audio sources")
        src_layout = QVBoxLayout(src_box)

        mic_row = QHBoxLayout()
        self.mic_check = QCheckBox(f"Microphone ({self.speaker_self})")
        self.mic_check.setChecked(True)
        mic_row.addWidget(self.mic_check)
        self.mic_combo = QComboBox()
        mic_row.addWidget(self.mic_combo, 1)
        src_layout.addLayout(mic_row)

        sys_row = QHBoxLayout()
        self.sys_check = QCheckBox("Meeting / system audio")
        self.sys_check.setChecked(True)
        sys_row.addWidget(self.sys_check)
        self.sys_combo = QComboBox()
        sys_row.addWidget(self.sys_combo, 1)
        src_layout.addLayout(sys_row)

        refresh_row = QHBoxLayout()
        refresh_btn = QPushButton("↻ Refresh devices")
        refresh_btn.clicked.connect(self._populate_devices)
        refresh_row.addWidget(refresh_btn)
        self.bh_hint = QLabel()
        self.bh_hint.setStyleSheet("color: #b45309;")
        refresh_row.addWidget(self.bh_hint, 1)
        src_layout.addLayout(refresh_row)
        return src_box

    def _build_external_box(self) -> QGroupBox:
        box = QGroupBox("External databases — optionally mirror meetings to your own DB (all fields optional)")
        outer = QVBoxLayout(box)
        outer.setSpacing(10)
        _HINT = "color:#64748b; font-size:11px;"

        # --- Storage mode ---
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Store meetings:"))
        self.storage_mode = QComboBox()
        self.storage_mode.addItem("Local + Remote", "local_remote")
        self.storage_mode.addItem("Remote only", "remote_only")
        self.storage_mode.addItem("Local only", "local_only")
        self.storage_mode.setToolTip(
            "Local + Remote: keep on this machine and mirror to your database.\n"
            "Remote only: after a successful sync, the local copy is removed (your DB is the system of record).\n"
            "Local only: keep on this machine; never auto-sync to a database.")
        mode_row.addWidget(self.storage_mode)
        mode_row.addSpacing(16)
        mode_row.addWidget(QLabel("Sync:"))
        self.sync_policy = QComboBox()
        self.sync_policy.addItem("Mirror all (incl. deletions)", "mirror")
        self.sync_policy.addItem("Add & update only", "add_only")
        self.sync_policy.setToolTip("Mirror all: additions, updates, and deletions propagate to the "
                                    "database.\nAdd & update only: never delete from the database.")
        mode_row.addWidget(self.sync_policy)
        mode_row.addStretch()
        outer.addLayout(mode_row)
        mode_hint = QLabel("Choose where your meetings live, and share accordingly. "
                           "“Remote only” needs a configured + enabled database below.")
        mode_hint.setStyleSheet(_HINT)
        mode_hint.setWordWrap(True)
        outer.addWidget(mode_hint)

        # --- Relational / document DB ---
        self.ext_rel_enable = QCheckBox("Structured database (SQL: PostgreSQL/MySQL/SQLite — or MongoDB)")
        outer.addWidget(self.ext_rel_enable)
        rel_form = QFormLayout()
        rel_form.setContentsMargins(22, 0, 0, 0)
        self.ext_rel_kind = QComboBox()
        self.ext_rel_kind.addItem("SQL (SQLAlchemy)", "sql")
        self.ext_rel_kind.addItem("MongoDB", "mongodb")
        self.ext_rel_kind.currentIndexChanged.connect(self._on_rel_kind_changed)
        rel_form.addRow("Database kind", self.ext_rel_kind)
        self.ext_rel_url = QLineEdit()
        self.ext_rel_url.setPlaceholderText("postgresql+psycopg://host:5432/dbname  (credentials optional below)")
        rel_form.addRow("Connection URL", self.ext_rel_url)
        self.ext_rel_db = QLineEdit()
        self.ext_rel_db.setPlaceholderText("MongoDB database name (default: meetgraph)")
        self.ext_rel_db_row = self.ext_rel_db  # kept for show/hide
        rel_form.addRow("Database name", self.ext_rel_db)
        self.ext_rel_user = QLineEdit()
        self.ext_rel_user.setPlaceholderText("optional — or embed in the URL")
        rel_form.addRow("Username", self.ext_rel_user)
        self.ext_rel_pass = QLineEdit()
        self.ext_rel_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ext_rel_pass.setPlaceholderText("optional — password or access token")
        rel_form.addRow("Password / token", self.ext_rel_pass)
        rel_hint = QLabel("SQL needs SQLAlchemy + a driver (psycopg2-binary, pymysql). MongoDB needs "
                          "pymongo (works with free MongoDB Atlas: mongodb+srv://… — or a local server). "
                          "Writes a meetgraph_meetings table / meetings collection.")
        rel_hint.setStyleSheet(_HINT)
        rel_hint.setWordWrap(True)
        rel_form.addRow("", rel_hint)
        rel_btn_row = QHBoxLayout()
        rel_test = QPushButton("Test connection")
        rel_test.clicked.connect(self._test_relational)
        rel_btn_row.addWidget(rel_test)
        self.ext_rel_status = QLabel("")
        self.ext_rel_status.setStyleSheet(_HINT)
        rel_btn_row.addWidget(self.ext_rel_status, 1)
        rel_form.addRow("", self._wrap(rel_btn_row))
        outer.addLayout(rel_form)

        # --- Graph ---
        from .external import GRAPH_DB_TYPES

        self.ext_graph_enable = QCheckBox("Graph database / triplestore (SPARQL — Oxigraph, Fuseki, GraphDB…)")
        outer.addWidget(self.ext_graph_enable)
        g_form = QFormLayout()
        g_form.setContentsMargins(22, 0, 0, 0)
        # Smart endpoint setup: pick a type + base URL, endpoints are derived.
        type_row = QHBoxLayout()
        self.ext_graph_type = QComboBox()
        for key, label, _needs in GRAPH_DB_TYPES:
            self.ext_graph_type.addItem(label, key)
        self.ext_graph_type.currentIndexChanged.connect(self._fill_graph_endpoints)
        type_row.addWidget(self.ext_graph_type)
        self.ext_graph_base = QLineEdit()
        self.ext_graph_base.setPlaceholderText("Base URL, e.g. http://localhost:7878")
        self.ext_graph_base.editingFinished.connect(self._fill_graph_endpoints)
        type_row.addWidget(self.ext_graph_base, 1)
        g_form.addRow("DB type / base URL", self._wrap(type_row))
        self.ext_graph_dataset = QLineEdit()
        self.ext_graph_dataset.setPlaceholderText("repository / dataset / namespace (for Fuseki, GraphDB, …)")
        self.ext_graph_dataset.editingFinished.connect(self._fill_graph_endpoints)
        g_form.addRow("Repository / dataset", self.ext_graph_dataset)
        self.ext_graph_store = QLineEdit()
        self.ext_graph_store.setPlaceholderText("http://localhost:7878/store   (Graph Store endpoint — include the path, e.g. /store)")
        g_form.addRow("Graph Store URL", self.ext_graph_store)
        self.ext_graph_update = QLineEdit()
        self.ext_graph_update.setPlaceholderText("http://localhost:7878/update   (SPARQL Update — preferred)")
        g_form.addRow("Update URL", self.ext_graph_update)
        self.ext_graph_query = QLineEdit()
        self.ext_graph_query.setPlaceholderText("http://localhost:7878/query   (used to test the connection)")
        g_form.addRow("Query URL", self.ext_graph_query)
        from .kg import MEETGRAPH_NG
        self.ext_graph_name = QLineEdit(MEETGRAPH_NG)
        self.ext_graph_name.setPlaceholderText(MEETGRAPH_NG)
        self.ext_graph_name.setToolTip("All meetings are stored in this single named graph (the 'meetgraph' graph).")
        g_form.addRow("Named graph", self.ext_graph_name)
        self.ext_graph_user = QLineEdit()
        self.ext_graph_user.setPlaceholderText("optional")
        g_form.addRow("Username", self.ext_graph_user)
        self.ext_graph_pass = QLineEdit()
        self.ext_graph_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ext_graph_pass.setPlaceholderText("optional")
        g_form.addRow("Password", self.ext_graph_pass)
        g_hint = QLabel("All meetings are written to one named graph (above), each replaced cleanly "
                        "on re-sync, with key terms linked to Wikipedia/Wikidata. If an Update URL "
                        "is set it's used (most reliable); otherwise the Graph Store URL must point "
                        "at the store endpoint (e.g. Oxigraph's /store), not the server root.")
        g_hint.setStyleSheet(_HINT)
        g_hint.setWordWrap(True)
        g_form.addRow("", g_hint)
        g_btn_row = QHBoxLayout()
        g_test = QPushButton("Test connection")
        g_test.clicked.connect(self._test_graph)
        g_btn_row.addWidget(g_test)
        self.ext_graph_status = QLabel("")
        self.ext_graph_status.setStyleSheet(_HINT)
        g_btn_row.addWidget(self.ext_graph_status, 1)
        g_form.addRow("", self._wrap(g_btn_row))
        outer.addLayout(g_form)

        # --- Sync all ---
        sync_row = QHBoxLayout()
        sync_btn = QPushButton("⇪ Sync all meetings now")
        sync_btn.clicked.connect(self._sync_all_external)
        sync_row.addWidget(sync_btn)
        self.ext_sync_status = QLabel("Enabled databases also receive new meetings automatically.")
        self.ext_sync_status.setStyleSheet(_HINT)
        self.ext_sync_status.setWordWrap(True)
        sync_row.addWidget(self.ext_sync_status, 1)
        outer.addLayout(sync_row)
        return box

    def _build_team_box(self) -> QGroupBox:
        box = QGroupBox("Team — share one key so the whole team's notes land in one centralized database")
        outer = QVBoxLayout(box)
        outer.setSpacing(8)
        _HINT = "color:#64748b; font-size:11px;"

        form = QFormLayout()
        self.member_name_edit = QLineEdit(self._display_name if self._display_name != "Local" else "")
        self.member_name_edit.setPlaceholderText("Your name (shown in the activity log)")
        form.addRow("Your name", self.member_name_edit)
        self.member_email_edit = QLineEdit(self.user_email)
        self.member_email_edit.setPlaceholderText("you@example.com — identifies who did what")
        form.addRow("Your email", self.member_email_edit)
        self.team_name_edit = QLineEdit(self.team_name)
        self.team_name_edit.setPlaceholderText("e.g. Acme Research")
        form.addRow("Team name", self.team_name_edit)
        for w in (self.member_name_edit, self.member_email_edit, self.team_name_edit):
            w.editingFinished.connect(self._persist_identity)
        outer.addLayout(form)

        self.team_status = QLabel()
        self.team_status.setWordWrap(True)
        self.team_status.setStyleSheet(_HINT)
        outer.addWidget(self.team_status)

        btns = QHBoxLayout()
        gen = QPushButton("Generate team key…")
        gen.setToolTip("Bundle your enabled external database(s) into a shareable key for teammates.")
        gen.clicked.connect(self._generate_team_key)
        btns.addWidget(gen)
        join = QPushButton("Join team (paste key)…")
        join.clicked.connect(self._join_team)
        btns.addWidget(join)
        manage = QPushButton("Manage keys…")
        manage.setToolTip("View the team keys you've generated; copy or revoke them.")
        manage.clicked.connect(lambda: TeamKeysDialog(self).exec())
        btns.addWidget(manage)
        self.teams_btn = QPushButton("Teams…")
        self.teams_btn.setToolTip("Switch between the teams you've joined; revoked ones are read-only.")
        self.teams_btn.clicked.connect(lambda: TeamsDialog(self).exec())
        btns.addWidget(self.teams_btn)
        self.leave_btn = QPushButton("Leave team")
        self.leave_btn.setToolTip("Leave the current team and stop syncing to its shared database.")
        self.leave_btn.clicked.connect(self._leave_team)
        btns.addWidget(self.leave_btn)
        btns.addStretch()
        log_btn = QPushButton("Activity log…")
        log_btn.clicked.connect(self._show_activity_log)
        btns.addWidget(log_btn)
        outer.addLayout(btns)

        hint = QLabel(
            "Anyone with the key joins the same team: their summaries are written to the shared "
            "database (centralized) and the agent links meetings across the team. Every action "
            "(create, summary, delete, sync) is recorded with your name and email. The key carries "
            "DB credentials — share it only with your team."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_HINT)
        outer.addWidget(hint)
        self._update_team_status()
        return box

    def _build_email_box(self) -> QGroupBox:
        box = QGroupBox("Email — send summaries to your team (SMTP)")
        outer = QVBoxLayout(box)
        outer.setSpacing(8)
        form = QFormLayout()
        row1 = QHBoxLayout()
        self.email_host = QLineEdit()
        self.email_host.setPlaceholderText("smtp.gmail.com")
        row1.addWidget(self.email_host, 1)
        row1.addWidget(QLabel("Port:"))
        self.email_port = QLineEdit("587")
        self.email_port.setMaximumWidth(70)
        row1.addWidget(self.email_port)
        row1.addWidget(QLabel("Security:"))
        self.email_security = QComboBox()
        self.email_security.addItem("STARTTLS", "starttls")
        self.email_security.addItem("SSL", "ssl")
        self.email_security.addItem("None", "none")
        row1.addWidget(self.email_security)
        form.addRow("SMTP server", self._wrap(row1))
        self.email_user = QLineEdit()
        self.email_user.setPlaceholderText("username (often your email)")
        form.addRow("Username", self.email_user)
        self.email_pass = QLineEdit()
        self.email_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.email_pass.setPlaceholderText("password or app-specific password")
        form.addRow("Password", self.email_pass)
        self.email_from = QLineEdit()
        self.email_from.setPlaceholderText("from address (defaults to username)")
        form.addRow("From", self.email_from)
        self.email_recipients = QLineEdit()
        self.email_recipients.setPlaceholderText("team@example.com, alice@example.com  (comma-separated)")
        form.addRow("Default recipients", self.email_recipients)
        outer.addLayout(form)

        btn_row = QHBoxLayout()
        test = QPushButton("Send test email")
        test.clicked.connect(self._send_test_email)
        btn_row.addWidget(test)
        fill = QPushButton("Fill from team members")
        fill.setToolTip("Add the email addresses of teammates seen in the activity log.")
        fill.clicked.connect(self._fill_team_recipients)
        btn_row.addWidget(fill)
        self.email_status = QLabel("")
        self.email_status.setStyleSheet("color:#64748b; font-size:11px;")
        btn_row.addWidget(self.email_status, 1)
        outer.addLayout(btn_row)
        return box

    def _build_integrations_box(self) -> QGroupBox:
        box = QGroupBox("Integrations — also send summary + transcript to a REST API or MCP server")
        outer = QVBoxLayout(box)
        outer.setSpacing(8)
        _HINT = "color:#64748b; font-size:11px;"

        # REST
        self.rest_enable = QCheckBox("REST API (HTTP webhook)")
        outer.addWidget(self.rest_enable)
        rform = QFormLayout()
        rform.setContentsMargins(22, 0, 0, 0)
        rrow = QHBoxLayout()
        self.rest_url = QLineEdit()
        self.rest_url.setPlaceholderText("https://api.example.com/meetings")
        rrow.addWidget(self.rest_url, 1)
        rrow.addWidget(QLabel("Method:"))
        self.rest_method = QComboBox()
        self.rest_method.addItems(["POST", "PUT"])
        rrow.addWidget(self.rest_method)
        rform.addRow("Endpoint URL", self._wrap(rrow))
        self.rest_auth = QLineEdit()
        self.rest_auth.setEchoMode(QLineEdit.EchoMode.Password)
        self.rest_auth.setPlaceholderText("Authorization header, e.g. Bearer <token> (optional)")
        rform.addRow("Auth header", self.rest_auth)
        self.rest_headers = QLineEdit()
        self.rest_headers.setPlaceholderText('Extra headers as JSON, e.g. {"X-Team":"acme"} (optional)')
        rform.addRow("Extra headers", self.rest_headers)
        rtest_row = QHBoxLayout()
        rtest = QPushButton("Send test request")
        rtest.clicked.connect(self._test_rest)
        rtest_row.addWidget(rtest)
        self.rest_status = QLabel("")
        self.rest_status.setStyleSheet(_HINT)
        rtest_row.addWidget(self.rest_status, 1)
        rform.addRow("", self._wrap(rtest_row))
        outer.addLayout(rform)

        # MCP
        self.mcp_enable = QCheckBox("MCP server (Model Context Protocol tool)")
        outer.addWidget(self.mcp_enable)
        mform = QFormLayout()
        mform.setContentsMargins(22, 0, 0, 0)
        self.mcp_url = QLineEdit()
        self.mcp_url.setPlaceholderText("https://mcp.example.com/mcp   (streamable HTTP endpoint)")
        mform.addRow("Server URL", self.mcp_url)
        self.mcp_tool = QLineEdit()
        self.mcp_tool.setPlaceholderText("tool name to call, e.g. ingest_meeting")
        mform.addRow("Tool name", self.mcp_tool)
        self.mcp_token = QLineEdit()
        self.mcp_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.mcp_token.setPlaceholderText("bearer token (optional)")
        mform.addRow("Token", self.mcp_token)
        mtest_row = QHBoxLayout()
        mtest = QPushButton("Send test call")
        mtest.clicked.connect(self._test_mcp)
        mtest_row.addWidget(mtest)
        self.mcp_status = QLabel("")
        self.mcp_status.setStyleSheet(_HINT)
        mtest_row.addWidget(self.mcp_status, 1)
        mform.addRow("", self._wrap(mtest_row))
        mhint = QLabel("MCP needs the 'mcp' Python package (pip install mcp). The tool is called with "
                       "title, summary, transcript, meeting_id, and team_id.")
        mhint.setWordWrap(True)
        mhint.setStyleSheet(_HINT)
        mform.addRow("", mhint)
        outer.addLayout(mform)
        return box

    def _build_pubmed_box(self) -> QGroupBox:
        box = QGroupBox("Scientific literature — link the discussion to PubMed publications & gaps")
        outer = QVBoxLayout(box)
        outer.setSpacing(8)
        self.pubmed_enable = QCheckBox("Find relevant PubMed publications and research gaps for scientific meetings")
        outer.addWidget(self.pubmed_enable)
        form = QFormLayout()
        form.setContentsMargins(22, 0, 0, 0)
        self.pubmed_token = QLineEdit()
        self.pubmed_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.pubmed_token.setPlaceholderText("NCBI API key (optional — speeds up / raises rate limit)")
        form.addRow("NCBI API key", self.pubmed_token)
        self.pubmed_max = QLineEdit("8")
        self.pubmed_max.setMaximumWidth(70)
        form.addRow("Max papers", self.pubmed_max)
        outer.addLayout(form)
        hint = QLabel("After a meeting is summarized, MeetGraph searches PubMed using the key terms; "
                      "your AI model judges relevance and proposes research gaps. Get a free key at "
                      "ncbi.nlm.nih.gov/account. Best results with a capable model.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        outer.addWidget(hint)
        return box

    def _current_delivery_cfg(self):
        from .delivery import DeliveryConfig, McpConfig, RestConfig

        return DeliveryConfig(
            rest=RestConfig(
                enabled=self.rest_enable.isChecked(), url=self.rest_url.text().strip(),
                method=self.rest_method.currentText(), auth=self.rest_auth.text(),
                headers=self.rest_headers.text().strip(),
            ),
            mcp=McpConfig(
                enabled=self.mcp_enable.isChecked(), url=self.mcp_url.text().strip(),
                tool=self.mcp_tool.text().strip(), token=self.mcp_token.text(),
            ),
        )

    def _test_rest(self) -> None:
        from .delivery import RestSink

        cfg = self._current_delivery_cfg().rest
        if not cfg.url:
            self.rest_status.setText("⚠ Enter an endpoint URL.")
            return
        self.rest_status.setText("Sending…")
        self._run_async(lambda: RestSink(cfg).test(),
                        lambda m, ok: self.rest_status.setText(("✓ " if ok else "⚠ ") + m))

    def _test_mcp(self) -> None:
        from .delivery import McpSink

        cfg = self._current_delivery_cfg().mcp
        if not cfg.url or not cfg.tool:
            self.mcp_status.setText("⚠ Enter the server URL and tool name.")
            return
        self.mcp_status.setText("Calling…")
        self._run_async(lambda: McpSink(cfg).test(),
                        lambda m, ok: self.mcp_status.setText(("✓ " if ok else "⚠ ") + m))

    def _current_email_cfg(self):
        from .email_send import EmailConfig, parse_recipients

        try:
            port = int(self.email_port.text().strip() or "587")
        except ValueError:
            port = 587
        return EmailConfig(
            host=self.email_host.text().strip(), port=port,
            username=self.email_user.text().strip(), password=self.email_pass.text(),
            from_addr=self.email_from.text().strip(),
            security=self.email_security.currentData() or "starttls",
            recipients=parse_recipients(self.email_recipients.text()),
        )

    def _fill_team_recipients(self) -> None:
        from .email_send import parse_recipients

        existing = parse_recipients(self.email_recipients.text())
        team = self.store.team_emails(self.team_id or None)
        merged = list(dict.fromkeys(existing + team))  # de-dupe, keep order
        self.email_recipients.setText(", ".join(merged))

    def _send_test_email(self) -> None:
        from .email_send import send

        cfg = self._current_email_cfg()
        recips = cfg.recipients or ([cfg.from_addr or cfg.username] if (cfg.from_addr or cfg.username) else [])
        if not cfg.host or not recips:
            self.email_status.setText("⚠ Set the SMTP server and at least one recipient.")
            return
        self.email_status.setText("Sending test…")
        self._run_async(
            lambda: send(cfg, recips, "MeetGraph test email",
                         "This is a test email from MeetGraph. Your SMTP settings work."),
            lambda msg, ok: self.email_status.setText(("✓ " if ok else "⚠ ") + msg),
        )

    def _update_team_status(self) -> None:
        if getattr(self, "team_status", None) is None:
            return
        in_team = bool(self.team_id)
        try:
            n_teams = len(self.store.list_memberships())
        except Exception:
            n_teams = 1 if in_team else 0
        revoked_note = getattr(self, "_revoked_team_name", "")
        if in_team:
            extra = f"  ·  {n_teams} team(s) joined — use “Teams…” to switch." if n_teams > 1 else ""
            self.team_status.setText(
                f"✓ In team “{self.team_name or self.team_id}” — meetings sync to the shared database." + extra)
        elif revoked_note:
            self.team_status.setText(
                f"Your key for “{revoked_note}” was revoked — back to personal mode. You can still "
                "view that team's meetings (read-only) from the Summary “Show” menu.")
            self._revoked_team_name = ""  # show this note once
        else:
            self.team_status.setText("Not in a team. Generate a key to start one, or paste a key to join.")
        # Leave only makes sense when you're actually in a team.
        if getattr(self, "leave_btn", None) is not None:
            self.leave_btn.setVisible(in_team)
        # "Teams..." (switch active team) only matters once you've joined more than one.
        if getattr(self, "teams_btn", None) is not None:
            self.teams_btn.setVisible(n_teams > 1)
        # Keep the Summary 'Show:' selector in step with the teams you belong to.
        self._populate_scope_combo()

    def _fill_graph_endpoints(self) -> None:
        """Derive query/update/store URLs from the chosen DB type + base URL."""
        from .external import GRAPH_DB_TYPES, derive_endpoints

        t = self.ext_graph_type.currentData()
        needs = next((n for k, _l, n in GRAPH_DB_TYPES if k == t), False)
        self.ext_graph_dataset.setEnabled(t == "custom" or needs)
        manual = t == "custom"
        # Derived endpoints are read-only for known types; freely editable for Custom.
        for w in (self.ext_graph_store, self.ext_graph_update, self.ext_graph_query):
            w.setReadOnly(not manual)
        if manual:
            return
        eps = derive_endpoints(t, self.ext_graph_base.text().strip(), self.ext_graph_dataset.text().strip())
        if eps["query"] or eps["update"]:
            self.ext_graph_query.setText(eps["query"])
            self.ext_graph_update.setText(eps["update"])
            self.ext_graph_store.setText(eps["store"])
            self._persist_external()

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 2)
        row.setSpacing(12)

        header_logo = ICON_PATH if ICON_PATH.exists() else LOGO_PATH
        if header_logo.exists():
            logo = QLabel()
            logo.setPixmap(
                QPixmap(str(header_logo)).scaled(
                    QSize(56, 56),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            row.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title = QLabel("MeetGraph")
        title.setObjectName("HeaderTitle")
        subtitle = QLabel("Turning meetings into a knowledge graph")
        subtitle.setObjectName("HeaderSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        row.addLayout(title_col)
        row.addStretch()

        self.proc_label = QLabel("")
        self.proc_label.setStyleSheet("color:#64748b; font-size:11px;")
        self.proc_label.setToolTip("Background enrichment (cross-linking, literature) status")
        row.addWidget(self.proc_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.identity_label = QLabel()
        self.identity_label.setStyleSheet("color:#475569; font-weight:600; font-size:12px;")
        self._update_identity_label()
        row.addWidget(self.identity_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.live_badge = QLabel("Idle")
        self.live_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_badge("idle")
        row.addWidget(self.live_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _set_badge(self, state: str) -> None:
        styles = {
            "recording": ("● Recording", "#fef2f2", "#dc2626", "#fca5a5"),
            "paused": ("❚❚ Paused", "#fffbeb", "#b45309", "#fcd34d"),
            "idle": ("● Idle", "#f1f5f9", "#64748b", "#e2e8f0"),
        }
        text, bg, fg, border = styles.get(state, styles["idle"])
        self.live_badge.setText(text)
        self.live_badge.setStyleSheet(
            f"background:{bg}; color:{fg}; border:1px solid {border};"
            "border-radius:11px; padding:4px 12px; font-weight:700; font-size:12px;"
        )

    def _update_identity_label(self) -> None:
        self.identity_label.setText(f"👤 {self._display_name}")

    def _build_ai_section(self) -> QGroupBox:
        from .agent import PROVIDERS, PROVIDER_LABELS

        self._providers = PROVIDERS
        box = QGroupBox("AI notes provider — configure first · notes auto-generate when you Stop")
        outer = QVBoxLayout(box)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Provider:"))
        self.ai_provider = QComboBox()
        for key in PROVIDERS:
            self.ai_provider.addItem(PROVIDER_LABELS[key], key)
        # Default to open-source/local models (overridden by saved config, if any).
        _default_i = self.ai_provider.findData("opensource")
        if _default_i >= 0:
            self.ai_provider.setCurrentIndex(_default_i)
        self.ai_provider.currentIndexChanged.connect(self._on_ai_provider_changed)
        row1.addWidget(self.ai_provider)
        row1.addWidget(QLabel("Model:"))
        self.ai_model = QComboBox()
        self.ai_model.setEditable(True)  # type to search / enter a custom id
        self.ai_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.ai_model.setMinimumWidth(260)
        comp = self.ai_model.completer()
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        row1.addWidget(self.ai_model, 1)
        self.ai_models_btn = QPushButton("↻")
        self.ai_models_btn.setToolTip("Fetch available models for this provider")
        self.ai_models_btn.setMaximumWidth(42)
        self.ai_models_btn.clicked.connect(self._refresh_models)
        row1.addWidget(self.ai_models_btn)
        self.ai_pull_btn = QPushButton("⤓ Pull")
        self.ai_pull_btn.setToolTip("Download the entered model with `ollama pull`")
        self.ai_pull_btn.clicked.connect(self._on_pull_model)
        row1.addWidget(self.ai_pull_btn)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        self.ai_key_label = QLabel("API key:")
        row2.addWidget(self.ai_key_label)
        self.ai_key = QLineEdit()
        self.ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        row2.addWidget(self.ai_key, 1)
        self.ai_base_label = QLabel("Base URL:")
        row2.addWidget(self.ai_base_label)
        self.ai_base = QLineEdit()
        row2.addWidget(self.ai_base, 1)
        outer.addLayout(row2)

        self.notes_using_label = QLabel("")
        self.notes_using_label.setStyleSheet("color:#334155; font-size:11px; font-weight:600;")
        outer.addWidget(self.notes_using_label)

        row3 = QHBoxLayout()
        self.auto_notes = QCheckBox("Auto-generate notes when I Stop")
        self.auto_notes.setChecked(True)
        row3.addWidget(self.auto_notes)
        notes_test_btn = QPushButton("Test model")
        notes_test_btn.setToolTip("Run a quick summarization to verify the notes provider + model.")
        notes_test_btn.clicked.connect(self._test_notes_model)
        row3.addWidget(notes_test_btn)
        row3.addStretch()
        self.notes_test_status = QLabel("")
        self.notes_test_status.setStyleSheet("color: #64748b; font-size:11px;")
        row3.addWidget(self.notes_test_status)
        self.notes_status = QLabel("")
        self.notes_status.setStyleSheet("color: #64748b;")
        row3.addWidget(self.notes_status)
        outer.addLayout(row3)

        self._on_ai_provider_changed()
        return box

    def _set_model_list(self, items: list[str], select: str | None = None) -> None:
        keep = select if select is not None else self.ai_model.currentText()
        self.ai_model.blockSignals(True)
        self.ai_model.clear()
        self.ai_model.addItems(items)
        if keep:
            self.ai_model.setCurrentText(keep)
        self.ai_model.blockSignals(False)

    def _on_ai_provider_changed(self) -> None:
        from .agent import default_models

        key = self.ai_provider.currentData()
        default_model, default_base, needs_base = self._providers[key]
        env = {
            "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY", "opensource": "",
        }.get(key, "")
        # Prefer per-provider saved values, then env var, then defaults.
        saved_model = self.store.get_setting(f"ai.model.{key}")
        saved_key = self.store.get_setting(f"ai.key.{key}")
        saved_base = self.store.get_setting(f"ai.base.{key}")

        self._set_model_list(default_models(key), select=saved_model or default_model)
        self.ai_base.setText(saved_base if saved_base is not None else (default_base or ""))
        self.ai_base.setPlaceholderText(
            "required (e.g. http://localhost:11434/v1)" if needs_base
            else (default_base or "default endpoint")
        )
        self.ai_key.setText(saved_key if saved_key is not None else (os.environ.get(env, "") if env else ""))
        self.ai_key.setPlaceholderText(
            "not required for most local servers" if key == "opensource" else "API key"
        )
        # Mark which fields are required vs optional for this provider.
        if key == "opensource":
            self.ai_key_label.setText("API key (optional):")
            self.ai_base_label.setText("Base URL (required):")
        else:
            self.ai_key_label.setText("API key (required):")
            self.ai_base_label.setText("Base URL (optional):")
        # Ollama pull only makes sense for the local/open-source provider.
        self.ai_pull_btn.setVisible(key == "opensource")
        if not self._loading:
            self.store.set_setting("ai.provider", key)
        self._refresh_models()  # live fetch in the background (reads Ollama's model list)

    def _refresh_models(self) -> None:
        key = self.ai_provider.currentData()
        if key == "anthropic":
            return  # curated list only
        self.notes_status.setText("Fetching models…")
        fetcher = ModelsFetcher(key, self.ai_key.text().strip(), self.ai_base.text().strip())
        fetcher.done.connect(self._on_models_fetched)
        self._models_fetcher = fetcher  # keep a reference
        threading.Thread(target=fetcher.run, daemon=True).start()

    def _on_models_fetched(self, provider: str, models: list) -> None:
        if provider != self.ai_provider.currentData():
            return  # provider changed while fetching
        if models:
            self._set_model_list(list(models), select=self.ai_model.currentText() or None)
            self.notes_status.setText(f"{len(models)} models available.")
        else:
            self.notes_status.setText("")

    def _on_pull_model(self) -> None:
        model = self.ai_model.currentText().strip()
        if not model:
            QMessageBox.information(self, "Pull model", "Enter a model name to pull (e.g. llama3.1).")
            return
        self.ai_pull_btn.setEnabled(False)
        self.notes_status.setText(f"Pulling {model}…")
        worker = PullWorker(model)
        worker.progress.connect(lambda line: self.notes_status.setText(f"Pull: {line}"))
        worker.done.connect(self._on_pull_done)
        self._pull_worker = worker  # keep a reference
        threading.Thread(target=worker.run, daemon=True).start()

    def _on_pull_done(self, ok: bool, msg: str) -> None:
        self.ai_pull_btn.setEnabled(True)
        self.notes_status.setText(("✓ " if ok else "⚠ ") + msg)
        if ok:
            self._refresh_models()

    # ----- config persistence (so settings + keys survive restarts) -----
    def _wire_config_persistence(self) -> None:
        self.ai_model.currentTextChanged.connect(self._save_ai_fields)
        self.ai_key.textChanged.connect(self._save_ai_fields)
        self.ai_base.textChanged.connect(self._save_ai_fields)
        self.auto_notes.toggled.connect(self._persist_config)
        self.auto_refresh.toggled.connect(self._persist_config)
        self.engine_combo.currentIndexChanged.connect(self._persist_config)
        self.lang_edit.textChanged.connect(self._persist_config)
        self.model_combo.currentTextChanged.connect(self._persist_config)
        self.api_key_edit.textChanged.connect(self._persist_config)
        self.openai_model_combo.currentTextChanged.connect(self._persist_config)
        self.openai_base.textChanged.connect(self._persist_config)
        self.diarize_combo.currentIndexChanged.connect(self._persist_config)
        self.compat_provider.currentIndexChanged.connect(self._persist_config)
        self.compat_base.textChanged.connect(self._persist_config)
        self.compat_key.textChanged.connect(self._persist_config)
        self.compat_model.currentTextChanged.connect(self._persist_config)
        self.mic_combo.currentIndexChanged.connect(self._persist_config)
        self.sys_combo.currentIndexChanged.connect(self._persist_config)
        self.hf_token_edit.textChanged.connect(self._persist_config)
        self.compute_combo.currentIndexChanged.connect(self._persist_config)
        self._wire_external_persistence()
        # Keep the read-only "which model is used" lines in sync.
        for w in (self.engine_combo, self.compute_combo, self.ai_provider):
            w.currentIndexChanged.connect(self._update_using_labels)
        for w in (self.model_combo, self.openai_model_combo, self.compat_model, self.ai_model):
            w.currentTextChanged.connect(self._update_using_labels)
        for w in (self.compat_base, self.api_key_edit, self.compat_key, self.ai_key):
            w.textChanged.connect(self._update_using_labels)

    def _apply_hf_token(self) -> None:
        token = self.hf_token_edit.text().strip()
        if token:
            os.environ["HF_TOKEN"] = token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = token

    def _save_ai_fields(self) -> None:
        if self._loading:
            return
        p = self.ai_provider.currentData()
        self.store.set_setting(f"ai.model.{p}", self.ai_model.currentText().strip())
        self.store.set_setting(f"ai.key.{p}", self.ai_key.text().strip())
        self.store.set_setting(f"ai.base.{p}", self.ai_base.text().strip())

    def _persist_config(self) -> None:
        if self._loading:
            return
        s = self.store.set_setting
        s("ai.provider", self.ai_provider.currentData() or "")
        s("ui.auto_notes", "1" if self.auto_notes.isChecked() else "0")
        # NB: live "Auto" summary is intentionally NOT persisted - it always
        # starts on so summaries generate automatically with no button.
        s("t.engine", self.engine_combo.currentData() or "")
        s("t.language", self.lang_edit.text())
        s("t.local_model", self.model_combo.currentText())
        s("t.openai_key", self.api_key_edit.text())
        s("t.openai_model", self.openai_model_combo.currentText())
        s("t.openai_base", self.openai_base.text().strip())
        s("t.diarization", self.diarize_combo.currentData() or "local")
        s("t.compat_provider", self.compat_provider.currentData() or "")
        s("t.compat_base", self.compat_base.text())
        s("t.compat_key", self.compat_key.text())
        s("t.compat_model", self.compat_model.currentText())
        s("t.mic_device", self.mic_combo.currentText())
        s("t.sys_device", self.sys_combo.currentText())
        s("t.hf_token", self.hf_token_edit.text())
        s("t.compute", self.compute_combo.currentData() or "auto")
        self._apply_hf_token()
        self._save_ai_fields()

    def _load_config(self) -> None:
        # Guard against widget signals persisting half-loaded state mid-load
        # (e.g. a provider change auto-filling fields before saved values load).
        prev, self._loading = self._loading, True
        try:
            self._load_config_impl()
        finally:
            self._loading = prev

    def _load_config_impl(self) -> None:
        g = self.store.get_setting
        prov = g("ai.provider")
        if prov:
            i = self.ai_provider.findData(prov)
            if i >= 0:
                self.ai_provider.setCurrentIndex(i)  # triggers per-provider field load
        eng = g("t.engine")
        if eng:
            i = self.engine_combo.findData(eng)
            if i >= 0:
                self.engine_combo.setCurrentIndex(i)
        lang = g("t.language")
        if lang is not None:
            self.lang_edit.setText(lang)
        lm = g("t.local_model")
        if lm:
            self.model_combo.setCurrentText(lm)
        ok = g("t.openai_key")
        if ok is not None:
            self.api_key_edit.setText(ok)
        om = g("t.openai_model")
        if om:
            self.openai_model_combo.setCurrentText(om)
        ob = g("t.openai_base")
        if ob is not None:
            self.openai_base.setText(ob)
        diar = g("t.diarization")
        if diar:
            di = self.diarize_combo.findData(diar)
            if di >= 0:
                self.diarize_combo.setCurrentIndex(di)
        cp = g("t.compat_provider")
        if cp:
            i = self.compat_provider.findData(cp)
            if i >= 0:
                self.compat_provider.setCurrentIndex(i)
        cb = g("t.compat_base")
        if cb is not None:
            self.compat_base.setText(cb)
        ck = g("t.compat_key")
        if ck is not None:
            self.compat_key.setText(ck)
        cm = g("t.compat_model")
        if cm:
            self.compat_model.setCurrentText(cm)
        an = g("ui.auto_notes")
        if an is not None:
            self.auto_notes.setChecked(an == "1")
        # live "Auto" summary is not restored from settings - always starts on.
        hf = g("t.hf_token")
        if hf:
            self.hf_token_edit.setText(hf)
        self._apply_hf_token()
        comp = g("t.compute")
        if comp:
            i = self.compute_combo.findData(comp)
            if i >= 0:
                self.compute_combo.setCurrentIndex(i)
        for combo, k in ((self.mic_combo, "t.mic_device"), (self.sys_combo, "t.sys_device")):
            name = g(k)
            if name:
                i = combo.findText(name)
                if i >= 0:
                    combo.setCurrentIndex(i)
        self._load_external_config()
        self._load_email_config()
        self._load_integrations_config()

    # ----- external databases -----
    def _wire_external_persistence(self) -> None:
        for w in (self.ext_rel_enable, self.ext_graph_enable):
            w.toggled.connect(self._persist_external)
        for w in (self.ext_rel_url, self.ext_rel_db, self.ext_rel_user, self.ext_rel_pass,
                  self.ext_graph_store, self.ext_graph_update, self.ext_graph_query,
                  self.ext_graph_name, self.ext_graph_user, self.ext_graph_pass,
                  self.ext_graph_base, self.ext_graph_dataset):
            w.textChanged.connect(self._persist_external)
        self.ext_rel_kind.currentIndexChanged.connect(self._persist_external)
        self.ext_graph_type.currentIndexChanged.connect(self._persist_external)
        self.storage_mode.currentIndexChanged.connect(self._persist_external)
        self.sync_policy.currentIndexChanged.connect(self._persist_external)
        self.ext_rel_enable.toggled.connect(self._auto_sync_on_enable)
        self.ext_graph_enable.toggled.connect(self._auto_sync_on_enable)
        for w in (self.email_host, self.email_port, self.email_user, self.email_pass,
                  self.email_from, self.email_recipients):
            w.textChanged.connect(self._persist_email)
        self.email_security.currentIndexChanged.connect(self._persist_email)
        for w in (self.rest_enable, self.mcp_enable):
            w.toggled.connect(self._persist_integrations)
        for w in (self.rest_url, self.rest_auth, self.rest_headers,
                  self.mcp_url, self.mcp_tool, self.mcp_token,
                  self.pubmed_token, self.pubmed_max):
            w.textChanged.connect(self._persist_integrations)
        self.rest_method.currentIndexChanged.connect(self._persist_integrations)
        self.pubmed_enable.toggled.connect(self._persist_integrations)

    def _persist_external(self) -> None:
        if self._loading:
            return
        s = self.store.set_setting
        s("ext.rel.enabled", "1" if self.ext_rel_enable.isChecked() else "0")
        s("ext.rel.kind", self.ext_rel_kind.currentData() or "sql")
        s("ext.rel.url", self.ext_rel_url.text().strip())
        s("ext.rel.database", self.ext_rel_db.text().strip())
        s("ext.rel.user", self.ext_rel_user.text().strip())
        s("ext.rel.password", self.ext_rel_pass.text())
        s("ext.graph.enabled", "1" if self.ext_graph_enable.isChecked() else "0")
        s("ext.graph.graph_store_url", self.ext_graph_store.text().strip())
        s("ext.graph.update_url", self.ext_graph_update.text().strip())
        s("ext.graph.query_url", self.ext_graph_query.text().strip())
        s("ext.graph.named_graph", self.ext_graph_name.text().strip())
        s("ext.graph.db_type", self.ext_graph_type.currentData() or "oxigraph")
        s("ext.graph.base", self.ext_graph_base.text().strip())
        s("ext.graph.dataset", self.ext_graph_dataset.text().strip())
        s("storage.mode", self.storage_mode.currentData() or "local_remote")
        s("sync.policy", self.sync_policy.currentData() or "mirror")
        s("ext.graph.user", self.ext_graph_user.text().strip())
        s("ext.graph.password", self.ext_graph_pass.text())

    def _persist_email(self) -> None:
        if self._loading:
            return
        s = self.store.set_setting
        s("email.host", self.email_host.text().strip())
        s("email.port", self.email_port.text().strip())
        s("email.username", self.email_user.text().strip())
        s("email.password", self.email_pass.text())
        s("email.from", self.email_from.text().strip())
        s("email.security", self.email_security.currentData() or "starttls")
        s("email.recipients", self.email_recipients.text().strip())

    def _persist_integrations(self) -> None:
        if self._loading:
            return
        s = self.store.set_setting
        s("rest.enabled", "1" if self.rest_enable.isChecked() else "0")
        s("rest.url", self.rest_url.text().strip())
        s("rest.method", self.rest_method.currentText())
        s("rest.auth", self.rest_auth.text())
        s("rest.headers", self.rest_headers.text().strip())
        s("mcp.enabled", "1" if self.mcp_enable.isChecked() else "0")
        s("mcp.url", self.mcp_url.text().strip())
        s("mcp.tool", self.mcp_tool.text().strip())
        s("mcp.token", self.mcp_token.text())
        s("pubmed.enabled", "1" if self.pubmed_enable.isChecked() else "0")
        s("pubmed.api_key", self.pubmed_token.text().strip())
        s("pubmed.max", self.pubmed_max.text().strip() or "8")

    def _load_integrations_config(self) -> None:
        prev, self._loading = self._loading, True
        try:
            g = self.store.get_setting
            self.rest_enable.setChecked(g("rest.enabled") == "1")
            self.rest_url.setText(g("rest.url") or "")
            mi = self.rest_method.findText(g("rest.method") or "POST")
            if mi >= 0:
                self.rest_method.setCurrentIndex(mi)
            self.rest_auth.setText(g("rest.auth") or "")
            self.rest_headers.setText(g("rest.headers") or "")
            self.mcp_enable.setChecked(g("mcp.enabled") == "1")
            self.mcp_url.setText(g("mcp.url") or "")
            self.mcp_tool.setText(g("mcp.tool") or "")
            self.mcp_token.setText(g("mcp.token") or "")
            self.pubmed_enable.setChecked(g("pubmed.enabled") == "1")
            self.pubmed_token.setText(g("pubmed.api_key") or "")
            self.pubmed_max.setText(g("pubmed.max") or "8")
        finally:
            self._loading = prev

    def _load_email_config(self) -> None:
        prev, self._loading = self._loading, True
        try:
            g = self.store.get_setting
            self.email_host.setText(g("email.host") or "")
            self.email_port.setText(g("email.port") or "587")
            self.email_user.setText(g("email.username") or "")
            self.email_pass.setText(g("email.password") or "")
            self.email_from.setText(g("email.from") or "")
            sec = g("email.security") or "starttls"
            i = self.email_security.findData(sec)
            if i >= 0:
                self.email_security.setCurrentIndex(i)
            self.email_recipients.setText(g("email.recipients") or "")
        finally:
            self._loading = prev

    def _load_external_config(self) -> None:
        # Suppress per-widget persistence while loading, or each setText() would
        # re-save (clobbering fields not yet loaded in this pass).
        prev, self._loading = self._loading, True
        try:
            g = self.store.get_setting
            self.ext_rel_enable.setChecked(g("ext.rel.enabled") == "1")
            ki = self.ext_rel_kind.findData(g("ext.rel.kind") or "sql")
            if ki >= 0:
                self.ext_rel_kind.setCurrentIndex(ki)
            self.ext_rel_url.setText(g("ext.rel.url") or "")
            self.ext_rel_db.setText(g("ext.rel.database") or "")
            self.ext_rel_user.setText(g("ext.rel.user") or "")
            self.ext_rel_pass.setText(g("ext.rel.password") or "")
            self._on_rel_kind_changed()
            self.ext_graph_enable.setChecked(g("ext.graph.enabled") == "1")
            self.ext_graph_store.setText(g("ext.graph.graph_store_url") or "")
            self.ext_graph_update.setText(g("ext.graph.update_url") or "")
            self.ext_graph_query.setText(g("ext.graph.query_url") or "")
            from .kg import MEETGRAPH_NG
            self.ext_graph_name.setText(g("ext.graph.named_graph") or MEETGRAPH_NG)
            dt = g("ext.graph.db_type") or "oxigraph"
            di = self.ext_graph_type.findData(dt)
            if di >= 0:
                self.ext_graph_type.setCurrentIndex(di)
            self.ext_graph_base.setText(g("ext.graph.base") or "")
            self.ext_graph_dataset.setText(g("ext.graph.dataset") or "")
            sm = g("storage.mode") or "local_remote"
            si = self.storage_mode.findData(sm)
            if si >= 0:
                self.storage_mode.setCurrentIndex(si)
            sp = g("sync.policy") or "mirror"
            spi = self.sync_policy.findData(sp)
            if spi >= 0:
                self.sync_policy.setCurrentIndex(spi)
            self._fill_graph_endpoints()  # set read-only state for the chosen type
            self.ext_graph_user.setText(g("ext.graph.user") or "")
            self.ext_graph_pass.setText(g("ext.graph.password") or "")
        finally:
            self._loading = prev

    def _on_rel_kind_changed(self) -> None:
        mongo = self.ext_rel_kind.currentData() == "mongodb"
        self.ext_rel_db.setEnabled(mongo)
        self.ext_rel_url.setPlaceholderText(
            "mongodb+srv://user:pass@cluster.mongodb.net/   (MongoDB Atlas or local)" if mongo
            else "postgresql+psycopg://host:5432/dbname  (credentials optional below)")
        if not self._loading:
            self._persist_external()

    def _current_external_cfg(self):
        from .external import ExternalConfig, GraphConfig, RelationalConfig

        return ExternalConfig(
            relational=RelationalConfig(
                enabled=self.ext_rel_enable.isChecked(),
                kind=self.ext_rel_kind.currentData() or "sql",
                url=self.ext_rel_url.text().strip(),
                user=self.ext_rel_user.text().strip(),
                password=self.ext_rel_pass.text(),
                database=self.ext_rel_db.text().strip(),
            ),
            graph=GraphConfig(
                enabled=self.ext_graph_enable.isChecked(),
                query_url=self.ext_graph_query.text().strip(),
                graph_store_url=self.ext_graph_store.text().strip(),
                update_url=self.ext_graph_update.text().strip(),
                named_graph=self.ext_graph_name.text().strip(),
                user=self.ext_graph_user.text().strip(),
                password=self.ext_graph_pass.text(),
            ),
        )

    def _run_async(self, fn, on_done) -> None:
        op = _AsyncOp(fn)
        op.done.connect(on_done)
        if not hasattr(self, "_async_ops"):
            self._async_ops = []
        self._async_ops.append(op)  # keep a reference until it finishes
        threading.Thread(target=op.run, daemon=True).start()

    def _test_relational(self) -> None:
        from .external import structured_sink

        rel = self._current_external_cfg().relational
        self.ext_rel_status.setText("Testing…")
        self._run_async(
            lambda: structured_sink(rel).test(),
            lambda msg, ok: self.ext_rel_status.setText(("✓ " if ok else "⚠ ") + msg),
        )

    def _test_graph(self) -> None:
        from .external import GraphSink

        cfg = self._current_external_cfg().graph
        self.ext_graph_status.setText("Testing…")
        self._run_async(
            lambda: GraphSink(cfg).test(),
            lambda msg, ok: self.ext_graph_status.setText(("✓ " if ok else "⚠ ") + msg),
        )

    def _prev_meeting_id(self, meeting_id, user):
        try:
            ms = self.store.list_meetings(user=user or None, limit=1000)
            earlier = [m.id for m in ms if meeting_id and m.id < meeting_id]
            return max(earlier) if earlier else None
        except Exception:
            return None

    def _storage_mode(self) -> str:
        return self.storage_mode.currentData() or "local_remote"

    def _sync_policy(self) -> str:
        return self.sync_policy.currentData() or "mirror"

    def _auto_sync_on_enable(self, checked: bool) -> None:
        """When a remote database is switched on, backfill all meetings to it."""
        if self._loading or not checked or self._storage_mode() == "local_only":
            return
        self._sync_all_external()

    def _delete_remote_async(self, meeting_id) -> None:
        """Propagate a local deletion to the remote DB(s), when policy allows."""
        if meeting_id is None or self._storage_mode() == "local_only":
            return
        if self._team_readonly:
            return  # read-only team - never modify its shared DB (no content loss)
        if self._sync_policy() != "mirror":
            return  # add/update-only: never delete remotely
        cfg = self._current_external_cfg()
        if not (cfg.relational.enabled or cfg.graph.enabled):
            return
        from . import external

        gid = self._gid(meeting_id)  # remote rows are keyed by the global id
        self._run_async(lambda: (external.delete_remote(gid, cfg) and "") or "",
                        lambda m, ok: None)

    def _gid(self, local_id):
        """Local meeting id -> stable global id for the shared store (idempotent)."""
        from . import external
        return external.global_id(self._node_id, local_id)

    def _extern_rec(self, rec: dict) -> dict:
        """Copy of a meeting record with its id (and cross-link related ids)
        mapped to global ids, so it doesn't collide with teammates' meetings."""
        rec = dict(rec)
        if rec.get("id") is not None:
            rec["links"] = self.store.get_links(rec["id"]) if not rec.get("links") else rec["links"]
            rec["id"] = self._gid(rec["id"])
        rec["links"] = [{**l, "related_id": self._gid(l.get("related_id"))}
                        for l in (rec.get("links") or [])]
        return rec

    def _push_external_async(self, meeting_id) -> None:
        """Mirror one meeting to any enabled external DB, in the background."""
        if meeting_id is None:
            return
        if self._storage_mode() == "local_only":
            return  # user chose not to sync to a remote database
        if self._team_readonly:
            return  # active team's key is revoked - read-only, don't write to it
        cfg = self._current_external_cfg()
        if not (cfg.relational.enabled or cfg.graph.enabled):
            return
        from . import external

        def work():
            rec = self.store.get_meeting(meeting_id)
            if not rec:
                return "no record"
            prev = self._gid(self._prev_meeting_id(meeting_id, rec.get("user")))
            res = external.push_meeting(self._extern_rec(rec), cfg, [prev] if prev else None)
            for k, v in res.items():
                if v == "ok":
                    self.store.mark_sent(meeting_id, k)  # dedup future bulk sync
            bad = [f"{k}: {v}" for k, v in res.items() if v != "ok"]
            return "External sync failed — " + "; ".join(bad) if bad else "ok"

        def report(msg, ok):
            if msg not in ("ok", "OK"):
                self.status_label.setText(f"⚠ {msg}")

        self._run_async(work, report)

    def _sync_all_external(self) -> None:
        from . import external

        if self._team_readonly:
            if hasattr(self, "ext_sync_status"):
                self.ext_sync_status.setText("🔒 This team is read-only (key revoked) — can't write to its shared DB.")
            return
        cfg = self._current_external_cfg()
        if not (cfg.relational.enabled or cfg.graph.enabled):
            QMessageBox.information(
                self, "Nothing enabled",
                "Enable a relational or graph database (and set its connection details) first.",
            )
            return
        try:
            ids = [m.id for m in self.store.list_meetings(user=self.user or None, limit=5000)]
        except Exception as exc:
            self.ext_sync_status.setText(f"⚠ {exc}")
            return
        if not ids:
            self.ext_sync_status.setText("No meetings to sync yet.")
            return
        self.ext_sync_status.setText(f"Syncing {len(ids)} meeting(s)…")

        def work():
            recs = [self._extern_rec(r) for r in (self.store.get_meeting(i) for i in ids) if r]
            recs.sort(key=lambda r: r["id"])
            errs: list[str] = []
            # Relational/Mongo: upsert each meeting (idempotent).
            if cfg.relational.enabled and cfg.relational.url:
                rs = external.structured_sink(cfg.relational)
                for rec in recs:
                    try:
                        rs.upsert(rec)
                    except Exception as exc:
                        errs.append(f"#{rec['id']} relational: {exc}")
            # Graph: rebuild the whole 'meetgraph' named graph in one clean pass.
            if cfg.graph.enabled and (cfg.graph.graph_store_url or cfg.graph.update_url):
                try:
                    external.GraphSink(cfg.graph).replace_all(recs)
                except Exception as exc:
                    errs.append(f"graph: {exc}")
            msg = f"Synced {len(recs)} meeting(s) to external database(s)."
            if errs:
                msg += f"  {len(errs)} error(s): " + " | ".join(errs[:3])
            return msg

        self._run_async(work, lambda msg, ok: self.ext_sync_status.setText(msg))

    # ----- team & audit -----
    def _persist_identity(self) -> None:
        self._display_name = self.member_name_edit.text().strip() or self._display_name
        self.user = self.member_name_edit.text().strip() or self.user
        self.user_email = self.member_email_edit.text().strip()
        self.team_name = self.team_name_edit.text().strip()
        self.store.set_setting("user_name", self._display_name)
        self.store.set_setting("user_email", self.user_email)
        if self.team_name:
            self.store.set_setting("team.name", self.team_name)
        self._update_identity_label()

    def _audit(self, action: str, target_id: int | None = None, detail: str | None = None) -> None:
        """Record who-did-what locally and mirror it to the centralized DB."""
        try:
            entry = self.store.log_action(
                action, self._display_name, self.user_email, self.team_id or None, target_id, detail)
        except Exception:
            return
        cfg = self._current_external_cfg()
        if cfg.relational.enabled and cfg.relational.url:
            from . import external
            self._run_async(lambda: (external.push_audit(entry, cfg) and "") or "", lambda *_: None)

    def _generate_team_key(self) -> None:
        from . import team

        self._persist_identity()
        if not self.member_email_edit.text().strip():
            QMessageBox.warning(self, "Email needed", "Enter your email so the team knows who you are.")
            return
        cfg = self._current_external_cfg()
        if not (cfg.relational.enabled or cfg.graph.enabled):
            QMessageBox.warning(
                self, "Configure a database first",
                "Enable and configure an external relational and/or graph database above, then "
                "generate the key — it bundles those connection settings for your team.")
            return
        from PyQt6.QtWidgets import QInputDialog

        label, ok = QInputDialog.getText(
            self, "New team key", "Label for this key (optional, e.g. 'engineering', 'Q3 offsite'):")
        if not ok:
            return
        label = label.strip()
        tid = self.team_id or team.new_team_id()
        name = self.team_name_edit.text().strip() or "My Team"
        kid = team.new_key_id()
        created = datetime.now().isoformat(timespec="seconds")
        key = team.make_team_key(name, tid, cfg, key_id=kid, label=label, created=created)
        self.team_id, self.team_name = tid, name
        self.store.set_setting("team.id", tid)
        self.store.set_setting("team.name", name)
        try:
            self.store.add_team_key(kid, label, tid, name, key, created)
        except Exception:
            pass
        # Record a membership so the generator can switch/leave it too, and so it
        # goes read-only for them if they later revoke this key.
        if not self.store.get_membership(tid):
            self.store.add_membership(tid, name, kid, key, created)
        self._refresh_team_readonly()
        self._update_team_status()
        self._audit("team_key_generated", None, label or kid)
        self._show_key_dialog(key)

    def _show_key_dialog(self, key: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Team key — share with your team")
        v = QVBoxLayout(dlg)
        lbl = QLabel("Send this key to teammates. They paste it via “Join team”. "
                     "It contains database credentials — share over a trusted channel only.")
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        field = QLineEdit(key)
        field.setReadOnly(True)
        v.addWidget(field)
        row = QHBoxLayout()
        copy = QPushButton("Copy key")
        copy.setObjectName("primary")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(key), copy.setText("Copied ✓")))
        row.addWidget(copy)
        row.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        row.addWidget(close)
        v.addLayout(row)
        dlg.resize(560, 160)
        dlg.exec()

    def _join_team(self) -> None:
        from PyQt6.QtWidgets import QInputDialog

        from . import team

        self._persist_identity()
        if not self.member_email_edit.text().strip():
            QMessageBox.warning(self, "Email needed", "Enter your email before joining a team.")
            return
        key, ok = QInputDialog.getText(self, "Join team", "Paste the team key:")
        if not ok or not key.strip():
            return
        try:
            parsed = team.parse_team_key(key)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid key", str(exc))
            return
        ext = parsed["external"]
        # Reject revoked keys (checked against the shared DB when reachable).
        kid = parsed.get("key_id")
        if kid and ext.relational.enabled and ext.relational.url:
            try:
                from .external import structured_sink
                if kid in structured_sink(ext.relational).revoked_key_ids():
                    QMessageBox.warning(self, "Key revoked",
                                        "This team key has been revoked. Ask your team for a new one.")
                    return
            except Exception:
                pass  # can't reach the DB to check - allow, fail later if truly unusable
        self._apply_external_config(ext)
        self.team_id, self.team_name = parsed["id"], parsed["team"]
        self.store.set_setting("team.id", self.team_id)
        self.store.set_setting("team.name", self.team_name)
        self.store.add_membership(self.team_id, self.team_name, kid or "", key.strip(),
                                  datetime.now().isoformat(timespec="seconds"))
        self._refresh_team_readonly()
        self._update_team_status()
        self._audit("team_joined", None, self.team_name)
        if self._storage_mode() != "local_only" and not self._team_readonly:
            self._sync_all_external()  # backfill existing meetings to the shared DB
        QMessageBox.information(
            self, "Joined team",
            f"You're now in “{self.team_name}”. Your meetings sync to the shared database automatically.")

    def _apply_external_config(self, ext) -> None:
        """Apply a team's bundled shared-DB config into the widgets and persist it.
        Used when joining or switching teams."""
        prev, self._loading = getattr(self, "_loading", False), True
        try:
            self.ext_rel_enable.setChecked(ext.relational.enabled)
            ki = self.ext_rel_kind.findData(ext.relational.kind or "sql")
            if ki >= 0:
                self.ext_rel_kind.setCurrentIndex(ki)
            self.ext_rel_url.setText(ext.relational.url)
            self.ext_rel_db.setText(ext.relational.database)
            self.ext_rel_user.setText(ext.relational.user)
            self.ext_rel_pass.setText(ext.relational.password)
            self.ext_graph_enable.setChecked(ext.graph.enabled)
            self.ext_graph_store.setText(ext.graph.graph_store_url)
            self.ext_graph_update.setText(ext.graph.update_url)
            self.ext_graph_query.setText(ext.graph.query_url)
            self.ext_graph_name.setText(ext.graph.named_graph)
            self.ext_graph_user.setText(ext.graph.user)
            self.ext_graph_pass.setText(ext.graph.password)
        finally:
            self._loading = prev
        self._on_rel_kind_changed()
        self._persist_external()

    def _switch_team(self, team_id: str) -> None:
        """Make ``team_id`` the active team: re-apply its shared-DB config and
        recompute read-only status. Content of every joined team stays isolated
        and accessible - switching just changes which one you're viewing/writing."""
        from . import team
        m = self.store.get_membership(team_id)
        if not m:
            return
        try:
            parsed = team.parse_team_key(m.get("key") or "")
            self._apply_external_config(parsed["external"])
        except Exception:
            pass  # keep current DB config if the stored key can't be parsed
        self.team_id, self.team_name = team_id, m.get("team_name") or team_id
        self.store.set_setting("team.id", self.team_id)
        self.store.set_setting("team.name", self.team_name)
        self._refresh_team_readonly()
        self._update_team_status()
        self._refresh_meetings()

    def _active_key_revoked(self) -> bool:
        """Whether the key the user is currently active under has been revoked
        (checked locally first, then against the shared DB best-effort)."""
        if not self.team_id:
            return False
        m = self.store.get_membership(self.team_id)
        kid = (m or {}).get("key_id")
        if not kid:
            return False
        try:
            if any(k.get("key_id") == kid and k.get("revoked")
                   for k in self.store.list_team_keys()):
                return True
        except Exception:
            pass
        rel = self._current_external_cfg().relational
        if rel.enabled and rel.url:
            try:
                from .external import structured_sink
                return kid in structured_sink(rel).revoked_key_ids()
            except Exception:
                return False
        return False

    def _refresh_team_readonly(self) -> None:
        """If the active team's join key has been revoked, drop to non-team mode.

        The membership (and its key) is kept, so the team's meetings can still be
        viewed read-only from the Summary 'Show' menu - you're simply no longer
        actively in the team and won't write to its shared database."""
        self._team_readonly = False
        if self.team_id and self._active_key_revoked():
            name = self.team_name or self.team_id
            self._audit("team_key_revoked", None, name)
            self.team_id, self.team_name = "", ""
            self.store.set_setting("team.id", "")
            self.store.set_setting("team.name", "")
            # Detach the revoked team's shared DB -> back to local/personal mode.
            prev, self._loading = self._loading, True
            try:
                self.ext_rel_enable.setChecked(False)
                self.ext_graph_enable.setChecked(False)
            finally:
                self._loading = prev
            self._persist_external()
            self._revoked_team_name = name  # surfaced once in the team status

    def _leave_team(self) -> None:
        if not self.team_id:
            return
        self._audit("team_left", None, self.team_name)
        self.store.remove_membership(self.team_id)
        # Switch to another joined team if one remains; otherwise go team-less.
        remaining = [m for m in self.store.list_memberships()]
        if remaining:
            self._switch_team(remaining[0]["team_id"])
            return
        self.team_id, self.team_name = "", ""
        self.store.set_setting("team.id", "")
        self.store.set_setting("team.name", "")
        self._team_readonly = False
        self._update_team_status()
        self._refresh_meetings()

    def _show_activity_log(self) -> None:
        ActivityLogDialog(self).exec()

    # ----- email -----
    def _default_recipients(self) -> list[str]:
        from .email_send import parse_recipients

        recips = parse_recipients(self.email_recipients.text())
        try:
            recips = list(dict.fromkeys(recips + self.store.team_emails(self.team_id or None)))
        except Exception:
            pass
        return recips

    @staticmethod
    def _md_to_html(md: str) -> str:
        from PyQt6.QtGui import QTextDocument

        doc = QTextDocument()
        doc.setMarkdown(md or "")
        return doc.toHtml()

    def _send_summary_email(self, recipients, subject, text, html, target_id=None, on_done=None) -> None:
        from .email_send import send

        cfg = self._current_email_cfg()
        if not cfg.host:
            QMessageBox.warning(self, "Email not configured",
                                "Set up your SMTP server in Configuration → Email first.")
            return
        name, email, team_id = self._display_name, self.user_email, self.team_id or None

        def work():
            msg = send(cfg, recipients, subject, text, html)
            try:
                from . import external
                entry = self.store.log_action("email_sent", name, email, team_id, target_id,
                                              f"to {len(recipients)}: {subject}")
                xcfg = self._current_external_cfg()
                if xcfg.relational.enabled and xcfg.relational.url:
                    external.push_audit(entry, xcfg)
            except Exception:
                pass
            return msg

        self._run_async(work, on_done or (
            lambda m, ok: self.status_label.setText(("✓ " if ok else "⚠ ") + m)))

    # ----- unified send (email / REST / MCP / DB) with dedup -----
    def _destination_availability(self) -> dict:
        """Which send destinations are configured right now."""
        ext = self._current_external_cfg()
        em = self._current_email_cfg()
        dv = self._current_delivery_cfg()
        return {
            "email": bool(em.host),
            "rest": bool(dv.rest.enabled and dv.rest.url),
            "mcp": bool(dv.mcp.enabled and dv.mcp.url and dv.mcp.tool),
            "relational": bool(ext.relational.enabled and ext.relational.url),
            "graph": bool(ext.graph.enabled and (ext.graph.graph_store_url or ext.graph.update_url)),
        }

    def _send_meeting_to(self, rec: dict, dest: str) -> None:
        """Send one meeting record to one destination. Raises on failure."""
        import json as _json

        if dest == "email":
            from .email_send import send
            cfg = self._current_email_cfg()
            recips = self._default_recipients()
            if not cfg.host:
                raise RuntimeError("Email not configured")
            if not recips:
                raise RuntimeError("no recipients")
            md = rec.get("summary_md") or ""
            send(cfg, recips, f"Meeting notes: {rec.get('title') or 'Meeting'}", md, self._md_to_html(md))
        elif dest == "rest":
            from .delivery import RestSink, payload_for
            RestSink(self._current_delivery_cfg().rest).send(payload_for(rec))
        elif dest == "mcp":
            from .delivery import McpSink, _mcp_arguments
            McpSink(self._current_delivery_cfg().mcp).send(_mcp_arguments(rec))
        elif dest == "relational":
            if self._team_readonly:
                raise RuntimeError("team is read-only (key revoked)")
            from .external import structured_sink
            structured_sink(self._current_external_cfg().relational).upsert(self._extern_rec(rec))
        elif dest == "graph":
            if self._team_readonly:
                raise RuntimeError("team is read-only (key revoked)")
            from .external import GraphSink
            g = self._current_external_cfg().graph
            summary = {}
            if rec.get("summary_json"):
                try:
                    summary = _json.loads(rec["summary_json"])
                except Exception:
                    summary = {}
            prev = self._gid(self._prev_meeting_id(rec["id"], rec.get("user")))
            grec = self._extern_rec(rec)
            GraphSink(g).push_meeting(grec, summary, [prev] if prev else None, links=grec["links"])
        else:
            raise ValueError(f"unknown destination {dest}")

    def _open_send_dialog(self, meeting_ids, title: str) -> None:
        SendDialog(self, meeting_ids, title).exec()

    def _email_live_summary(self) -> None:
        md = self._last_summary_md
        if not md.strip():
            self._set_summary_status("No summary to email yet.")
            return
        subject = f"Meeting summary: {self.meeting_name or 'MeetGraph'}"
        EmailComposeDialog(self, self._default_recipients(), subject, md,
                           self._md_to_html(md), target_id=self._meeting_id).exec()

    # ----- background enrichment pipeline (status + resume) -----
    def _target_stages(self) -> list[str]:
        stages = ["crosslink"]
        if self.pubmed_enable.isChecked():
            stages.append("literature")
        return stages

    def _update_proc_status(self) -> None:
        if not hasattr(self, "proc_label"):
            return
        mids = {mid for mid, _ in self._processing}
        self.proc_label.setText(f"⏳ Processing {len(mids)} meeting(s)…" if mids else "✓ All processed")

    def _process_meeting(self, meeting_id, force: bool = False) -> None:
        """Run the enrichment stages this meeting still needs (status-tracked, resumable)."""
        if meeting_id is None:
            return
        done = {} if force else self.store.jobs_for(meeting_id)
        for stage in self._target_stages():
            if done.get(stage) == "done":
                continue
            self.store.mark_job(meeting_id, stage, "pending")
            self._start_stage(meeting_id, stage)

    def _start_stage(self, meeting_id, stage: str) -> None:
        key = (meeting_id, stage)
        if key in self._processing:
            return
        self._processing.add(key)
        self._update_proc_status()

        def finish():
            try:
                self.store.mark_job(meeting_id, stage, "done")
            except Exception:
                pass
            self._processing.discard(key)
            self._update_proc_status()
            self._refresh_meetings()  # reflect the new status in the table
            self._refresh_open_detail(meeting_id)  # live-update an open detail window

        if stage == "crosslink":
            self._crosslink_async(meeting_id, on_finish=finish)
        elif stage == "literature":
            self._literature_async(meeting_id, on_finish=finish)
        else:
            finish()

    def _resume_pending(self) -> None:
        """On startup, finish enrichment that was interrupted (status='pending')."""
        try:
            pending = self.store.pending_jobs()
        except Exception:
            return
        targets = set(self._target_stages())
        for mid, stage in pending:
            if stage in targets:
                self._start_stage(mid, stage)
            else:
                self.store.mark_job(mid, stage, "done")  # no longer applicable - clear it

    def _crosslink_async(self, meeting_id, on_finish=None) -> None:
        """Let the agent link this meeting to related ones, across the team if centralized."""
        if meeting_id is None:
            if on_finish:
                on_finish()
            return
        cfg = self._current_external_cfg()
        provider_cfg = {
            "provider": self.ai_provider.currentData(),
            "model": self.ai_model.currentText().strip(),
            "api_key": self.ai_key.text().strip(),
            "base_url": self.ai_base.text().strip(),
        }
        name, email, team_id = self._display_name, self.user_email, self.team_id or None
        mode = self._storage_mode()
        readonly = self._team_readonly  # revoked team: link locally but don't push

        def work():
            import json as _json

            from . import crosslink, external

            rec = self.store.get_meeting(meeting_id)
            if not rec:
                return ""
            try:
                summary = _json.loads(rec.get("summary_json") or "") if rec.get("summary_json") else {}
            except Exception:
                summary = {}
            target = crosslink.digest_of(meeting_id, rec.get("title") or "", summary)
            by_id = {d.id: d for d in crosslink.digests_from_store(self.store, exclude_id=meeting_id)}
            if cfg.graph.enabled and cfg.graph.query_url:  # team-wide candidates from the shared graph
                try:
                    for r in external.GraphSink(cfg.graph).fetch_digests():
                        if r["id"] != meeting_id and r["id"] not in by_id:
                            by_id[r["id"]] = crosslink.digest_from_remote(
                                r["id"], r["title"], r["topics"], r["qids"])
                except Exception:
                    pass
            links = [l.as_dict() for l in crosslink.cross_link(target, list(by_id.values()), provider_cfg)]
            self.store.set_links(meeting_id, links)
            rec["links"] = links
            push_res = {}
            if mode != "local_only" and not readonly and (cfg.relational.enabled or cfg.graph.enabled):
                prev = self._gid(self._prev_meeting_id(meeting_id, rec.get("user")))
                push_res = external.push_meeting(self._extern_rec(rec), cfg, [prev] if prev else None)
                for k, v in push_res.items():
                    if v == "ok":
                        self.store.mark_sent(meeting_id, k)
            try:
                entry = self.store.log_action("cross_linked", name, email, team_id, meeting_id,
                                              f"{len(links)} link(s)")
                if cfg.relational.enabled and cfg.relational.url:
                    external.push_audit(entry, cfg)
            except Exception:
                pass
            # Remote-only: once safely synced, the local copy is removed.
            if mode == "remote_only" and push_res and all(v == "ok" for v in push_res.values()):
                try:
                    self.store.delete_meeting(meeting_id)
                except Exception:
                    pass
                return "Synced to remote database; local copy removed (remote-only)."
            return f"Linked {len(links)} related meeting(s)." if links else "No related meetings found."

        def done(msg, ok):
            if msg:
                self._set_summary_status(msg)
            self._refresh_meetings()  # reflects a remote-only purge
            if on_finish:
                on_finish()

        self._run_async(work, done)

    def _literature_async(self, meeting_id, on_finish=None, force=False) -> None:
        """For a scientific meeting, attach relevant PubMed papers + research gaps.

        ``force`` runs it on demand (the "Find papers" button) even when the
        auto toggle is off - useful for meetings summarized before enabling it.
        """
        if meeting_id is None or (not force and not self.pubmed_enable.isChecked()):
            if on_finish:
                on_finish()
            return
        api_key = self.pubmed_token.text().strip()
        try:
            max_results = int(self.pubmed_max.text().strip() or "8")
        except ValueError:
            max_results = 8
        provider_cfg = {
            "provider": self.ai_provider.currentData(),
            "model": self.ai_model.currentText().strip(),
            "api_key": self.ai_key.text().strip(),
            "base_url": self.ai_base.text().strip(),
        }

        def work():
            from .agent import MeetingSummary, link_literature, summary_to_markdown

            rec = self.store.get_meeting(meeting_id)
            if not rec or not rec.get("summary_json"):
                return ""
            try:
                summary = MeetingSummary.model_validate_json(rec["summary_json"])
            except Exception:
                return ""
            link_literature(summary, api_key=api_key or None,
                            max_results=max_results, provider_cfg=provider_cfg)
            if not summary.publications:
                return "No relevant publications found."
            md = summary_to_markdown(summary, title=rec.get("title"))
            self.store.update_summary(meeting_id, md, summary.model_dump_json(indent=2))
            return f"Linked {len(summary.publications)} publication(s)" + (
                f" · {len(summary.research_gaps)} research gap(s)." if summary.research_gaps else ".")

        def done(msg, ok):
            if msg:
                self._set_summary_status(msg)
            self._refresh_meetings()
            if meeting_id == self._meeting_id:  # refresh the live view + re-sync
                rec = self.store.get_meeting(meeting_id)
                if rec and rec.get("summary_md"):
                    self._last_summary_md = rec["summary_md"]
                    self._last_summary_json = rec.get("summary_json") or ""
                    self.summary_view.setMarkdown(rec["summary_md"])
                self._push_external_async(meeting_id)
            if on_finish:
                on_finish()

        self._run_async(work, done)

    # ----- model prewarming (avoid cold start) -----
    def _maybe_prewarm(self) -> None:
        if self.controller.running:
            return
        engine = self.engine_combo.currentData()
        transcribe_config = None
        if engine == "local":
            sel = self.compute_combo.currentData() or "auto"
            transcribe_config = {
                "engine": "local",
                "language": self.lang_edit.text().strip(),
                "model_size": self.model_combo.currentText().strip(),
                "device": sel,
                "compute_type": {"cpu": "int8", "cuda": "float16"}.get(sel, "auto"),
            }
        # Pull the Ollama notes model only when pointed at a local Ollama server.
        pull_model = None
        if self.ai_provider.currentData() == "opensource":
            base = self.ai_base.text().strip()
            if (not base) or ("11434" in base) or ("localhost" in base) or ("127.0.0.1" in base):
                pull_model = self.ai_model.currentText().strip() or None

        sig = (str(transcribe_config), pull_model)
        if sig == getattr(self, "_prewarm_sig", None):
            return  # already warmed for this exact configuration
        if not transcribe_config and not pull_model:
            return
        self._prewarm_sig = sig
        worker = PrewarmWorker(transcribe_config, pull_model)
        worker.progress.connect(self.status_label.setText)
        worker.done.connect(lambda ok, msg: msg and self.status_label.setText(msg))
        self._prewarm_worker = worker  # keep a reference
        threading.Thread(target=worker.run, daemon=True).start()

    # ----- live meeting summary -----
    def _notes_ready(self) -> bool:
        if not self.transcript.entries:
            return False
        provider = self.ai_provider.currentData()
        if provider in ("anthropic", "openai", "openrouter") and not self.ai_key.text().strip():
            return False
        return True

    def _run_notes(self) -> None:
        """Generate / refresh the live summary (auto, the ⟳ button, or on Stop)."""
        if self._notes_busy:
            return
        if not self.transcript.entries:
            self._set_summary_status("Transcript is empty — nothing to summarize yet.")
            return
        if not self._notes_ready():
            self._set_summary_status("Set an API key in Configuration to generate the summary.")
            return
        config = {
            "provider": self.ai_provider.currentData(),
            "model": self.ai_model.currentText().strip(),
            "api_key": self.ai_key.text().strip(),
            "base_url": self.ai_base.text().strip(),
        }
        # Incremental: once we have a running summary, only summarize the NEW
        # speech and merge it in - so long meetings stay fast and nothing is lost.
        # Use content without diarization labels: the summary describes what was
        # said, not a per-speaker breakdown (labels stay in the live transcript).
        full = self.transcript.to_content()
        running = getattr(self, "_running_summary", None)
        done_chars = getattr(self, "_summarized_chars", 0)
        incremental = running is not None and len(full) > done_chars
        text = full[done_chars:] if incremental else full
        if incremental and len(text.strip()) < 40:
            # Not enough new speech to bother - just re-render what we have.
            self._set_summary_status("Summary up to date.")
            return

        self._notes_busy = True
        self._summary_dirty = False
        self.summary_btn.setEnabled(False)
        self._set_summary_status("Summarizing…")
        worker = NotesWorker(config, text, title=self.meeting_name or None,
                             incremental=incremental, dispatch_len=len(full))
        worker.done.connect(self._on_notes_done)
        worker.failed.connect(self._on_notes_failed)
        self._notes_worker = worker  # keep a reference
        threading.Thread(target=worker.run, daemon=True).start()

    def _autogen_notes(self) -> None:
        if self.auto_notes.isChecked() and self._notes_ready():
            self._run_notes()

    def _on_summary_tick(self) -> None:
        # Auto-summarize as the meeting goes - only when there's new speech.
        if (self.controller.running and self.auto_refresh.isChecked()
                and self._summary_dirty and not self._notes_busy and self._notes_ready()):
            self._run_notes()

    def _on_notes_done(self, json_text: str, incremental: bool, dispatch_len: int) -> None:
        from .agent import MeetingSummary, merge_summaries, summary_to_markdown

        self._notes_busy = False
        self.summary_btn.setEnabled(True)
        try:
            chunk = MeetingSummary.model_validate_json(json_text)
        except Exception:
            self._set_summary_status("⚠ Could not parse the summary.")
            return
        if incremental and getattr(self, "_running_summary", None) is not None:
            self._running_summary = merge_summaries(self._running_summary, chunk)
        else:
            self._running_summary = chunk
        self._summarized_chars = max(getattr(self, "_summarized_chars", 0), dispatch_len)

        from .agent import Provenance
        self._running_summary.provenance = Provenance(
            transcription=getattr(self, "_transcribe_label", None), notes=self._notes_label())

        markdown = summary_to_markdown(self._running_summary, title=self.meeting_name or None)
        json_text = self._running_summary.model_dump_json(indent=2)
        self._last_summary_md = markdown
        self._last_summary_json = json_text
        self.summary_view.setMarkdown(markdown)  # live summary on the Record tab
        self._set_summary_status(f"Summary updated · {datetime.now():%H:%M:%S}")
        if self._meeting_id is not None:
            try:
                self.store.update_summary(self._meeting_id, markdown, json_text)
                self._refresh_meetings()
            except Exception:
                pass
            self._push_external_async(self._meeting_id)  # mirror to external DB(s)
            # When this is the final (post-Stop) summary, record it and let the
            # agent link this meeting to related ones. (Skipped on live ticks.)
            if not self.controller.running:
                self.store.mark_job(self._meeting_id, "summary", "done")
                self._audit("summary_generated", self._meeting_id)
                self._process_meeting(self._meeting_id)  # crosslink + literature (status-tracked)

    def _on_notes_failed(self, msg: str) -> None:
        self._notes_busy = False
        self.summary_btn.setEnabled(True)
        self._set_summary_status(f"⚠ {msg}")

    def _set_summary_status(self, msg: str) -> None:
        if hasattr(self, "notes_status"):
            self.notes_status.setText(msg)
        self.status_label.setText(msg)

    def _populate_devices(self) -> None:
        self.devices = list_input_devices()
        self.mic_combo.clear()
        self.sys_combo.clear()
        for dev in self.devices:
            self.mic_combo.addItem(str(dev), dev.index)
            self.sys_combo.addItem(str(dev), dev.index)

        bh = find_system_audio_device(self.devices)
        if bh is not None:
            i = self.sys_combo.findData(bh.index)
            if i >= 0:
                self.sys_combo.setCurrentIndex(i)
            self.bh_hint.setText("")
        else:
            self.bh_hint.setText(_system_audio_hint())

    # ------------------------------------------------------------- controller
    def _wire_controller(self) -> None:
        self.controller.new_text.connect(self._on_new_text)
        self.controller.status.connect(self.status_label.setText)
        self.controller.started.connect(self._on_started)
        self.controller.paused.connect(self._on_paused)
        self.controller.stopped.connect(self._on_stopped)
        self.controller.error.connect(self._on_error)

    def _device_by_index(self, idx: int):
        for dev in self.devices:
            if dev.index == idx:
                return dev
        return None

    def _on_engine_changed(self) -> None:
        self.engine_stack.setCurrentIndex(self.engine_combo.currentIndex())

    def _transcription_label(self, cfg: dict) -> str:
        """Human-readable provenance for which engine/model produced the transcript."""
        from .transcribe import compute_label

        eng = cfg.get("engine")
        if eng == "local":
            return f"Whisper {cfg.get('model_size')} · {compute_label(cfg.get('device', 'auto'))} (local)"
        if eng == "openai":
            base = cfg.get("base_url")
            return f"OpenAI {cfg.get('openai_model')}" + (f" @ {base}" if base else "")
        if eng == "compatible":
            return f"{cfg.get('openai_model')} @ {cfg.get('base_url')}"
        return str(eng)

    def _update_using_labels(self) -> None:
        """Read-only lines showing exactly which provider+model is used for each."""
        if hasattr(self, "engine_using_label"):
            try:
                self.engine_using_label.setText(
                    "▸ Transcribing with: " + self._transcription_label(self._transcription_config()))
            except Exception:
                pass
        if hasattr(self, "notes_using_label"):
            try:
                self.notes_using_label.setText("▸ Notes written by: " + self._notes_label())
            except Exception:
                pass
        self._update_models_banner()

    def _update_models_banner(self) -> None:
        """Top-of-Meeting banner: which models are used (open-source vs cloud) + key status."""
        if not hasattr(self, "models_banner"):
            return
        try:
            eng = self.engine_combo.currentData()
            t_label = self._transcription_label(self._transcription_config())
            if eng == "local":
                t = f"{t_label} · local / open-source"
            elif eng == "openai":
                t = f"{t_label} · cloud · " + ("✓ key set" if self.api_key_edit.text().strip() else "⚠ API key required")
            else:
                t = f"{t_label} · custom · " + ("✓ key set" if self.compat_key.text().strip() else "no key (ok for local)")

            prov = self.ai_provider.currentData()
            n_label = self._notes_label()
            if prov == "opensource":
                n = f"{n_label} · open-source / local"
            else:
                n = f"{n_label} · cloud · " + ("✓ key set" if self.ai_key.text().strip() else "⚠ API key required")

            ok = "⚠" not in (t + n)
            self.models_banner.setText(f"🎙 Transcription: {t}    🧠 Notes: {n}")
            color = "#0d9488" if ok else "#b45309"
            bg = "#ecfdf5" if ok else "#fffbeb"
            border = "#a7f3d0" if ok else "#fcd34d"
            self.models_banner.setStyleSheet(
                f"color:{color}; background:{bg}; border:1px solid {border}; "
                "border-radius:8px; padding:6px 10px; font-size:11px; font-weight:600;")
        except Exception:
            pass

    def _notes_label(self) -> str:
        from .agent import PROVIDER_LABELS

        provider = self.ai_provider.currentData()
        model = self.ai_model.currentText().strip()
        return f"{PROVIDER_LABELS.get(provider, provider)} · {model}" if model else PROVIDER_LABELS.get(provider, provider)

    def _transcription_config(self) -> dict:
        """Build the transcription engine config from the current widgets."""
        sel = self.compute_combo.currentData() or "auto"
        engine = self.engine_combo.currentData()
        config = {
            "engine": engine,
            "language": self.lang_edit.text().strip(),
            "model_size": self.model_combo.currentText().strip(),
            "device": sel,
            "compute_type": {"cpu": "int8", "cuda": "float16"}.get(sel, "auto"),
            "api_key": self.api_key_edit.text().strip(),
            "openai_model": self.openai_model_combo.currentText().strip(),
            "diarization": self.diarize_combo.currentData() or "local",
            "hf_token": self.hf_token_edit.text().strip(),
        }
        if engine == "openai":
            config["base_url"] = self.openai_base.text().strip()
        if engine == "compatible":
            config["api_key"] = self.compat_key.text().strip()
            config["base_url"] = self.compat_base.text().strip()
            config["openai_model"] = self.compat_model.currentText().strip()
        return config

    def _test_transcription(self) -> None:
        config = self._transcription_config()
        if config["engine"] == "compatible" and not config.get("base_url"):
            self.engine_test_status.setText("⚠ Enter the base URL.")
            return
        if config["engine"] == "openai" and not config["api_key"]:
            self.engine_test_status.setText("⚠ Enter your OpenAI API key.")
            return
        self.engine_test_status.setText("Testing… (first local run downloads the model)")

        def work():
            from .transcribe import make_transcriber
            import numpy as np

            t = make_transcriber(config)
            try:
                t.transcribe(np.zeros(8000, dtype=np.float32))  # 0.5s silence
            finally:
                try:
                    t.close()
                except Exception:
                    pass
            return f"Transcription engine ready ({config['engine']})."

        self._run_async(work, lambda m, ok: self.engine_test_status.setText(("✓ " if ok else "⚠ ") + m))

    def _test_notes_model(self) -> None:
        if not self._notes_ready_provider():
            self.notes_test_status.setText("⚠ Set the provider's API key first.")
            return
        cfg = {
            "provider": self.ai_provider.currentData(),
            "model": self.ai_model.currentText().strip(),
            "api_key": self.ai_key.text().strip(),
            "base_url": self.ai_base.text().strip(),
        }
        self.notes_test_status.setText("Testing model…")

        def work():
            from .agent import MeetingNotesAgent

            agent = MeetingNotesAgent(provider=cfg["provider"], model_name=cfg["model"] or None,
                                      api_key=cfg["api_key"] or None, base_url=cfg["base_url"] or None)
            s = agent.summarize("Alice: Let's ship v2 next week. Bob: Agreed, I'll prep the release notes.",
                                title=None)
            return f"Notes model OK — produced {len(s.topics)} topic(s), {len(s.action_items)} action(s)."

        self._run_async(work, lambda m, ok: self.notes_test_status.setText(("✓ " if ok else "⚠ ") + m))

    def _notes_ready_provider(self) -> bool:
        provider = self.ai_provider.currentData()
        return not (provider in ("anthropic", "openai", "openrouter") and not self.ai_key.text().strip())

    def _on_compat_provider_changed(self) -> None:
        key = self.compat_provider.currentData()
        if key == "custom":
            return  # leave the user's own values untouched
        _label, url, model = COMPAT_PROVIDERS.get(key, ("", "", ""))
        if url:
            self.compat_base.setText(url)
        if model:
            self.compat_model.setCurrentText(model)

    def _on_start(self) -> None:
        sources = []
        # With diarization on, don't assume the recorder is the speaker - use a
        # neutral source label (the diarizer overrides it with Speaker N when
        # available; otherwise lines stay neutral rather than the recorder's name).
        diar_on = self.diarize_combo.currentData() == "local"
        mic_label = "Mic" if diar_on else self.speaker_self
        if self.mic_check.isChecked():
            dev = self._device_by_index(self.mic_combo.currentData())
            if dev:
                sources.append((dev, mic_label))
        if self.sys_check.isChecked():
            dev = self._device_by_index(self.sys_combo.currentData())
            if dev:
                sources.append((dev, "Meeting"))
        if not sources:
            QMessageBox.warning(self, "No source", "Enable at least one audio source.")
            return

        config = self._transcription_config()
        self._transcribe_label = self._transcription_label(config)
        engine = config["engine"]
        if engine == "compatible" and not config.get("base_url"):
            QMessageBox.warning(self, "Missing URL", "Enter the OpenAI-compatible base URL.")
            return
        if engine == "openai" and not config["api_key"]:
            QMessageBox.warning(self, "Missing key", "Enter your OpenAI API key.")
            return

        # Start always begins a NEW meeting - clear the previous transcript & summary.
        self.transcript.clear()
        self.transcript_view.clear()
        self.summary_view.clear()
        self._last_summary_md = ""
        self._last_summary_json = ""
        self._view_md = ""
        self._view_json = ""
        self._meeting_id = None
        self._running_summary = None       # reset incremental running summary
        self._summarized_chars = 0

        self._started_at = datetime.now()
        self.transcript.started_at = self._started_at
        self.start_btn.setEnabled(False)
        self.controller.start(config, sources)

    def _on_pause_resume(self) -> None:
        if self.controller.is_paused:
            self.controller.resume()
        else:
            self.controller.pause()

    def _on_started(self) -> None:  # fired on start and on resume
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("❚❚ Pause")
        self._set_badge("recording")
        self._set_settings_enabled(False)
        self._summary_timer.start()  # drives optional live auto-refresh

    def _on_paused(self) -> None:
        self.pause_btn.setText("▶ Resume")
        self._set_badge("paused")
        self._summary_timer.stop()

    def _on_stopped(self) -> None:
        self.start_btn.setEnabled(True)
        self.start_btn.setText("● Start new meeting")  # current meeting ended
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("❚❚ Pause")
        self._set_badge("idle")
        self._set_settings_enabled(True)
        self._summary_timer.stop()
        self._persist_meeting()
        self._autogen_notes()

    def _persist_meeting(self) -> None:
        """Store the meeting transcript locally (summary is added when ready)."""
        if not self.transcript.entries:
            return
        try:
            default_title = f"Meeting {self._started_at:%Y-%m-%d %H:%M}" if self._started_at else "Meeting"
            self._meeting_id = self.store.save_meeting(
                user=self.user,
                title=self.meeting_name or default_title,
                started_at=self._started_at.isoformat() if self._started_at else "",
                ended_at=datetime.now().isoformat(timespec="seconds"),
                transcript_md=self.transcript.to_markdown(),
                transcript_plain=self.transcript.to_plain(),
                team_id=self.team_id or None,
            )
            # Mark enrichment as pending up front so the Summary tab shows the
            # meeting as processing from the moment recording stops.
            if self.auto_notes.isChecked():
                self.store.mark_job(self._meeting_id, "summary", "pending")
                for stage in self._target_stages():
                    self.store.mark_job(self._meeting_id, stage, "pending")
            self.status_label.setText(f"Saved transcript to local database (#{self._meeting_id}).")
            self._refresh_meetings()
            self._audit("meeting_saved", self._meeting_id, self.meeting_name or default_title)
            self._push_external_async(self._meeting_id)  # mirror to external DB(s)
        except Exception as exc:
            self.status_label.setText(f"⚠ Could not save to database: {exc}")

    def _set_settings_enabled(self, enabled: bool) -> None:
        for w in (
            self.engine_combo, self.model_combo, self.api_key_edit,
            self.openai_model_combo, self.openai_base, self.diarize_combo,
            self.compat_provider, self.compat_base,
            self.compat_key, self.compat_model, self.lang_edit, self.mic_check,
            self.sys_check, self.mic_combo, self.sys_combo,
        ):
            w.setEnabled(enabled)

    _SPK_PALETTE = ["#7c3aed", "#db2777", "#ea580c", "#0891b2", "#65a30d", "#9333ea", "#c026d3", "#0d9488"]

    def _speaker_color(self, speaker: str) -> str:
        if speaker == self.speaker_self:
            return SPEAKER_COLORS["You"]
        if speaker in SPEAKER_COLORS:
            return SPEAKER_COLORS[speaker]
        if not hasattr(self, "_speaker_colors"):
            self._speaker_colors = {}
        if speaker not in self._speaker_colors:
            self._speaker_colors[speaker] = self._SPK_PALETTE[len(self._speaker_colors) % len(self._SPK_PALETTE)]
        return self._speaker_colors[speaker]

    def _on_new_text(self, speaker: str, ts: datetime, text: str) -> None:
        self.transcript.add(speaker, text, when=ts)
        self._summary_dirty = True  # triggers auto-summary on the next tick
        color = self._speaker_color(speaker)
        chip = (
            f'<span style="background:{color}1a; color:{color};'
            f' font-weight:700; padding:1px 6px; border-radius:4px;">{speaker}</span>'
        )
        html = (
            f'<div style="margin:0 0 6px 0; line-height:150%;">'
            f'<span style="color:#94a3b8;">[{ts:%H:%M:%S}]</span> {chip} '
            f'<span style="color:#1f2733;">{_escape(text)}</span></div>'
        )
        self.transcript_view.append(html)  # each call is its own paragraph
        sb = self.transcript_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_error(self, msg: str) -> None:
        self.status_label.setText(f"⚠ {msg}")

    # ------------------------------------------------------------- transcript
    def _on_clear(self) -> None:
        self.transcript.clear()
        self.transcript_view.clear()
        self.status_label.setText("Cleared.")

    def _on_copy(self) -> None:
        QApplication.clipboard().setText(self.transcript.to_markdown())
        self.status_label.setText("Markdown copied to clipboard.")

    def _default_filename(self) -> str:
        return f"meeting-{datetime.now():%Y%m%d-%H%M}.md"

    def _on_save(self) -> str | None:
        if not self.transcript.entries:
            QMessageBox.information(self, "Nothing to save", "Transcript is empty.")
            return None
        path, _ = QFileDialog.getSaveFileName(
            self, "Save transcript", self._default_filename(), "Markdown (*.md)"
        )
        if not path:
            return None
        if not path.endswith(".md"):
            path += ".md"
        self.transcript.save_markdown(path)
        self.status_label.setText(f"Saved → {path}")
        return path

    def _on_share(self) -> None:
        if not self.transcript.entries:
            QMessageBox.information(self, "Nothing to share", "Transcript is empty.")
            return
        path = self._on_save()
        if path:
            reveal_in_file_manager(path)
            self.status_label.setText(
                f"Saved & revealed in file manager — right-click → Share, or drag to send. ({path})"
            )

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self.controller.stop()
        event.accept()


class ModelsFetcher(QObject):
    """Fetches a provider's available model list off the GUI thread."""

    done = pyqtSignal(str, list)  # provider, model ids

    def __init__(self, provider: str, api_key: str, base_url: str):
        super().__init__()
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url

    def run(self) -> None:
        from .agent import fetch_models

        try:
            models = fetch_models(self.provider, self.api_key or None, self.base_url or None)
        except Exception:
            models = []
        self.done.emit(self.provider, models)


class PullWorker(QObject):
    """Runs `ollama pull <model>` off the GUI thread, streaming progress."""

    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)  # ok, message

    def __init__(self, model: str):
        super().__init__()
        self.model = model

    def run(self) -> None:
        import subprocess

        try:
            proc = subprocess.Popen(
                ["ollama", "pull", self.model],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            last = ""
            for line in proc.stdout:  # type: ignore[union-attr]
                last = line.strip() or last
                self.progress.emit(last)
            code = proc.wait()
            self.done.emit(code == 0, "Pulled" if code == 0 else f"ollama pull exited {code}")
        except FileNotFoundError:
            self.done.emit(False, "ollama not found — install Ollama (ollama.com)")
        except Exception as exc:
            self.done.emit(False, str(exc))


class PrewarmWorker(QObject):
    """Pre-downloads/loads the configured models so Start has no cold-start wait.

    Warms the local transcription model (a short silent decode forces the model
    files to download into the cache) and, for the open-source notes provider,
    pulls the Ollama model.
    """

    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, transcribe_config: dict | None, pull_model: str | None):
        super().__init__()
        self.transcribe_config = transcribe_config
        self.pull_model = pull_model

    def run(self) -> None:
        ready = []
        try:
            if self.transcribe_config:
                self.progress.emit("Preparing transcription model… (first run downloads it)")
                from .transcribe import make_transcriber
                import numpy as np

                t = make_transcriber(self.transcribe_config)
                try:
                    t.transcribe(np.zeros(8000, dtype=np.float32))  # 0.5s silence -> forces load
                except Exception:
                    pass
                finally:
                    try:
                        t.close()
                    except Exception:
                        pass
                ready.append("transcription model")
            if self.pull_model:
                import subprocess

                self.progress.emit(f"Downloading notes model {self.pull_model}…")
                try:
                    proc = subprocess.run(
                        ["ollama", "pull", self.pull_model],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    )
                    if proc.returncode == 0:
                        ready.append(self.pull_model)
                except FileNotFoundError:
                    pass  # ollama not installed - silently skip
            self.done.emit(True, ("Models ready: " + ", ".join(ready)) if ready else "")
        except Exception as exc:
            self.done.emit(False, f"Model prep: {exc}")


class _AsyncOp(QObject):
    """Runs a blocking callable off the GUI thread and reports back via a signal."""

    done = pyqtSignal(str, bool)  # message, ok

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            msg = self._fn()
            self.done.emit(msg or "OK", True)
        except Exception as exc:
            self.done.emit(f"{type(exc).__name__}: {exc}", False)


class NotesWorker(QObject):
    """Runs the (provider-agnostic) Pydantic AI notes agent off the GUI thread.

    Summarizes the given text (a recent chunk for incremental live updates, or the
    full transcript) and emits the raw summary JSON; the UI merges it into the
    running summary. Key-term linking (network) stays off the GUI thread here.
    """

    done = pyqtSignal(str, bool, int)  # summary json, incremental, dispatch_len
    failed = pyqtSignal(str)

    def __init__(self, config, transcript_text, title, incremental=False, dispatch_len=0):
        super().__init__()
        self.config = config
        self.transcript_text = transcript_text
        self.title = title
        self.incremental = incremental
        self.dispatch_len = dispatch_len

    def run(self) -> None:
        try:
            from .agent import MeetingNotesAgent, link_key_terms

            agent = MeetingNotesAgent(
                provider=self.config["provider"],
                model_name=self.config.get("model") or None,
                api_key=self.config.get("api_key") or None,
                base_url=self.config.get("base_url") or None,
            )
            summary = agent.summarize(self.transcript_text, title=self.title)
            link_key_terms(summary)  # resolve key terms -> Wikipedia / Wikidata (best-effort)
            self.done.emit(summary.model_dump_json(), self.incremental, self.dispatch_len)
        except Exception as exc:  # surface to the UI
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class NotesDialog(QDialog):
    """Shows generated notes with copy / save (.md + .json) / share actions."""

    def __init__(self, parent, markdown: str, json_text: str):
        super().__init__(parent)
        self.setWindowTitle("MeetGraph — Meeting Notes")
        self.setWindowIcon(app_icon())
        self.resize(720, 640)
        self.markdown = markdown
        self.json_text = json_text

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        heading = QLabel("Structured meeting notes")
        heading.setObjectName("HeaderTitle")
        layout.addWidget(heading)
        view = QTextBrowser()
        view.setObjectName("transcript")
        view.setOpenExternalLinks(True)  # clickable Wikipedia/Wikidata links
        view.setMarkdown(markdown)
        view.setFont(QFont("SF Pro Text", 13))
        layout.addWidget(view, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        copy_btn = QPushButton("Copy Markdown")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.markdown))
        row.addWidget(copy_btn)
        row.addStretch()
        save_btn = QPushButton("Save .md + .json")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save)
        row.addWidget(save_btn)
        share_btn = QPushButton("Share…")
        share_btn.clicked.connect(self._share)
        row.addWidget(share_btn)
        layout.addLayout(row)

    def _save(self) -> str | None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save notes", f"meeting-notes-{datetime.now():%Y%m%d-%H%M}.md", "Markdown (*.md)"
        )
        if not path:
            return None
        if not path.endswith(".md"):
            path += ".md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.markdown)
        with open(path[:-3] + ".json", "w", encoding="utf-8") as f:
            f.write(self.json_text)
        return path

    def _share(self) -> None:
        path = self._save()
        if path:
            reveal_in_file_manager(path)


def _system_audio_hint() -> str:
    if sys.platform == "darwin":
        return "No loopback device found — install BlackHole to capture meeting audio (see README)."
    if sys.platform.startswith("win"):
        return "No loopback device found — enable 'Stereo Mix' or install VB-Cable (see README)."
    return "No loopback device found — pick your PulseAudio '.monitor' source (see README)."


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


class MeetingDetailDialog(QDialog):
    """A meeting's summary + full transcript in its own window, with actions."""

    def __init__(self, parent, rec: dict, remote: bool = False):
        super().__init__(parent)
        self._parent = parent
        self._rec = rec
        self._remote = remote
        self._mid = rec.get("id")
        self._json = rec.get("summary_json") or ""
        title = rec.get("title") or "Meeting"
        self.setWindowTitle(f"MeetGraph — {title}" + ("  (shared)" if remote else ""))
        self.setWindowIcon(app_icon())
        self.resize(780, 700)

        self._summary_md = rec.get("summary_md") or f"# {title}\n\n_No summary was generated._"
        self._transcript_md = rec.get("transcript_md") or "_No transcript._"
        # Cross-links live in the local DB; skip for shared/remote records.
        self._related_md = "" if remote else self._build_related_md(parent, rec.get("id"))

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)

        self._head = QLabel(title)
        self._head.setObjectName("HeaderTitle")
        v.addWidget(self._head)
        when = (rec.get("started_at") or rec.get("created_at") or "")[:16].replace("T", " ")
        sub = QLabel(f"{when}   ·   {rec.get('user') or ''}")
        sub.setObjectName("HeaderSubtitle")
        v.addWidget(sub)
        self._editing = False
        self._edited_label = QLabel("")
        self._edited_label.setStyleSheet("color:#0d9488; font-size:11px;")
        v.addWidget(self._edited_label)
        self._refresh_edited_label()

        scope_row = QHBoxLayout()
        scope_row.setSpacing(8)
        scope_row.addWidget(QLabel("Include:"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("Summary + transcript", "both")
        self.scope_combo.addItem("Summary only", "summary")
        self.scope_combo.addItem("Transcript only", "transcript")
        self.scope_combo.currentIndexChanged.connect(self._update_view)
        scope_row.addWidget(self.scope_combo)
        scope_row.addStretch()
        v.addLayout(scope_row)

        self._view = QTextBrowser()
        self._view.setObjectName("transcript")
        self._view.setOpenLinks(False)          # handle clicks ourselves
        self._view.setOpenExternalLinks(False)
        self._view.anchorClicked.connect(self._on_anchor)
        self._view.setFont(QFont("SF Pro Text", 13))
        v.addWidget(self._view, 1)
        # Raw-markdown editor (hidden until "Edit"): lets the user refine/add info.
        self._editor = QTextEdit()
        self._editor.setObjectName("transcript")
        self._editor.setFont(QFont("Menlo", 12))
        self._editor.hide()
        v.addWidget(self._editor, 1)
        self._update_view()

        row = QHBoxLayout()
        row.setSpacing(8)
        rename = QPushButton("Rename…")
        rename.setToolTip("Rename this meeting")
        rename.clicked.connect(self._rename)
        row.addWidget(rename)
        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setToolTip("Edit the summary and add your own notes")
        self._edit_btn.clicked.connect(self._toggle_edit)
        row.addWidget(self._edit_btn)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._exit_edit)
        self._cancel_btn.hide()
        row.addWidget(self._cancel_btn)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self._current_md()))
        row.addWidget(copy)
        exp = QPushButton("Export .md")
        exp.setObjectName("primary")
        exp.clicked.connect(self._export)
        row.addWidget(exp)
        self._papers_btn = QPushButton("Find papers")
        self._papers_btn.setToolTip("Search PubMed for related publications (PMID + DOI) and attach them")
        self._papers_btn.clicked.connect(self._find_papers)
        self._papers_btn.setEnabled(not self._remote)
        row.addWidget(self._papers_btn)
        em = QPushButton("Email…")
        em.setToolTip("Email this meeting's notes to your team")
        em.clicked.connect(self._email)
        row.addWidget(em)
        snd = QPushButton("Send…")
        snd.setToolTip("Send this meeting to REST API / MCP / databases (skips already-sent)")
        snd.clicked.connect(lambda: self._parent._open_send_dialog([self._mid], "Send this meeting"))
        row.addWidget(snd)
        rdf = QPushButton("Export RDF…")
        rdf.setToolTip("Export this meeting as a knowledge graph (JSON-LD / Turtle), "
                       "with key terms linked to Wikipedia/Wikidata and links to previous meetings.")
        rdf.clicked.connect(self._export_rdf)
        row.addWidget(rdf)
        share = QPushButton("Share…")
        share.clicked.connect(self._share)
        row.addWidget(share)
        row.addStretch()
        delete = QPushButton("Delete")
        delete.setObjectName("danger")
        delete.clicked.connect(self._delete)
        delete.setEnabled(not self._remote)  # don't delete shared records from here
        if self._remote:
            delete.setToolTip("This is a shared (remote) meeting — manage it in the shared database.")
        row.addWidget(delete)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)

    def _on_anchor(self, url) -> None:
        """Open a related meeting (meetgraph: links) or an external link (Wikipedia, etc.)."""
        from PyQt6.QtGui import QDesktopServices

        s = url.toString()
        if s.startswith("meetgraph:"):
            try:
                mid = int(s.rstrip("/").split("/")[-1])
            except ValueError:
                return
            rec = self._parent.store.get_meeting(mid)
            if rec:
                MeetingDetailDialog(self._parent, rec).exec()
            else:
                QMessageBox.information(self, "Not found",
                                        "That meeting isn't in this local database (it may be a teammate's).")
        else:
            QDesktopServices.openUrl(url)

    def _scope(self) -> str:
        return self.scope_combo.currentData()

    def _refresh_edited_label(self) -> None:
        by = self._rec.get("edited_by")
        at = (self._rec.get("edited_at") or "")[:16].replace("T", " ")
        if by:
            self._edited_label.setText(f"✏ Edited by {by}" + (f" on {at}" if at else ""))
            self._edited_label.show()
        else:
            self._edited_label.hide()

    def _toggle_edit(self) -> None:
        if not self._editing:
            self._editing = True
            self._editor.setPlainText(self._summary_md)
            self._view.hide()
            self._editor.show()
            self._edit_btn.setText("Save changes")
            self._cancel_btn.show()
            self.scope_combo.setEnabled(False)
        else:
            self._save_edit()

    def _exit_edit(self) -> None:
        self._editing = False
        self._editor.hide()
        self._view.show()
        self._edit_btn.setText("Edit")
        self._cancel_btn.hide()
        self.scope_combo.setEnabled(True)

    def _save_edit(self) -> None:
        new_md = self._editor.toPlainText()
        by = self._parent._display_name
        at = datetime.now().isoformat(timespec="seconds")
        self._summary_md = new_md
        self._rec["summary_md"] = new_md
        self._rec["edited_by"] = by
        self._rec["edited_at"] = at
        try:
            if self._remote:
                from .external import structured_sink
                rel = self._parent._current_external_cfg().relational
                if rel.enabled and rel.url:
                    structured_sink(rel).upsert(self._rec)
            else:
                self._parent.store.set_summary_edited(self._mid, new_md, by, at)
                self._parent._audit("summary_edited", self._mid, by)
                self._parent._push_external_async(self._mid)
        except Exception as exc:
            QMessageBox.warning(self, "Edit", f"Saved locally, but sync failed: {exc}")
        self._exit_edit()
        self._refresh_edited_label()
        self._update_view()
        self._parent._refresh_meetings()

    def reload(self) -> None:
        """Re-load this meeting from the local store (after background enrichment)."""
        if self._remote or self._mid is None or self._editing:
            return
        rec = self._parent.store.get_meeting(self._mid)
        if not rec:
            return
        self._rec = rec
        self._json = rec.get("summary_json") or ""
        title = rec.get("title") or "Meeting"
        self._summary_md = rec.get("summary_md") or f"# {title}\n\n_No summary was generated._"
        self._transcript_md = rec.get("transcript_md") or "_No transcript._"
        self._related_md = self._build_related_md(self._parent, self._mid)
        self._refresh_edited_label()
        self._update_view()

    def _build_related_md(self, parent, meeting_id) -> str:
        """Markdown for the agent-discovered cross-meeting links."""
        if meeting_id is None:
            return ""
        try:
            links = parent.store.get_links(meeting_id)
        except Exception:
            return ""
        if not links:
            return ""
        lines = ["## Related meetings", "",
                 "_Linked automatically by the cross-link agent — click one to open it._", ""]
        for l in links:
            rec = parent.store.get_meeting(l["related_id"])
            title = (rec.get("title") if rec else None) or f"Meeting #{l['related_id']}"
            rel = (l.get("relation") or "related").replace("_", " ")
            reason = f" — {l['reason']}" if l.get("reason") else ""
            lines.append(f"- **[{title}](meetgraph:meeting/{l['related_id']})** ({rel}){reason}")
        return "\n".join(lines)

    def _current_md(self) -> str:
        scope = self._scope()
        related = f"\n\n---\n\n{self._related_md}" if self._related_md else ""
        if scope == "summary":
            return self._summary_md + related
        if scope == "transcript":
            return f"## Full transcript\n\n{self._transcript_md}"
        return f"{self._summary_md}{related}\n\n---\n\n## Full transcript\n\n{self._transcript_md}"

    def _update_view(self) -> None:
        self._view.setMarkdown(self._current_md())

    def _export(self) -> str | None:
        scope = self._scope()
        suffix = {"summary": "-summary", "transcript": "-transcript"}.get(scope, "")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export meeting",
            f"meetgraph-{datetime.now():%Y%m%d-%H%M}{suffix}.md", "Markdown (*.md)"
        )
        if not path:
            return None
        if not path.endswith(".md"):
            path += ".md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._current_md())
        # JSON only makes sense when the summary is included.
        if self._json and scope != "transcript":
            with open(path[:-3] + ".json", "w", encoding="utf-8") as f:
                f.write(self._json)
        return path

    def _prev_ids(self) -> list:
        """The immediately-preceding meeting of the same user (a series chain)."""
        try:
            ms = self._parent.store.list_meetings(user=self._rec.get("user"), limit=1000)
            earlier = [m.id for m in ms if self._mid and m.id < self._mid]
            return [max(earlier)] if earlier else []
        except Exception:
            return []

    def _export_rdf(self) -> None:
        import json as _json

        from . import kg

        try:
            summary = _json.loads(self._json) if self._json else {}
        except Exception:
            summary = {}
        path, selected = QFileDialog.getSaveFileName(
            self, "Export RDF (knowledge graph)",
            f"meetgraph-{datetime.now():%Y%m%d-%H%M}.jsonld",
            "JSON-LD (*.jsonld);;Turtle (*.ttl);;N-Quads (*.nq)",
        )
        if not path:
            return
        if path.endswith(".ttl"):
            fmt = "turtle"
        elif path.endswith(".nq"):
            fmt = "nquads"
        elif path.endswith((".jsonld", ".json")):
            fmt = "jsonld"
        else:
            fmt = {"Turtle (*.ttl)": "turtle", "N-Quads (*.nq)": "nquads"}.get(selected, "jsonld")
            path += kg.EXTENSIONS[fmt]
        try:
            data = kg.serialize_meeting(self._rec, summary, prev_ids=self._prev_ids(), fmt=fmt)
            with open(path, "wb") as f:
                f.write(data)
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", f"Could not export RDF: {exc}")
            return
        reveal_in_file_manager(path)

    def _share(self) -> None:
        path = self._export()
        if path:
            reveal_in_file_manager(path)

    def _rename(self) -> None:
        from PyQt6.QtWidgets import QInputDialog

        new, ok = QInputDialog.getText(self, "Rename meeting", "Meeting name:",
                                       text=self._rec.get("title") or "")
        new = new.strip()
        if not ok or not new or new == (self._rec.get("title") or ""):
            return
        self._rec["title"] = new
        self.setWindowTitle(f"MeetGraph — {new}" + ("  (shared)" if self._remote else ""))
        self._head.setText(new)
        try:
            if self._remote:  # update the shared DB record directly
                from .external import structured_sink
                rel = self._parent._current_external_cfg().relational
                if rel.enabled and rel.url:
                    structured_sink(rel).upsert(self._rec)
            else:
                self._parent.store.rename_meeting(self._mid, new)
                self._parent._audit("meeting_renamed", self._mid, new)
                self._parent._push_external_async(self._mid)  # re-sync the new title
        except Exception as exc:
            QMessageBox.warning(self, "Rename", f"Renamed locally, but sync failed: {exc}")
        self._parent._refresh_meetings()

    def _find_papers(self) -> None:
        if self._remote or self._mid is None:
            return
        self._papers_btn.setEnabled(False)
        self._papers_btn.setText("Searching…")

        def done():
            self._papers_btn.setText("Find papers")
            self._papers_btn.setEnabled(True)
            self.reload()  # show the attached publications

        self._parent._literature_async(self._mid, on_finish=done, force=True)

    def _email(self) -> None:
        md = self._current_md()
        subject = f"Meeting notes: {self._rec.get('title') or 'Meeting'}"
        EmailComposeDialog(
            self._parent, self._parent._default_recipients(), subject, md,
            self._parent._md_to_html(md), target_id=self._mid,
        ).exec()

    def _delete(self) -> None:
        if QMessageBox.question(
            self, "Delete meeting", "Delete this meeting from the local database? This cannot be undone."
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self._parent.store.delete_meeting(self._mid)
            self._parent._audit("meeting_deleted", self._mid, self._rec.get("title"))
            self._parent._delete_remote_async(self._mid)  # propagate deletion if policy allows
            self._parent._refresh_meetings()
        except Exception:
            pass
        self.accept()


class ActivityLogDialog(QDialog):
    """Shows the audit log - who did what, when (local; the same entries are
    mirrored to the centralized DB when a team database is configured)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("MeetGraph — activity log")
        self.setWindowIcon(app_icon())
        self.resize(720, 480)
        v = QVBoxLayout(self)
        head = QLabel("Activity log")
        head.setObjectName("HeaderTitle")
        v.addWidget(head)
        sub = QLabel("Every create, summary, delete, link, and sync — with the team member who did it.")
        sub.setObjectName("HeaderSubtitle")
        v.addWidget(sub)

        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["When", "Who", "Email", "Action", "Detail"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        try:
            rows = parent.store.list_audit(limit=1000)
        except Exception:
            rows = []
        table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            vals = [
                (e.get("ts") or "")[:19].replace("T", " "),
                e.get("actor_name") or "", e.get("actor_email") or "",
                e.get("action") or "", e.get("detail") or "",
            ]
            for c, val in enumerate(vals):
                table.setItem(r, c, QTableWidgetItem(str(val)))
        v.addWidget(table, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        v.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)


class TeamKeysDialog(QDialog):
    """View the team keys you've generated; copy or revoke them."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self._win = main_window
        self.setWindowTitle("Team keys")
        self.setWindowIcon(app_icon())
        self.resize(680, 420)
        v = QVBoxLayout(self)
        head = QLabel("Team keys you've issued")
        head.setObjectName("HeaderTitle")
        v.addWidget(head)
        sub = QLabel("Generate several keys (e.g. per group) and revoke any of them. Revoking records "
                     "it in the shared database so teammates can no longer join with that key.")
        sub.setObjectName("HeaderSubtitle")
        sub.setWordWrap(True)
        v.addWidget(sub)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Label", "Created", "Status", "Team"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#64748b; font-size:11px;")
        v.addWidget(self.status)

        row = QHBoxLayout()
        copy = QPushButton("Copy key")
        copy.clicked.connect(self._copy)
        row.addWidget(copy)
        revoke = QPushButton("Revoke key")
        revoke.setObjectName("danger")
        revoke.clicked.connect(self._revoke)
        row.addWidget(revoke)
        row.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)
        self._reload()

    def _reload(self) -> None:
        try:
            self._keys = self._win.store.list_team_keys()
        except Exception:
            self._keys = []
        self.table.setRowCount(len(self._keys))
        for r, k in enumerate(self._keys):
            cells = [
                k.get("label") or "(no label)",
                (k.get("created_at") or "")[:16].replace("T", " "),
                "Revoked" if k.get("revoked") else "Active",
                k.get("team_name") or k.get("team_id") or "",
            ]
            for c, val in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))

    def _selected(self) -> dict | None:
        r = self.table.currentRow()
        return self._keys[r] if 0 <= r < len(self._keys) else None

    def _copy(self) -> None:
        k = self._selected()
        if not k:
            self.status.setText("Select a key first.")
            return
        QApplication.clipboard().setText(k.get("key") or "")
        self.status.setText(f"Copied “{k.get('label') or k.get('key_id')}” to the clipboard.")

    def _revoke(self) -> None:
        k = self._selected()
        if not k:
            self.status.setText("Select a key first.")
            return
        if k.get("revoked"):
            self.status.setText("That key is already revoked.")
            return
        if QMessageBox.question(
            self, "Revoke key",
            f"Revoke “{k.get('label') or k.get('key_id')}”? Teammates will no longer be able to "
            "join with it (enforced via the shared database).",
        ) != QMessageBox.StandardButton.Yes:
            return
        kid = k.get("key_id")
        self._win.store.set_key_revoked(kid, True)
        self._win._audit("key_revoked", None, k.get("label") or kid)
        # If this is the key the user is active under, they immediately go
        # read-only (content stays accessible; no more writes to its shared DB).
        self._win._refresh_team_readonly()
        self._win._update_team_status()
        self._reload()
        self.status.setText("Revoked locally; recording in the shared database…")
        rel = self._win._current_external_cfg().relational
        email = self._win.user_email
        ts = datetime.now().isoformat(timespec="seconds")

        def work():
            if rel.enabled and rel.url:
                from .external import structured_sink
                structured_sink(rel).revoke_key(kid, email, ts)
                return "Revocation recorded in the shared database."
            return "Revoked locally (no shared database configured to broadcast it)."

        self._win._run_async(work, lambda m, ok: self.status.setText(("✓ " if ok else "⚠ ") + m))


class TeamsDialog(QDialog):
    """Switch between the teams you've joined. Each team is an isolated shared
    scope; a team whose key was revoked is read-only (view-only, no content loss)."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self._win = main_window
        self.setWindowTitle("Teams")
        self.setWindowIcon(app_icon())
        self.resize(640, 380)
        v = QVBoxLayout(self)
        head = QLabel("Teams you've joined")
        head.setObjectName("HeaderTitle")
        v.addWidget(head)
        sub = QLabel("Switch the active team to view and write to its shared database. Revoked teams "
                     "stay accessible read-only — switching to one lets you view its meetings, but new "
                     "ones won't sync there.")
        sub.setObjectName("HeaderSubtitle")
        sub.setWordWrap(True)
        v.addWidget(sub)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Team", "Joined", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(lambda *_: self._switch())
        v.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#64748b; font-size:11px;")
        v.addWidget(self.status)

        row = QHBoxLayout()
        switch = QPushButton("Switch to selected")
        switch.setObjectName("primary")
        switch.clicked.connect(self._switch)
        row.addWidget(switch)
        leave = QPushButton("Leave selected")
        leave.setObjectName("danger")
        leave.clicked.connect(self._leave)
        row.addWidget(leave)
        row.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)
        self._reload()

    def _revoked_ids(self) -> set:
        try:
            return {k.get("key_id") for k in self._win.store.list_team_keys() if k.get("revoked")}
        except Exception:
            return set()

    def _reload(self) -> None:
        try:
            self._teams = self._win.store.list_memberships()
        except Exception:
            self._teams = []
        revoked = self._revoked_ids()
        self.table.setRowCount(len(self._teams))
        for r, m in enumerate(self._teams):
            active = m.get("team_id") == self._win.team_id
            is_ro = (m.get("key_id") in revoked) or (active and self._win._team_readonly)
            status = "● Active" if active else ""
            if is_ro:
                status = (status + " · read-only").strip(" ·") or "read-only (revoked)"
            cells = [m.get("team_name") or m.get("team_id") or "",
                     (m.get("joined_at") or "")[:16].replace("T", " "), status]
            for c, val in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))

    def _selected(self) -> dict | None:
        r = self.table.currentRow()
        return self._teams[r] if 0 <= r < len(self._teams) else None

    def _switch(self) -> None:
        m = self._selected()
        if not m:
            self.status.setText("Select a team first.")
            return
        name = m.get("team_name") or m["team_id"]
        if m.get("key_id") in self._revoked_ids():
            self.status.setText(f"“{name}” key is revoked — view it read-only from the Summary "
                                "“Show” menu (can't be the active team).")
            return
        self._win._switch_team(m["team_id"])
        self._reload()
        if self._win.team_id == m["team_id"]:
            self.status.setText(f"Switched to “{name}”.")
        else:
            self.status.setText(f"“{name}” key was revoked — staying in personal mode; "
                                "view it read-only from the Summary “Show” menu.")

    def _leave(self) -> None:
        m = self._selected()
        if not m:
            self.status.setText("Select a team first.")
            return
        if QMessageBox.question(
            self, "Leave team",
            f"Leave “{m.get('team_name') or m['team_id']}”? Your local meetings stay; the team's "
            "shared content is untouched. You can rejoin later with a valid key.",
        ) != QMessageBox.StandardButton.Yes:
            return
        tid = m["team_id"]
        if tid == self._win.team_id:
            self._win._leave_team()  # removes membership + switches/clears active
        else:
            self._win.store.remove_membership(tid)
            self._win._update_team_status()
        self._reload()


class EmailComposeDialog(QDialog):
    """Compose + send a summary email to the team."""

    def __init__(self, main_window, recipients: list[str], subject: str,
                 text_md: str, html: str, target_id=None):
        super().__init__(main_window)
        self._win = main_window
        self._text = text_md
        self._html = html
        self._target_id = target_id
        self.setWindowTitle("Email summary")
        self.setWindowIcon(app_icon())
        self.resize(620, 560)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)
        form = QFormLayout()
        self.to_edit = QLineEdit(", ".join(recipients))
        self.to_edit.setPlaceholderText("recipient@example.com, …")
        form.addRow("To", self.to_edit)
        self.subject_edit = QLineEdit(subject)
        form.addRow("Subject", self.subject_edit)
        v.addLayout(form)

        preview = QTextBrowser()
        preview.setObjectName("transcript")
        preview.setMarkdown(text_md)
        v.addWidget(preview, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#64748b; font-size:11px;")
        v.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self._send)
        row.addWidget(self.send_btn)
        v.addLayout(row)

    def _send(self) -> None:
        from .email_send import parse_recipients

        recips = parse_recipients(self.to_edit.text())
        if not recips:
            self.status.setText("⚠ Add at least one recipient.")
            return
        self.send_btn.setEnabled(False)
        self.status.setText("Sending…")

        def done(msg, ok):
            self.status.setText(("✓ " if ok else "⚠ ") + msg)
            self.send_btn.setEnabled(True)
            if ok:
                QTimer.singleShot(700, self.accept)

        self._win._send_summary_email(
            recips, self.subject_edit.text().strip() or "Meeting notes",
            self._text, self._html, target_id=self._target_id, on_done=done)


class SendDialog(QDialog):
    """Send / sync one or many meetings to chosen destinations, skipping
    anything already delivered there."""

    DESTS = [
        ("email", "Email"), ("rest", "REST API"), ("mcp", "MCP server"),
        ("relational", "Relational database"), ("graph", "Graph database"),
    ]

    def __init__(self, main_window, meeting_ids, title: str = "Send"):
        super().__init__(main_window)
        self._win = main_window
        self._ids = list(meeting_ids)
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon())
        self.resize(440, 360)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)
        head = QLabel(f"Send {len(self._ids)} meeting(s) to:")
        head.setObjectName("HeaderTitle")
        v.addWidget(head)

        avail = main_window._destination_availability()
        self.checks: dict[str, QCheckBox] = {}
        for key, label in self.DESTS:
            cb = QCheckBox(label)
            if avail.get(key):
                cb.setChecked(True)
            else:
                cb.setEnabled(False)
                cb.setToolTip("Not configured — set it up in Configuration first.")
                cb.setText(f"{label}  (not configured)")
            self.checks[key] = cb
            v.addWidget(cb)

        self.skip_check = QCheckBox("Skip meetings already sent to that destination")
        self.skip_check.setChecked(True)
        v.addWidget(self.skip_check)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#64748b; font-size:11px;")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        v.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self._run)
        row.addWidget(self.send_btn)
        v.addLayout(row)

    def _run(self) -> None:
        dests = [k for k, cb in self.checks.items() if cb.isChecked() and cb.isEnabled()]
        if not dests:
            self.status.setText("⚠ Pick at least one destination.")
            return
        skip = self.skip_check.isChecked()
        ids, win = self._ids, self._win
        self.status.setText("Sending…")
        self.send_btn.setEnabled(False)

        def work():
            sent = skipped = 0
            errs: list[str] = []
            for mid in ids:
                rec = win.store.get_meeting(mid)
                if not rec:
                    continue
                for dest in dests:
                    if skip and win.store.is_sent(mid, dest):
                        skipped += 1
                        continue
                    try:
                        win._send_meeting_to(rec, dest)
                        win.store.mark_sent(mid, dest)
                        sent += 1
                    except Exception as exc:
                        errs.append(f"#{mid} {dest}: {exc}")
            try:
                from . import external
                entry = win.store.log_action(
                    "bulk_send", win._display_name, win.user_email, win.team_id or None, None,
                    f"{sent} sent, {skipped} skipped, {len(errs)} errors; dests={','.join(dests)}")
                xcfg = win._current_external_cfg()
                if xcfg.relational.enabled and xcfg.relational.url:
                    external.push_audit(entry, xcfg)
            except Exception:
                pass
            msg = f"Sent {sent}; skipped {skipped} already-sent."
            if errs:
                msg += f"  {len(errs)} error(s): " + " | ".join(errs[:3])
            return msg

        def done(msg, ok):
            self.status.setText(msg)
            self.send_btn.setEnabled(True)

        win._run_async(work, done)


class WelcomeDialog(QDialog):
    """First-run setup: capture the user's name and an optional meeting name.

    The name is shown only the first time - once saved it's reused silently.
    """

    def __init__(self, default_name: str = "", ask_name: bool = True, default_email: str = "",
                 current_team: str = ""):
        super().__init__()
        self.setWindowTitle("MeetGraph")
        self.setWindowIcon(app_icon())
        self.resize(480, 600)
        self.user_name = default_name
        self.user_email = default_email
        self.meeting_name = ""
        self.team_key = ""
        self.leave_team = False
        self._current_team = current_team
        self._ask_name = ask_name

        v = QVBoxLayout(self)
        v.setContentsMargins(26, 22, 26, 22)
        v.setSpacing(12)

        if LOGO_PATH.exists():
            logo = QLabel()
            logo.setPixmap(
                QPixmap(str(LOGO_PATH)).scaled(
                    QSize(180, 180), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(logo)

        greeting = QLabel(
            f"Welcome back, {default_name}!" if (not ask_name and default_name)
            else "Turning meetings into a knowledge graph"
        )
        greeting.setObjectName("HeaderTitle" if (not ask_name and default_name) else "HeaderSubtitle")
        greeting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(greeting)
        if not ask_name and default_name:
            sub = QLabel("Turning meetings into a knowledge graph")
            sub.setObjectName("HeaderSubtitle")
            sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(sub)
        v.addSpacing(6)

        self.name_edit = QLineEdit(default_name)
        self.email_edit = QLineEdit(default_email)
        if ask_name:
            lbl = QLabel("Your name")
            lbl.setStyleSheet("font-weight:600;")
            v.addWidget(lbl)
            self.name_edit.setPlaceholderText("used to label your speech (e.g. Tek Raj)")
            v.addWidget(self.name_edit)
            elbl = QLabel("Your email (optional — used for team activity logs)")
            elbl.setStyleSheet("font-weight:600;")
            v.addWidget(elbl)
            self.email_edit.setPlaceholderText("you@example.com")
            v.addWidget(self.email_edit)

        mlbl = QLabel("Meeting name (optional)")
        mlbl.setStyleSheet("font-weight:600;")
        v.addWidget(mlbl)
        self.meeting_edit = QLineEdit()
        self.meeting_edit.setPlaceholderText("e.g. Launch planning sync")
        self.meeting_edit.returnPressed.connect(self._continue)
        v.addWidget(self.meeting_edit)

        self.leave_check = None
        if current_team:
            info = QLabel(f"✓ You're in team: {current_team}")
            info.setStyleSheet("color:#0d9488; font-weight:600;")
            v.addWidget(info)
            self.leave_check = QCheckBox("Leave this team")
            v.addWidget(self.leave_check)

        tlbl = QLabel("Switch / join a team (optional)" if current_team else "Join a team (optional)")
        tlbl.setStyleSheet("font-weight:600;")
        v.addWidget(tlbl)
        trow = QHBoxLayout()
        self.team_key_edit = QLineEdit()
        self.team_key_edit.setPlaceholderText("Paste a team key to join — your notes sync to the shared database")
        self.team_key_edit.textChanged.connect(self._preview_key)
        trow.addWidget(self.team_key_edit, 1)
        self.team_key_status = QLabel("")
        self.team_key_status.setStyleSheet("font-size:11px;")
        trow.addWidget(self.team_key_status)
        v.addLayout(trow)
        thint = QLabel("Don't have a key? Continue, then create a team in Configuration once your "
                       "database is set — generated keys are shareable from there.")
        thint.setWordWrap(True)
        thint.setStyleSheet("color:#64748b; font-size:11px;")
        v.addWidget(thint)

        v.addStretch()
        cont = QPushButton("Continue →")
        cont.setObjectName("primary")
        cont.clicked.connect(self._continue)
        v.addWidget(cont)

    def _preview_key(self) -> None:
        t = self.team_key_edit.text().strip()
        if not t:
            self.team_key_status.setText("")
            return
        try:
            from . import team
            p = team.parse_team_key(t)
            self.team_key_status.setText(f"→ join {p['team'] or 'team'}")
            self.team_key_status.setStyleSheet("color:#0d9488; font-size:11px;")
        except Exception:
            self.team_key_status.setText("⚠ invalid")
            self.team_key_status.setStyleSheet("color:#dc2626; font-size:11px;")

    def _continue(self) -> None:
        if self.leave_check is not None:
            self.leave_team = self.leave_check.isChecked()
        if self._ask_name:
            self.user_name = self.name_edit.text().strip()
            self.user_email = self.email_edit.text().strip()
        self.meeting_name = self.meeting_edit.text().strip()
        key = self.team_key_edit.text().strip()
        if key:
            from . import team
            try:
                team.parse_team_key(key)  # validate before proceeding
            except ValueError:
                self.team_key_status.setText("⚠ invalid key")
                self.team_key_status.setStyleSheet("color:#dc2626; font-size:11px;")
                return
            self.team_key = key
        self.accept()


def _ensure_chevron_icon() -> str:
    """Render a clean down-chevron PNG for the combo-box arrow (needs a QApp)."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
    from .storage import data_dir

    path = data_dir() / "chevron.png"
    pm = QPixmap(18, 18)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#64748b"))
    pen.setWidth(2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPolyline(QPolygonF([QPointF(5, 7), QPointF(9, 11), QPointF(13, 7)]))
    p.end()
    pm.save(str(path))
    return str(path)


def run() -> None:
    import sys

    app = QApplication(sys.argv)
    app.setApplicationName("MeetGraph")
    app.setApplicationDisplayName("MeetGraph")
    app.setWindowIcon(app_icon())

    stylesheet = STYLESHEET
    try:
        chevron = _ensure_chevron_icon().replace("\\", "/")
        stylesheet += (
            f"\nQComboBox::down-arrow {{ image: url('{chevron}'); "
            f"width: 14px; height: 14px; margin-right: 9px; }}\n"
        )
    except Exception:
        pass
    app.setStyleSheet(stylesheet)

    from .storage import Store

    store = Store()
    saved_name = (store.get_setting("user_name") or "").strip()
    saved_email = (store.get_setting("user_email") or "").strip()

    # Show the welcome screen only when we don't yet know the user's name;
    # afterwards the saved name is reused silently. The meeting name is asked
    # each run (it's optional and changes meeting-to-meeting).
    current_team = (store.get_setting("team.name") or "").strip()
    dlg = WelcomeDialog(default_name=saved_name, ask_name=not saved_name,
                        default_email=saved_email, current_team=current_team)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return  # closing the welcome screen (X / Esc) exits the app

    user_name = saved_name or dlg.user_name
    if dlg.user_name and not saved_name:
        store.set_setting("user_name", dlg.user_name)
    user_email = saved_email or dlg.user_email
    if dlg.user_email and not saved_email:
        store.set_setting("user_email", dlg.user_email)

    # Leaving the team on the welcome screen clears the membership.
    left_team = ""
    if dlg.leave_team and current_team:
        prev_tid = (store.get_setting("team.id") or "").strip()
        store.set_setting("team.id", "")
        store.set_setting("team.name", "")
        if prev_tid:
            store.remove_membership(prev_tid)
        left_team = current_team

    # Quick join: a team key pasted on the welcome screen applies the shared
    # database config + team identity before the window builds.
    joined_team = ""
    if dlg.team_key:
        from . import external, team

        try:
            parsed = team.parse_team_key(dlg.team_key)
            external.save_config(store.set_setting, parsed["external"])
            store.set_setting("team.id", parsed["id"])
            store.set_setting("team.name", parsed["team"])
            from datetime import datetime as _dt
            store.add_membership(parsed["id"], parsed["team"], parsed.get("key_id") or "",
                                 dlg.team_key, _dt.now().isoformat(timespec="seconds"))
            joined_team = parsed["team"]
        except Exception:
            pass

    win = MainWindow(user_name=user_name, meeting_name=dlg.meeting_name, user_email=user_email)
    if left_team and not joined_team:
        win._audit("team_left", None, left_team)
    if joined_team:
        win._audit("team_joined", None, joined_team)
    win.show()
    sys.exit(app.exec())
