import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_DIR = REPO_ROOT / "system"
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from audio_processor import DiarizationProcessor  # noqa: E402


class ClickSeekSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            ratio = event.position().x() / max(1.0, self.width())
            value = self.minimum() + round((self.maximum() - self.minimum()) * ratio)
            self.setValue(value)
            self.sliderMoved.emit(value)
            self.sliderReleased.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class AnalysisThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, video_path, subtitle_path, processor):
        super().__init__()
        self.video_path = video_path
        self.subtitle_path = subtitle_path
        self.processor = processor

    def run(self):
        try:
            self.progress.emit("Preparing dubbing metadata...")
            for _ in self.processor.process_video(self.video_path, subtitle_path=self.subtitle_path):
                pass
            self.finished.emit()
        except Exception as exc:
            self.error.emit(f"{exc}\n{traceback.format_exc()}")


class IntegrationPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Subtitle-Driven Dubbing Consumer Example")
        self.resize(1180, 760)

        self.video_path = None
        self.subtitle_path = None
        self.processor = None
        self.analysis_thread = None
        self.dubbing_process = None
        self.current_media_path = None
        self.is_scrubbing = False

        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(1.0)
        self.media_player = QMediaPlayer()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.positionChanged.connect(self.on_position_changed)
        self.media_player.durationChanged.connect(self.on_duration_changed)

        self.fullscreen_shortcut = QShortcut(QKeySequence("F"), self)
        self.fullscreen_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.fullscreen_shortcut.activated.connect(self.toggle_fullscreen)

        self.state_timer = QTimer(self)
        self.state_timer.setInterval(2000)
        self.state_timer.timeout.connect(self.refresh_state)
        self.state_timer.start()

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        pick_row = QHBoxLayout()
        self.video_label = QLabel("No video selected")
        self.pick_video_btn = QPushButton("Choose Video")
        self.pick_video_btn.clicked.connect(self.pick_video)
        pick_row.addWidget(self.video_label, 1)
        pick_row.addWidget(self.pick_video_btn)
        layout.addLayout(pick_row)

        subtitle_row = QHBoxLayout()
        self.subtitle_label = QLabel("No subtitles selected")
        self.pick_subtitle_btn = QPushButton("Choose Subtitles")
        self.pick_subtitle_btn.clicked.connect(self.pick_subtitles)
        subtitle_row.addWidget(self.subtitle_label, 1)
        subtitle_row.addWidget(self.pick_subtitle_btn)
        layout.addLayout(subtitle_row)

        action_row = QHBoxLayout()
        self.start_btn = QPushButton("Prepare and Start Dubbing")
        self.start_btn.clicked.connect(self.start_workflow)
        self.play_btn = QPushButton("Dubbed Playback Not Ready")
        self.play_btn.setEnabled(False)
        self.play_btn.setStyleSheet("background-color: #7f1d1d; color: white;")
        self.play_btn.clicked.connect(self.toggle_playback)
        self.fullscreen_btn = QPushButton("Fullscreen")
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        action_row.addWidget(self.start_btn)
        action_row.addWidget(self.play_btn)
        action_row.addWidget(self.fullscreen_btn)
        layout.addLayout(action_row)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(420)
        self.media_player.setVideoOutput(self.video_widget)
        layout.addWidget(self.video_widget)

        self.position_slider = ClickSeekSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.seek_position)
        self.position_slider.sliderPressed.connect(self.on_slider_pressed)
        self.position_slider.sliderReleased.connect(self.on_slider_released)
        layout.addWidget(self.position_slider)

        self.status_label = QLabel("Choose a video and subtitles to begin.")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

    def hf_token(self):
        token_path = REPO_ROOT / ".hf_token"
        if token_path.exists():
            return token_path.read_text(encoding="utf-8").strip()
        return None

    def pick_video(self):
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose video",
            str(REPO_ROOT / "stazene"),
            "Video Files (*.mp4 *.mkv *.avi *.mov)",
        )
        if selected:
            self.video_path = selected
            self.video_label.setText(Path(selected).name)
            self.current_media_path = None
            self.media_player.stop()
            self.media_player.setSource(QUrl())
            self.refresh_state()

    def pick_subtitles(self):
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose subtitles",
            str(REPO_ROOT / "stazene"),
            "Subtitle Files (*.srt)",
        )
        if selected:
            self.subtitle_path = selected
            self.subtitle_label.setText(Path(selected).name)

    def preview_video_path(self):
        if not self.video_path:
            return None
        video = Path(self.video_path)
        return video.with_name(f"{video.stem}_dub_assets").joinpath(f"{video.stem}_preview.mp4")

    def job_state_path(self):
        if not self.video_path:
            return None
        return Path(self.video_path).with_suffix(".dubbing_job_state.json")

    def start_workflow(self):
        if not self.video_path or not self.subtitle_path:
            self.status_label.setText("Choose both a video and a subtitle file.")
            return
        if self.analysis_thread and self.analysis_thread.isRunning():
            self.status_label.setText("Analysis is already running.")
            return
        self.start_btn.setEnabled(False)
        self.status_label.setText("Initializing analysis...")
        self.progress_bar.setRange(0, 0)

        try:
            if self.processor is None:
                self.processor = DiarizationProcessor(hf_token=self.hf_token())
        except Exception as exc:
            self.start_btn.setEnabled(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.status_label.setText(f"Engine init failed: {exc}")
            return

        self.analysis_thread = AnalysisThread(self.video_path, self.subtitle_path, self.processor)
        self.analysis_thread.progress.connect(self.status_label.setText)
        self.analysis_thread.finished.connect(self.on_analysis_finished)
        self.analysis_thread.error.connect(self.on_analysis_error)
        self.analysis_thread.start()

    def on_analysis_finished(self):
        self.status_label.setText("Analysis finished. Starting dubbing...")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.start_dubbing()

    def on_analysis_error(self, message):
        self.start_btn.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        first_line = message.splitlines()[0] if message else "Unknown error"
        self.status_label.setText(f"Analysis failed: {first_line}")

    def start_dubbing(self):
        if self.dubbing_process and self.dubbing_process.poll() is None:
            return
        command = [sys.executable, str(SYSTEM_DIR / "dubbing_runner.py"), self.video_path]
        self.dubbing_process = subprocess.Popen(
            command,
            cwd=str(REPO_ROOT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.refresh_state()

    def refresh_state(self):
        preview_path = self.preview_video_path()
        if preview_path and preview_path.exists():
            self.play_btn.setEnabled(True)
            self.play_btn.setText("Play Dubbed Video")
            self.play_btn.setStyleSheet("background-color: #166534; color: white;")
            if self.current_media_path != str(preview_path):
                self.load_media(str(preview_path))
        else:
            self.play_btn.setEnabled(False)
            self.play_btn.setText("Dubbed Playback Not Ready")
            self.play_btn.setStyleSheet("background-color: #7f1d1d; color: white;")

        state_path = self.job_state_path()
        if not state_path or not state_path.exists():
            return
        try:
            state = json.loads(state_path.read_text(encoding="utf-8-sig"))
            progress = state.get("progress", {})
            completed = progress.get("dub_completed", 0)
            pending = progress.get("dub_pending", 0)
            failed = progress.get("dub_failed", 0)
            total = completed + pending + failed
            ready_until = float(state.get("ready_until", 0.0) or 0.0)
            ready_minutes = int(ready_until // 60)
            ready_seconds = int(ready_until % 60)
            self.status_label.setText(
                f"{state.get('job_status', 'unknown')} | "
                f"done {completed} / pending {pending} / failed {failed} | "
                f"ready until {ready_minutes:02d}:{ready_seconds:02d}"
            )
            if total > 0:
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(completed)
        except Exception as exc:
            self.status_label.setText(f"State read failed: {exc}")

    def load_media(self, media_path):
        self.current_media_path = media_path
        self.media_player.setSource(QUrl.fromLocalFile(media_path))

    def toggle_playback(self):
        preview_path = self.preview_video_path()
        if not preview_path or not preview_path.exists():
            return
        if self.current_media_path != str(preview_path):
            self.load_media(str(preview_path))
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def toggle_fullscreen(self):
        if self.video_widget.isFullScreen():
            self.video_widget.setFullScreen(False)
            self.fullscreen_btn.setText("Fullscreen")
        else:
            self.video_widget.setFullScreen(True)
            self.fullscreen_btn.setText("Exit Fullscreen")

    def on_position_changed(self, position):
        if not self.is_scrubbing:
            self.position_slider.setValue(position)

    def on_duration_changed(self, duration):
        self.position_slider.setRange(0, duration)

    def seek_position(self, position):
        self.media_player.setPosition(position)

    def on_slider_pressed(self):
        self.is_scrubbing = True

    def on_slider_released(self):
        self.is_scrubbing = False
        self.media_player.setPosition(self.position_slider.value())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = IntegrationPlayer()
    window.show()
    sys.exit(app.exec())
