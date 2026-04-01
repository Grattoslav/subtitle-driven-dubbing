import json
import os
import subprocess
import sys
import traceback
import faulthandler

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

from audio_processor import DiarizationProcessor

LOG_PATH = os.path.join(os.getcwd(), "dabing_debug.log")


def log_line(message):
    line = str(message)
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(line + "\n")


class ProcessingThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, video_path, processor):
        super().__init__()
        self.video_path = video_path
        self.processor = processor

    def run(self):
        try:
            log_line(f"ProcessingThread started for: {self.video_path}")
            self.progress.emit("Pripravuji analyzu...")
            for _segment in self.processor.process_video(self.video_path):
                pass

            self.finished.emit()
            log_line("ProcessingThread finished successfully")
        except Exception as exc:
            tb = traceback.format_exc()
            log_line(tb)
            self.error.emit(f"{exc}\n{tb}")


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


class DabingGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("S.bros Dubbing")
        self.resize(1100, 700)

        self.hf_token = self.load_hf_token()
        self.processor = None
        self.thread = None
        self.video_path = None
        self.current_media_path = None
        self.is_scrubbing = False
        self.dubbing_process = None
        self.auto_started_dubbing = False

        self.setup_player()
        self.setup_polling()
        self.init_ui()

    def load_hf_token(self):
        token_path = os.path.join(os.getcwd(), ".hf_token")
        if os.path.exists(token_path):
            with open(token_path, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        return None

    def setup_player(self):
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(1.0)
        self.media_player = QMediaPlayer()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.positionChanged.connect(self.on_position_changed)
        self.media_player.durationChanged.connect(self.on_duration_changed)
        self.fullscreen_shortcut = QShortcut(QKeySequence("F"), self)
        self.fullscreen_shortcut.activated.connect(self.toggle_fullscreen)

    def setup_polling(self):
        self.state_timer = QTimer(self)
        self.state_timer.setInterval(2000)
        self.state_timer.timeout.connect(self.refresh_dubbing_state)
        self.state_timer.start()

    def preview_video_path(self):
        if not self.video_path:
            return None
        base = os.path.splitext(self.video_path)[0]
        preview_path = base + "_dub_assets\\" + os.path.splitext(os.path.basename(self.video_path))[0] + "_preview.mp4"
        mixed_audio_path = base + "_dub_assets\\mixed_preview_audio.wav"
        if not os.path.exists(preview_path):
            return None
        if os.path.exists(mixed_audio_path):
            if os.path.getmtime(preview_path) < os.path.getmtime(mixed_audio_path):
                return None
        return preview_path

    def job_state_path(self):
        if not self.video_path:
            return None
        return os.path.splitext(self.video_path)[0] + ".dubbing_job_state.json"

    def runner_command(self, reset=False):
        if not self.video_path:
            return None
        command = [sys.executable, "system\\dubbing_runner.py", self.video_path]
        if reset:
            command.append("--reset")
        return command

    def start_dubbing(self, reset=False):
        command = self.runner_command(reset=reset)
        if not command:
            return
        if self.dubbing_process and self.dubbing_process.poll() is None:
            self.preview_status_label.setText("Dubbing: uz bezi")
            return

        self.preview_status_label.setText("Dubbing: spoustim...")
        self.dubbing_process = subprocess.Popen(
            command,
            cwd=os.getcwd(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.refresh_dubbing_state()

    def refresh_dubbing_state(self):
        if not self.video_path:
            self.preview_status_label.setText("Dubbing: neni vybrane video")
            self.play_dub_btn.setEnabled(False)
            self.play_dub_btn.setText("Dabing jeste neni pripraven")
            self.play_dub_btn.setStyleSheet("background-color: #7f1d1d; color: white;")
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            return

        preview_path = self.preview_video_path()
        if preview_path:
            self.play_dub_btn.setEnabled(True)
            self.play_dub_btn.setText("Prehrat dabing")
            self.play_dub_btn.setStyleSheet("background-color: #166534; color: white;")
            if self.current_media_path != preview_path:
                self.load_media(preview_path, "Dubbed audio")
        else:
            self.play_dub_btn.setEnabled(False)
            self.play_dub_btn.setText("Dabing jeste neni pripraven")
            self.play_dub_btn.setStyleSheet("background-color: #7f1d1d; color: white;")

        state_path = self.job_state_path()
        if not state_path or not os.path.exists(state_path):
            self.preview_status_label.setText("Dubbing: zatim neni pripraveny job")
            return

        try:
            with open(state_path, "r", encoding="utf-8-sig") as handle:
                state = json.load(handle)
            progress = state.get("progress", {})
            completed = progress.get("dub_completed", 0)
            pending = progress.get("dub_pending", 0)
            failed = progress.get("dub_failed", 0)
            total = completed + pending + failed
            self.preview_status_label.setText(
                "Dubbing: "
                f"{state.get('job_status', 'unknown')} | "
                f"hotovo {completed} / "
                f"ceka {pending} / "
                f"chyby {failed}"
            )
            if total > 0:
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(completed)
            else:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
        except Exception:
            self.preview_status_label.setText("Dubbing: stav nejde precist")
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)

    def load_media(self, media_path, label):
        if not media_path or not os.path.exists(media_path):
            self.status_label.setText(f"{label} not available")
            return
        self.current_media_path = media_path
        self.media_player.setSource(QUrl.fromLocalFile(media_path))
        self.player_source_label.setText(f"Nacteno: {os.path.basename(media_path)}")

    def play_dubbed_media(self):
        preview_path = self.preview_video_path()
        if not preview_path:
            return
        if self.current_media_path != preview_path:
            self.load_media(preview_path, "Preview video")
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.player_source_label.setText(f"Pozastaveno: {os.path.basename(preview_path)}")
        else:
            self.media_player.play()
            self.player_source_label.setText(f"Prehravam: {os.path.basename(preview_path)}")

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

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        file_layout = QHBoxLayout()
        self.file_label = QLabel("Neni vybrane video")
        self.browse_btn = QPushButton("Vybrat video")
        self.browse_btn.clicked.connect(self.browse_file)
        file_layout.addWidget(self.file_label, 1)
        file_layout.addWidget(self.browse_btn)
        layout.addLayout(file_layout)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(320)
        self.media_player.setVideoOutput(self.video_widget)
        layout.addWidget(self.video_widget)

        control_layout = QHBoxLayout()
        self.play_dub_btn = QPushButton("Dabing jeste neni pripraven")
        self.play_dub_btn.setEnabled(False)
        self.play_dub_btn.setStyleSheet("background-color: #7f1d1d; color: white;")
        self.play_dub_btn.clicked.connect(self.play_dubbed_media)
        self.fullscreen_btn = QPushButton("Fullscreen")
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        self.player_source_label = QLabel("Dabing zatim neni nacteny")

        control_layout.addWidget(self.play_dub_btn)
        control_layout.addWidget(self.fullscreen_btn)
        control_layout.addWidget(self.player_source_label, 1)
        layout.addLayout(control_layout)

        self.preview_status_label = QLabel("Dubbing: zatim neni pripraveny job")
        layout.addWidget(self.preview_status_label)

        self.position_slider = ClickSeekSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.seek_position)
        self.position_slider.sliderPressed.connect(self.on_slider_pressed)
        self.position_slider.sliderReleased.connect(self.on_slider_released)
        layout.addWidget(self.position_slider)

        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video",
            "stazene",
            "Video Files (*.mp4 *.mkv *.avi *.mov)",
        )
        if not file_path:
            return

        self.video_path = file_path
        self.file_label.setText(os.path.basename(file_path))
        self.current_media_path = None
        self.auto_started_dubbing = False
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        self.player_source_label.setText("Dabing zatim neni nacteny")
        self.status_label.setText("Pripravuji analyzu...")
        self.progress_bar.setRange(0, 0)
        self.refresh_dubbing_state()
        self.start_processing()

    def start_processing(self):
        if not self.video_path:
            return

        log_line(f"Start requested for video: {self.video_path}")
        self.browse_btn.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("Initializing models...")

        try:
            if self.processor is None:
                log_line("Initializing DiarizationProcessor on main thread")
                self.processor = DiarizationProcessor(hf_token=self.hf_token)
                log_line("DiarizationProcessor initialized successfully")
        except Exception as exc:
            tb = traceback.format_exc()
            log_line(tb)
            self.on_error(f"{exc}\n{tb}")
            return

        self.status_label.setText("Starting processing...")
        self.thread = ProcessingThread(self.video_path, self.processor)
        self.thread.progress.connect(self.status_label.setText)
        self.thread.finished.connect(self.on_finished)
        self.thread.error.connect(self.on_error)
        self.thread.start()

    def on_finished(self):
        log_line("GUI received finished signal")
        self.status_label.setText("Analyza hotova, spoustim cely dabing...")
        self.browse_btn.setEnabled(True)
        if not self.auto_started_dubbing:
            self.auto_started_dubbing = True
            self.start_dubbing(reset=False)
        self.refresh_dubbing_state()

    def on_error(self, message):
        log_line("GUI received error signal")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        first_line = message.splitlines()[0] if message else "Unknown error"
        self.status_label.setText(f"Error: {first_line}")
        log_line(message)
        self.browse_btn.setEnabled(True)
        self.refresh_dubbing_state()


if __name__ == "__main__":
    with open(LOG_PATH, "w", encoding="utf-8") as log_file:
        log_file.write("Starting GUI session\n")
    fault_log = open(LOG_PATH, "a", encoding="utf-8")
    faulthandler.enable(file=fault_log, all_threads=True)
    app = QApplication(sys.argv)
    window = DabingGUI()
    window.show()
    sys.exit(app.exec())
