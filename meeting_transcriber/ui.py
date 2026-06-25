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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .audio import find_system_audio_device, list_input_devices
from .controller import TranscriptionController
from .transcript import Transcript, reveal_in_file_manager

SPEAKER_COLORS = {"You": "#2563eb", "Meeting": "#0d9488"}

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
    def __init__(self, user_name: str = "", meeting_name: str = "") -> None:
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
        self.speaker_self = user_name.strip() or "You"
        self._display_name = user_name.strip() or "Local"
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
        self.auto_refresh.setToolTip("Summarize automatically as the meeting goes")
        srow.addWidget(self.auto_refresh)
        self.summary_btn = QPushButton("⟳")
        self.summary_btn.setToolTip("Refresh the summary now")
        self.summary_btn.setMaximumWidth(40)
        self.summary_btn.clicked.connect(self._run_notes)
        srow.addWidget(self.summary_btn)
        self.live_copy_btn = QPushButton("Copy")
        self.live_copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self._last_summary_md))
        srow.addWidget(self.live_copy_btn)
        rl.addLayout(srow)
        self.summary_view = QTextEdit()
        self.summary_view.setObjectName("transcript")
        self.summary_view.setReadOnly(True)
        self.summary_view.setFont(QFont("SF Pro Text", 13))
        self.summary_view.setPlaceholderText(
            "A live summary (topics · decisions · open questions · action items) "
            "appears here automatically as you talk."
        )
        rl.addWidget(self.summary_view, 1)
        split.addWidget(right)
        split.setSizes([540, 430])
        v.addWidget(split, 1)

        # Live auto-summary timer (fires while recording + "Auto" on + new speech).
        self._summary_timer = QTimer(self)
        self._summary_timer.setInterval(25_000)
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
        if self.tabs.tabText(index).strip().endswith("Summary"):
            self._refresh_meetings()

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

    def _build_config_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ConfigPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(2, 10, 2, 2)
        v.setSpacing(12)
        v.addWidget(self._build_ai_section())
        v.addWidget(self._build_engine_box())
        v.addWidget(self._build_sources_box())
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
        self.engine_combo.addItem("Local (faster-whisper)", "local")
        self.engine_combo.addItem("OpenAI API (cloud)", "openai")
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
        self.compute_combo.addItem("Auto", "auto")
        self.compute_combo.addItem("CPU", "cpu")
        self.compute_combo.addItem("GPU (CUDA)", "cuda")
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

        engine_layout.addWidget(self.engine_stack)

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

    def _update_compute_label(self) -> None:
        from .transcribe import detect_compute

        choice = self.compute_combo.currentData()
        if choice == "cpu":
            self._compute_label.setText("· CPU (int8)")
        elif choice == "cuda":
            self._compute_label.setText("· GPU CUDA (float16)")
        else:
            self._compute_label.setText(f"· auto → {detect_compute()[2]}")

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
        self.mic_combo.currentIndexChanged.connect(self._persist_config)
        self.sys_combo.currentIndexChanged.connect(self._persist_config)
        self.hf_token_edit.textChanged.connect(self._persist_config)
        self.compute_combo.currentIndexChanged.connect(self._persist_config)

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
        s("ui.auto_refresh", "1" if self.auto_refresh.isChecked() else "0")
        s("t.engine", self.engine_combo.currentData() or "")
        s("t.language", self.lang_edit.text())
        s("t.local_model", self.model_combo.currentText())
        s("t.openai_key", self.api_key_edit.text())
        s("t.openai_model", self.openai_model_combo.currentText())
        s("t.mic_device", self.mic_combo.currentText())
        s("t.sys_device", self.sys_combo.currentText())
        s("t.hf_token", self.hf_token_edit.text())
        s("t.compute", self.compute_combo.currentData() or "auto")
        self._apply_hf_token()
        self._save_ai_fields()

    def _load_config(self) -> None:
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
        an = g("ui.auto_notes")
        if an is not None:
            self.auto_notes.setChecked(an == "1")
        ar = g("ui.auto_refresh")
        if ar is not None:
            self.auto_refresh.setChecked(ar == "1")
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

        device, compute_type = {
            "cpu": ("cpu", "int8"), "cuda": ("cuda", "float16"),
        }.get(self.compute_combo.currentData(), ("auto", "auto"))
        config = {
            "engine": self.engine_combo.currentData(),
            "language": self.lang_edit.text().strip(),
            "model_size": self.model_combo.currentText().strip(),
            "device": device,
            "compute_type": compute_type,
            "api_key": self.api_key_edit.text().strip(),
            "openai_model": self.openai_model_combo.currentText(),
        }
        if config["engine"] == "openai" and not config["api_key"]:
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
            )
            self.status_label.setText(f"Saved transcript to local database (#{self._meeting_id}).")
            self._refresh_meetings()
        except Exception as exc:
            self.status_label.setText(f"⚠ Could not save to database: {exc}")

    def _set_settings_enabled(self, enabled: bool) -> None:
        for w in (
            self.engine_combo, self.model_combo, self.api_key_edit,
            self.openai_model_combo, self.lang_edit, self.mic_check,
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
            from .agent import MeetingNotesAgent, summary_to_markdown

            agent = MeetingNotesAgent(
                provider=self.config["provider"],
                model_name=self.config.get("model") or None,
                api_key=self.config.get("api_key") or None,
                base_url=self.config.get("base_url") or None,
            )
            summary = agent.summarize(self.transcript_text, title=self.title)
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
        view = QTextEdit()
        view.setObjectName("transcript")
        view.setReadOnly(True)
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

        self._view = QTextEdit()
        self._view.setObjectName("transcript")
        self._view.setReadOnly(True)
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

    def _current_md(self) -> str:
        scope = self._scope()
        if scope == "summary":
            return self._summary_md
        if scope == "transcript":
            return f"## Full transcript\n\n{self._transcript_md}"
        return f"{self._summary_md}\n\n---\n\n## Full transcript\n\n{self._transcript_md}"

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
            self._parent._refresh_meetings()
        except Exception:
            pass
        self.accept()


class WelcomeDialog(QDialog):
    """First-run setup: capture the user's name and an optional meeting name.

    The name is shown only the first time — once saved it's reused silently.
    """

    def __init__(self, default_name: str = "", ask_name: bool = True):
        super().__init__()
        self.setWindowTitle("MeetGraph")
        self.setWindowIcon(app_icon())
        self.resize(460, 420)
        self.user_name = default_name
        self.meeting_name = ""
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
        if ask_name:
            lbl = QLabel("Your name")
            lbl.setStyleSheet("font-weight:600;")
            v.addWidget(lbl)
            self.name_edit.setPlaceholderText("used to label your speech (e.g. Tek Raj)")
            v.addWidget(self.name_edit)

        mlbl = QLabel("Meeting name (optional)")
        mlbl.setStyleSheet("font-weight:600;")
        v.addWidget(mlbl)
        self.meeting_edit = QLineEdit()
        self.meeting_edit.setPlaceholderText("e.g. Launch planning sync")
        self.meeting_edit.returnPressed.connect(self._continue)
        v.addWidget(self.meeting_edit)

        v.addStretch()
        cont = QPushButton("Continue →")
        cont.setObjectName("primary")
        cont.clicked.connect(self._continue)
        v.addWidget(cont)

    def _continue(self) -> None:
        if self._ask_name:
            self.user_name = self.name_edit.text().strip()
        self.meeting_name = self.meeting_edit.text().strip()
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

    # Show the welcome screen only when we don't yet know the user's name;
    # afterwards the saved name is reused silently. The meeting name is asked
    # each run (it's optional and changes meeting-to-meeting).
    dlg = WelcomeDialog(default_name=saved_name, ask_name=not saved_name)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return  # closing the welcome screen (X / Esc) exits the app

    user_name = saved_name or dlg.user_name
    if dlg.user_name and not saved_name:
        store.set_setting("user_name", dlg.user_name)

    win = MainWindow(user_name=user_name, meeting_name=dlg.meeting_name)
    win.show()
    sys.exit(app.exec())
