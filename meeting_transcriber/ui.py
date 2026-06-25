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
        self.meeting_name = meeting_name.strip()
        self._started_at = None
        self._meeting_id = None
        self._last_summary_md = ""    # the live/current meeting's summary
        self._last_summary_json = ""
        self._view_md = ""            # detail view (Summary tab)
        self._view_json = ""
        self._summary_dirty = False   # new speech since last summary
        self._notes_busy = False      # a summary generation is in flight
        self._loading = True  # suppress config saves while widgets are built/loaded

        self._build_ui()
        self._wire_controller()
        self._load_config()
        self._wire_config_persistence()
        self._loading = False

    # ---------------------------------------------------------------- UI build
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        root.addLayout(self._build_header())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_record_tab(), "  ◉  Record  ")
        self.tabs.addTab(self._build_summary_tab(), "  ✦  Summary  ")
        self.tabs.addTab(self._build_config_tab(), "  ⚙  Configuration  ")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("statusBar")
        root.addWidget(self.status_label)

        self._populate_devices()
        self._on_engine_changed()

    # --------------------------------------------------------------- tabs
    def _build_record_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("RecordPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(2, 10, 2, 2)
        v.setSpacing(10)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        self.start_btn = QPushButton("● Start")
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
        refresh = QPushButton("↻ Refresh")
        refresh.clicked.connect(self._refresh_meetings)
        srow.addWidget(refresh)
        graph_btn = QPushButton("⬡ Export graph")
        graph_btn.setToolTip("Export all meetings as one connected knowledge graph "
                             "(JSON-LD / Turtle) — key terms linked to Wikipedia/Wikidata, "
                             "meetings chained to their predecessors.")
        graph_btn.clicked.connect(self._export_graph)
        srow.addWidget(graph_btn)
        v.addLayout(srow)

        self.meetings_table = QTableWidget(0, 4)
        self.meetings_table.setHorizontalHeaderLabels(["Meeting", "Date", "Participant", "Summary"])
        self.meetings_table.verticalHeader().setVisible(False)
        self.meetings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.meetings_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.meetings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.meetings_table.setSortingEnabled(True)
        self.meetings_table.setCursor(Qt.CursorShape.PointingHandCursor)
        hh = self.meetings_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
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
        # Leaving Configuration → warm up the configured models so there's no
        # cold-start download when the user hits Start.
        if getattr(self, "_prev_tab_text", "").endswith("Configuration") and not text.endswith("Configuration"):
            self._maybe_prewarm()
        self._prev_tab_text = text

    # ----- meetings table (Summary tab) -----
    def _refresh_meetings(self) -> None:
        if not hasattr(self, "meetings_table"):
            return
        query = self.search_edit.text() if hasattr(self, "search_edit") else ""
        try:
            meetings = self.store.search_meetings(query)
        except Exception as exc:
            self.meetings_count.setText(f"⚠ {exc}")
            return
        self.meetings_table.setSortingEnabled(False)
        self.meetings_table.setRowCount(0)
        for m in meetings:
            r = self.meetings_table.rowCount()
            self.meetings_table.insertRow(r)
            when = (m.started_at or m.created_at or "")[:16].replace("T", " ")
            title_item = QTableWidgetItem(m.title or "Meeting")
            title_item.setData(Qt.ItemDataRole.UserRole, m.id)
            self.meetings_table.setItem(r, 0, title_item)
            self.meetings_table.setItem(r, 1, QTableWidgetItem(when))
            self.meetings_table.setItem(r, 2, QTableWidgetItem(m.user or ""))
            self.meetings_table.setItem(r, 3, QTableWidgetItem("✦ yes" if m.summary_md else "—"))
        self.meetings_table.setSortingEnabled(True)
        self.meetings_count.setText(
            (f"{len(meetings)} meeting(s)" + (f" matching “{query.strip()}”" if query.strip() else ""))
            + " · click a row to open"
        )

    def _open_meeting_detail(self, row: int, _col: int = 0) -> None:
        cell = self.meetings_table.item(row, 0)
        mid = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if mid is None:
            return
        rec = self.store.get_meeting(mid)
        if not rec:
            QMessageBox.information(self, "Not found", "Meeting not found.")
            return
        MeetingDetailDialog(self, rec).exec()

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
        v.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        scroll.viewport().setStyleSheet("background: transparent;")
        return scroll

    def _build_engine_box(self) -> QGroupBox:
        engine_box = QGroupBox("Transcription engine")
        engine_layout = QVBoxLayout(engine_box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Engine:"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Local — Whisper (faster-whisper / Apple MLX)", "local")
        self.engine_combo.addItem("OpenAI (Whisper / GPT-4o transcribe)", "openai")
        self.engine_combo.addItem("OpenAI-compatible — Groq, local server, custom…", "compatible")
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        row.addWidget(self.engine_combo)
        row.addWidget(QLabel("Language:"))
        self.lang_edit = QLineEdit()
        self.lang_edit.setPlaceholderText("auto (e.g. en, es, fr)")
        self.lang_edit.setMaximumWidth(160)
        row.addWidget(self.lang_edit)
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
        self.openai_model_combo.addItems(
            ["whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"]
        )
        openai_l.addWidget(self.openai_model_combo)
        self.engine_stack.addWidget(openai_w)

        # OpenAI-compatible (Groq, OpenRouter, Anthropic, self-hosted, custom…)
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

        # HuggingFace token — optional; only used to download local Whisper models
        # faster / past anonymous rate limits.
        hf_row = QHBoxLayout()
        hf_row.addWidget(QLabel("HuggingFace token (optional):"))
        self.hf_token_edit = QLineEdit()
        self.hf_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.hf_token_edit.setPlaceholderText("hf_…  — speeds up local-model downloads (not required)")
        self.hf_token_edit.setText(os.environ.get("HF_TOKEN", os.environ.get("HUGGING_FACE_HUB_TOKEN", "")))
        hf_row.addWidget(self.hf_token_edit, 1)
        engine_layout.addLayout(hf_row)
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

        # --- Relational ---
        self.ext_rel_enable = QCheckBox("Relational database (PostgreSQL / MySQL / SQLite via SQLAlchemy)")
        outer.addWidget(self.ext_rel_enable)
        rel_form = QFormLayout()
        rel_form.setContentsMargins(22, 0, 0, 0)
        self.ext_rel_url = QLineEdit()
        self.ext_rel_url.setPlaceholderText("postgresql+psycopg://host:5432/dbname  (credentials optional below)")
        rel_form.addRow("Connection URL", self.ext_rel_url)
        self.ext_rel_user = QLineEdit()
        self.ext_rel_user.setPlaceholderText("optional — or embed in the URL")
        rel_form.addRow("Username", self.ext_rel_user)
        self.ext_rel_pass = QLineEdit()
        self.ext_rel_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ext_rel_pass.setPlaceholderText("optional — password or access token")
        rel_form.addRow("Password / token", self.ext_rel_pass)
        rel_hint = QLabel("Needs SQLAlchemy + a driver (e.g. psycopg2-binary, pymysql). "
                          "Writes a meetgraph_meetings table. Username/password here are "
                          "merged into the URL if set.")
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
        self.ext_graph_enable = QCheckBox("Graph database / triplestore (SPARQL — Oxigraph, Fuseki, GraphDB…)")
        outer.addWidget(self.ext_graph_enable)
        g_form = QFormLayout()
        g_form.setContentsMargins(22, 0, 0, 0)
        self.ext_graph_store = QLineEdit()
        self.ext_graph_store.setPlaceholderText("http://localhost:7878/store   (Graph Store Protocol — preferred)")
        g_form.addRow("Graph Store URL", self.ext_graph_store)
        self.ext_graph_update = QLineEdit()
        self.ext_graph_update.setPlaceholderText("http://localhost:7878/update   (SPARQL Update — fallback)")
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
        g_hint = QLabel("Each meeting is written as its own named graph (replaced on re-sync), "
                        "with key terms linked to Wikipedia/Wikidata.")
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
        leave = QPushButton("Leave team")
        leave.clicked.connect(self._leave_team)
        btns.addWidget(leave)
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

    def _update_team_status(self) -> None:
        if getattr(self, "team_status", None) is None:
            return
        if self.team_id:
            self.team_status.setText(f"✓ In team “{self.team_name or self.team_id}” — meetings sync to the shared database.")
        else:
            self.team_status.setText("Not in a team. Generate a key to start one, or paste a key to join.")

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

        row3 = QHBoxLayout()
        self.auto_notes = QCheckBox("Auto-generate notes when I Stop")
        self.auto_notes.setChecked(True)
        row3.addWidget(self.auto_notes)
        row3.addStretch()
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
        self.compat_provider.currentIndexChanged.connect(self._persist_config)
        self.compat_base.textChanged.connect(self._persist_config)
        self.compat_key.textChanged.connect(self._persist_config)
        self.compat_model.currentTextChanged.connect(self._persist_config)
        self.mic_combo.currentIndexChanged.connect(self._persist_config)
        self.sys_combo.currentIndexChanged.connect(self._persist_config)
        self.hf_token_edit.textChanged.connect(self._persist_config)
        self.compute_combo.currentIndexChanged.connect(self._persist_config)
        self._wire_external_persistence()

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
        # NB: live "Auto" summary is intentionally NOT persisted — it always
        # starts on so summaries generate automatically with no button.
        s("t.engine", self.engine_combo.currentData() or "")
        s("t.language", self.lang_edit.text())
        s("t.local_model", self.model_combo.currentText())
        s("t.openai_key", self.api_key_edit.text())
        s("t.openai_model", self.openai_model_combo.currentText())
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
        # live "Auto" summary is not restored from settings — always starts on.
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

    # ----- external databases -----
    def _wire_external_persistence(self) -> None:
        for w in (self.ext_rel_enable, self.ext_graph_enable):
            w.toggled.connect(self._persist_external)
        for w in (self.ext_rel_url, self.ext_rel_user, self.ext_rel_pass,
                  self.ext_graph_store, self.ext_graph_update, self.ext_graph_query,
                  self.ext_graph_name, self.ext_graph_user, self.ext_graph_pass):
            w.textChanged.connect(self._persist_external)

    def _persist_external(self) -> None:
        if self._loading:
            return
        s = self.store.set_setting
        s("ext.rel.enabled", "1" if self.ext_rel_enable.isChecked() else "0")
        s("ext.rel.url", self.ext_rel_url.text().strip())
        s("ext.rel.user", self.ext_rel_user.text().strip())
        s("ext.rel.password", self.ext_rel_pass.text())
        s("ext.graph.enabled", "1" if self.ext_graph_enable.isChecked() else "0")
        s("ext.graph.graph_store_url", self.ext_graph_store.text().strip())
        s("ext.graph.update_url", self.ext_graph_update.text().strip())
        s("ext.graph.query_url", self.ext_graph_query.text().strip())
        s("ext.graph.named_graph", self.ext_graph_name.text().strip())
        s("ext.graph.user", self.ext_graph_user.text().strip())
        s("ext.graph.password", self.ext_graph_pass.text())

    def _load_external_config(self) -> None:
        # Suppress per-widget persistence while loading, or each setText() would
        # re-save (clobbering fields not yet loaded in this pass).
        prev, self._loading = self._loading, True
        try:
            g = self.store.get_setting
            self.ext_rel_enable.setChecked(g("ext.rel.enabled") == "1")
            self.ext_rel_url.setText(g("ext.rel.url") or "")
            self.ext_rel_user.setText(g("ext.rel.user") or "")
            self.ext_rel_pass.setText(g("ext.rel.password") or "")
            self.ext_graph_enable.setChecked(g("ext.graph.enabled") == "1")
            self.ext_graph_store.setText(g("ext.graph.graph_store_url") or "")
            self.ext_graph_update.setText(g("ext.graph.update_url") or "")
            self.ext_graph_query.setText(g("ext.graph.query_url") or "")
            from .kg import MEETGRAPH_NG
            self.ext_graph_name.setText(g("ext.graph.named_graph") or MEETGRAPH_NG)
            self.ext_graph_user.setText(g("ext.graph.user") or "")
            self.ext_graph_pass.setText(g("ext.graph.password") or "")
        finally:
            self._loading = prev

    def _current_external_cfg(self):
        from .external import ExternalConfig, GraphConfig, RelationalConfig

        return ExternalConfig(
            relational=RelationalConfig(
                enabled=self.ext_rel_enable.isChecked(),
                url=self.ext_rel_url.text().strip(),
                user=self.ext_rel_user.text().strip(),
                password=self.ext_rel_pass.text(),
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
        from .external import RelationalSink

        rel = self._current_external_cfg().relational
        self.ext_rel_status.setText("Testing…")
        self._run_async(
            lambda: RelationalSink(rel.url, rel.user, rel.password).test(),
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

    def _push_external_async(self, meeting_id) -> None:
        """Mirror one meeting to any enabled external DB, in the background."""
        if meeting_id is None:
            return
        cfg = self._current_external_cfg()
        if not (cfg.relational.enabled or cfg.graph.enabled):
            return
        from . import external

        def work():
            rec = self.store.get_meeting(meeting_id)
            if not rec:
                return "no record"
            prev = self._prev_meeting_id(meeting_id, rec.get("user"))
            res = external.push_meeting(rec, cfg, [prev] if prev else None)
            bad = [f"{k}: {v}" for k, v in res.items() if v != "ok"]
            return "External sync failed — " + "; ".join(bad) if bad else "ok"

        def report(msg, ok):
            if msg not in ("ok", "OK"):
                self.status_label.setText(f"⚠ {msg}")

        self._run_async(work, report)

    def _sync_all_external(self) -> None:
        from . import external

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
            recs = [r for r in (self.store.get_meeting(i) for i in ids) if r]
            recs.sort(key=lambda r: r["id"])
            errs: list[str] = []
            # Relational: upsert each meeting (idempotent).
            if cfg.relational.enabled and cfg.relational.url:
                rs = external.RelationalSink(
                    cfg.relational.url, cfg.relational.user, cfg.relational.password)
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
        tid = self.team_id or team.new_team_id()
        name = self.team_name_edit.text().strip() or "My Team"
        key = team.make_team_key(name, tid, cfg)
        self.team_id, self.team_name = tid, name
        self.store.set_setting("team.id", tid)
        self.store.set_setting("team.name", name)
        self._update_team_status()
        self._audit("team_key_generated", None, name)
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
        # Apply the shared external DB config into the widgets (guarded), then enable.
        ext = parsed["external"]
        prev, self._loading = self._loading, True
        try:
            self.ext_rel_enable.setChecked(ext.relational.enabled)
            self.ext_rel_url.setText(ext.relational.url)
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
        self._persist_external()
        self.team_id, self.team_name = parsed["id"], parsed["team"]
        self.store.set_setting("team.id", self.team_id)
        self.store.set_setting("team.name", self.team_name)
        self._update_team_status()
        self._audit("team_joined", None, self.team_name)
        QMessageBox.information(
            self, "Joined team",
            f"You're now in “{self.team_name}”. Your meetings will sync to the shared database.")

    def _leave_team(self) -> None:
        if not self.team_id:
            return
        self._audit("team_left", None, self.team_name)
        self.team_id, self.team_name = "", ""
        self.store.set_setting("team.id", "")
        self.store.set_setting("team.name", "")
        self._update_team_status()

    def _show_activity_log(self) -> None:
        ActivityLogDialog(self).exec()

    def _crosslink_async(self, meeting_id) -> None:
        """Let the agent link this meeting to related ones, across the team if centralized."""
        if meeting_id is None:
            return
        cfg = self._current_external_cfg()
        provider_cfg = {
            "provider": self.ai_provider.currentData(),
            "model": self.ai_model.currentText().strip(),
            "api_key": self.ai_key.text().strip(),
            "base_url": self.ai_base.text().strip(),
        }
        name, email, team_id = self._display_name, self.user_email, self.team_id or None

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
            if cfg.relational.enabled or cfg.graph.enabled:
                prev = self._prev_meeting_id(meeting_id, rec.get("user"))
                external.push_meeting(rec, cfg, [prev] if prev else None)
            try:
                entry = self.store.log_action("cross_linked", name, email, team_id, meeting_id,
                                              f"{len(links)} link(s)")
                if cfg.relational.enabled and cfg.relational.url:
                    external.push_audit(entry, cfg)
            except Exception:
                pass
            return f"Linked {len(links)} related meeting(s)." if links else "No related meetings found."

        self._run_async(work, lambda msg, ok: msg and self._set_summary_status(msg))

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
        self._notes_busy = True
        self._summary_dirty = False
        self.summary_btn.setEnabled(False)
        self._set_summary_status("Summarizing…")
        worker = NotesWorker(config, self.transcript.to_plain(), title=self.meeting_name or None)
        worker.done.connect(self._on_notes_done)
        worker.failed.connect(self._on_notes_failed)
        self._notes_worker = worker  # keep a reference
        threading.Thread(target=worker.run, daemon=True).start()

    def _autogen_notes(self) -> None:
        if self.auto_notes.isChecked() and self._notes_ready():
            self._run_notes()

    def _on_summary_tick(self) -> None:
        # Auto-summarize as the meeting goes — only when there's new speech.
        if (self.controller.running and self.auto_refresh.isChecked()
                and self._summary_dirty and not self._notes_busy and self._notes_ready()):
            self._run_notes()

    def _on_notes_done(self, markdown: str, json_text: str) -> None:
        self._notes_busy = False
        self._last_summary_md = markdown
        self._last_summary_json = json_text
        self.summary_btn.setEnabled(True)
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
                self._audit("summary_generated", self._meeting_id)
                self._crosslink_async(self._meeting_id)

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
        if self.mic_check.isChecked():
            dev = self._device_by_index(self.mic_combo.currentData())
            if dev:
                sources.append((dev, self.speaker_self))
        if self.sys_check.isChecked():
            dev = self._device_by_index(self.sys_combo.currentData())
            if dev:
                sources.append((dev, "Meeting"))
        if not sources:
            QMessageBox.warning(self, "No source", "Enable at least one audio source.")
            return

        sel = self.compute_combo.currentData() or "auto"
        compute_type = {"cpu": "int8", "cuda": "float16"}.get(sel, "auto")
        engine = self.engine_combo.currentData()
        config = {
            "engine": engine,
            "language": self.lang_edit.text().strip(),
            "model_size": self.model_combo.currentText().strip(),
            "device": sel,            # auto | cpu | cuda | mlx (resolved in make_transcriber)
            "compute_type": compute_type,
            "api_key": self.api_key_edit.text().strip(),
            "openai_model": self.openai_model_combo.currentText(),
        }
        if engine == "compatible":
            config["api_key"] = self.compat_key.text().strip()
            config["base_url"] = self.compat_base.text().strip()
            config["openai_model"] = self.compat_model.currentText().strip()
            if not config["base_url"]:
                QMessageBox.warning(self, "Missing URL", "Enter the OpenAI-compatible base URL.")
                return
        if engine == "openai" and not config["api_key"]:
            QMessageBox.warning(self, "Missing key", "Enter your OpenAI API key.")
            return

        # Start always begins a NEW meeting — clear the previous transcript & summary.
        self.transcript.clear()
        self.transcript_view.clear()
        self.summary_view.clear()
        self._last_summary_md = ""
        self._last_summary_json = ""
        self._view_md = ""
        self._view_json = ""
        self._meeting_id = None

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
            self.status_label.setText(f"Saved transcript to local database (#{self._meeting_id}).")
            self._refresh_meetings()
            self._audit("meeting_saved", self._meeting_id, self.meeting_name or default_title)
            self._push_external_async(self._meeting_id)  # mirror to external DB(s)
        except Exception as exc:
            self.status_label.setText(f"⚠ Could not save to database: {exc}")

    def _set_settings_enabled(self, enabled: bool) -> None:
        for w in (
            self.engine_combo, self.model_combo, self.api_key_edit,
            self.openai_model_combo, self.compat_provider, self.compat_base,
            self.compat_key, self.compat_model, self.lang_edit, self.mic_check,
            self.sys_check, self.mic_combo, self.sys_combo,
        ):
            w.setEnabled(enabled)

    def _on_new_text(self, speaker: str, ts: datetime, text: str) -> None:
        self.transcript.add(speaker, text, when=ts)
        self._summary_dirty = True  # triggers auto-summary on the next tick
        if speaker == self.speaker_self:
            color = SPEAKER_COLORS["You"]  # the local user keeps the blue chip
        else:
            color = SPEAKER_COLORS.get(speaker, SPEAKER_COLORS["Meeting"])
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
                    t.transcribe(np.zeros(8000, dtype=np.float32))  # 0.5s silence → forces load
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
                    pass  # ollama not installed — silently skip
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
    """Runs the (provider-agnostic) Pydantic AI notes agent off the GUI thread."""

    done = pyqtSignal(str, str)  # markdown, json
    failed = pyqtSignal(str)

    def __init__(self, config: dict, transcript_text: str, title: str | None):
        super().__init__()
        self.config = config
        self.transcript_text = transcript_text
        self.title = title

    def run(self) -> None:
        try:
            from .agent import MeetingNotesAgent, link_key_terms, summary_to_markdown

            agent = MeetingNotesAgent(
                provider=self.config["provider"],
                model_name=self.config.get("model") or None,
                api_key=self.config.get("api_key") or None,
                base_url=self.config.get("base_url") or None,
            )
            summary = agent.summarize(self.transcript_text, title=self.title)
            link_key_terms(summary)  # resolve key terms -> Wikipedia / Wikidata (best-effort)
            self.done.emit(
                summary_to_markdown(summary, title=self.title),
                summary.model_dump_json(indent=2),
            )
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

    def __init__(self, parent, rec: dict):
        super().__init__(parent)
        self._parent = parent
        self._rec = rec
        self._mid = rec.get("id")
        self._json = rec.get("summary_json") or ""
        title = rec.get("title") or "Meeting"
        self.setWindowTitle(f"MeetGraph — {title}")
        self.setWindowIcon(app_icon())
        self.resize(780, 700)

        self._summary_md = rec.get("summary_md") or f"# {title}\n\n_No summary was generated._"
        self._transcript_md = rec.get("transcript_md") or "_No transcript._"
        self._related_md = self._build_related_md(parent, rec.get("id"))

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)

        head = QLabel(title)
        head.setObjectName("HeaderTitle")
        v.addWidget(head)
        when = (rec.get("started_at") or rec.get("created_at") or "")[:16].replace("T", " ")
        sub = QLabel(f"{when}   ·   {rec.get('user') or ''}")
        sub.setObjectName("HeaderSubtitle")
        v.addWidget(sub)

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
        self._view.setOpenExternalLinks(True)  # clickable Wikipedia/Wikidata links
        self._view.setFont(QFont("SF Pro Text", 13))
        v.addWidget(self._view, 1)
        self._update_view()

        row = QHBoxLayout()
        row.setSpacing(8)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self._current_md()))
        row.addWidget(copy)
        exp = QPushButton("Export .md")
        exp.setObjectName("primary")
        exp.clicked.connect(self._export)
        row.addWidget(exp)
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
        row.addWidget(delete)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)

    def _scope(self) -> str:
        return self.scope_combo.currentData()

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
        lines = ["## Related meetings", "", "_Linked automatically by the cross-link agent._", ""]
        for l in links:
            rec = parent.store.get_meeting(l["related_id"])
            title = (rec.get("title") if rec else None) or f"Meeting #{l['related_id']}"
            rel = (l.get("relation") or "related").replace("_", " ")
            reason = f" — {l['reason']}" if l.get("reason") else ""
            lines.append(f"- **{title}** ({rel}){reason}")
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

    def _delete(self) -> None:
        if QMessageBox.question(
            self, "Delete meeting", "Delete this meeting from the local database? This cannot be undone."
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self._parent.store.delete_meeting(self._mid)
            self._parent._audit("meeting_deleted", self._mid, self._rec.get("title"))
            self._parent._refresh_meetings()
        except Exception:
            pass
        self.accept()


class ActivityLogDialog(QDialog):
    """Shows the audit log — who did what, when (local; the same entries are
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


class WelcomeDialog(QDialog):
    """First-run setup: capture the user's name and an optional meeting name.

    The name is shown only the first time — once saved it's reused silently.
    """

    def __init__(self, default_name: str = "", ask_name: bool = True, default_email: str = ""):
        super().__init__()
        self.setWindowTitle("MeetGraph")
        self.setWindowIcon(app_icon())
        self.resize(480, 560)
        self.user_name = default_name
        self.user_email = default_email
        self.meeting_name = ""
        self.team_key = ""
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

        tlbl = QLabel("Join a team (optional)")
        tlbl.setStyleSheet("font-weight:600;")
        v.addWidget(tlbl)
        trow = QHBoxLayout()
        self.team_key_edit = QLineEdit()
        self.team_key_edit.setPlaceholderText("Paste a team key to join — your notes sync to the shared database")
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

    def _continue(self) -> None:
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
    dlg = WelcomeDialog(default_name=saved_name, ask_name=not saved_name, default_email=saved_email)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return  # closing the welcome screen (X / Esc) exits the app

    user_name = saved_name or dlg.user_name
    if dlg.user_name and not saved_name:
        store.set_setting("user_name", dlg.user_name)
    user_email = saved_email or dlg.user_email
    if dlg.user_email and not saved_email:
        store.set_setting("user_email", dlg.user_email)

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
            joined_team = parsed["team"]
        except Exception:
            pass

    win = MainWindow(user_name=user_name, meeting_name=dlg.meeting_name, user_email=user_email)
    if joined_team:
        win._audit("team_joined", None, joined_team)
    win.show()
    sys.exit(app.exec())
