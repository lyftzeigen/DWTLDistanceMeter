import sys
import cv2
import math
import numpy as np

from PyQt6.QtCore import Qt
from PyQt6.QtCore import QUrl
from PyQt6.QtCore import QTime
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import QPoint
from PyQt6.QtCore import QRectF
from PyQt6.QtCore import QPointF

from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QSlider
from PyQt6.QtWidgets import QWidget
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QFileDialog
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QGraphicsScene
from PyQt6.QtWidgets import QGraphicsItem
from PyQt6.QtWidgets import QGraphicsView

from PyQt6.QtGui import QPen
from PyQt6.QtGui import QColor
from PyQt6.QtGui import QPainter

from PyQt6.QtMultimedia import QMediaPlayer, QVideoFrame
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem


class CoordinateTranslator:
    # Точки на кадре
    frame_points = np.array(
        [
            (610, 399),
            (962, 389),
            (1312, 390),
            (490, 587),
            (967, 584),
            (1444, 570),
            (296, 935),
            (976, 998),
            (1643, 916),
        ]
    )

    # Точки в реальном пространстве
    real_points = np.array(
        [
            (-1.8, +1.8),
            (0, +1.8),
            (+1.8, +1.8),
            (-1.8, 0),
            (0, 0),
            (+1.8, 0),
            (-1.8, -1.8),
            (0, -1.8),
            (+1.8, -1.8),
        ]
    )

    # Гомография
    h, status = cv2.findHomography(frame_points, real_points)

    def transform(point: QPoint) -> QPointF:
        # Преобразуем в формат для трансформации
        points = np.array([[(point.x(), point.y())]]).astype("float32")
        # Проводим трансформацию
        transform = cv2.perspectiveTransform(points, CoordinateTranslator.h)
        # Восстанавливаем формат
        transform = transform.reshape((-1))
        # Результат в виде QPointF
        return QPointF(transform[0], transform[1])


class Window(QWidget):
    def __init__(self):
        super().__init__()

    def center_window(self):
        size = self.geometry()
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - size.width()) // 2,
            (screen.height() - size.height()) // 2,
        )


class OpenVideoWindow(Window):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DWTL - Открытие видео")
        self.setGeometry(100, 100, 400, 300)
        self.setMinimumSize(400, 300)
        self.center_window()

        self.layout = QVBoxLayout(self)

        text = (
            "<b>Escape</b> - закрыть видео<br>"
            "<b>Пробел</b> - пауза/проигрывание<br>"
            "<b>D</b> - вперед на 1 минуту<br>"
            "<b>A</b> - назад на 1 минуту"
        )

        self.label = QLabel(text, self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addStretch()
        self.layout.addWidget(self.label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.button_open = QPushButton("Открыть видео", self)
        self.button_open.clicked.connect(self.open_video)
        self.layout.addWidget(self.button_open, alignment=Qt.AlignmentFlag.AlignCenter)
        self.layout.addStretch()

    def open_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите видео", "", "Видео файлы (*.mp4)"
        )

        if file_path:
            self.close()
            self.video_window = VideoPlayerWindow(file_path)
            self.video_window.show()


class OverlayItem(QGraphicsItem):
    def __init__(self, video_item):
        super().__init__(video_item)

        # Точки оверлея
        self.point_one: QPointF = None
        self.point_two: QPointF = None

        # Сплошной карандаш
        self.pen_solid = QPen(QColor("lime"), 1, Qt.PenStyle.SolidLine)

        # Пунктирный карандаш
        self.pen_dash = QPen(QColor("lime"), 1, Qt.PenStyle.DashLine)

    def clear(self):
        self.point_one = None
        self.point_two = None
        self.update()

    def set_point_one(self, point):
        self.point_one = point
        self.update()

    def set_point_two(self, point):
        self.point_two = point
        self.update()

    def paint(self, painter: QPainter, option, widget=None):
        # Режим сглаживания
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Сплошным карандашом
        painter.setPen(self.pen_solid)

        # Рисование возможных точек
        for point in [self.point_one, self.point_two]:
            if point is not None:
                painter.drawEllipse(point, 3, 3)

        # Рисование соединительной линии
        if self.point_one and self.point_two:
            # Пунктирным карандашом
            painter.setPen(self.pen_dash)
            painter.drawLine(self.point_one, self.point_two)

    def boundingRect(self) -> QRectF:
        return self.parentItem().boundingRect()


class VideoPlayerWindow(Window):
    def __init__(self, file_path):
        super().__init__()

        # Координаты точек на кадре
        self.frame_point_one = None
        self.frame_point_two = None

        # Настройки окна
        self.setWindowTitle("DWTL - Воспроизведение видео")
        self.setGeometry(100, 100, 960, 600)
        self.setMinimumSize(960, 600)
        self.center_window()

        # Вертикальная разметка
        self.layout = QVBoxLayout(self)

        # Компонент для отображения дистанции
        self.label_distance = QLabel("Дистанция: 0.00м", self)
        self.label_distance.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.layout.addWidget(self.label_distance)

        # Компонент для отображения видео
        self.video_item = QGraphicsVideoItem()

        # Компонент для отображения оверлея
        self.overlay_item = OverlayItem(self.video_item)

        # Плеер для воспроизведения видео
        self.player = QMediaPlayer()
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.player.setVideoOutput(self.video_item)
        self.player.durationChanged.connect(self.updateDurationEvent)
        self.player.play()

        # Компонент воспроизведения видео
        self.sink = self.player.videoSink()
        self.sink.videoFrameChanged.connect(self.videoFrameChangedEvent)

        # Сцена для размещения видео
        self.scene = QGraphicsScene(self)
        self.scene.addItem(self.video_item)
        self.scene.addItem(self.overlay_item)

        # Виджет для отображения сцены
        self.view = QGraphicsView(self.scene)
        self.view.setMouseTracking(True)
        self.view.mousePressEvent = self.viewMousePressEvent

        # Добавление виджета в разметку
        self.layout.addWidget(self.view)

        # Горизонтальная разметка
        time_slider_layout = QHBoxLayout()

        # Таймер видео
        self.time_label = QLabel("00:00:00 - 00:00:00", self)
        time_slider_layout.addWidget(self.time_label)

        # Слайдер видео
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.sliderPressed.connect(self.sliderPressedReleaseEvent)
        self.slider.sliderReleased.connect(self.sliderPressedReleaseEvent)
        self.slider.valueChanged.connect(self.sliderValueChangedEvent)
        time_slider_layout.addWidget(self.slider)

        # Добавление горизонтальной разметки в вертикальную
        self.layout.addLayout(time_slider_layout)

        # Запуск таймера обновления слайдера
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.timerUpdateSliderEvent)
        self.timer.start(100)

        # Слайдер не активен
        self.is_slider_active = False

    def keyPressEvent(self, event):
        step = 60 * 1000
        if event.key() == Qt.Key.Key_Space:
            self.toggle_playback()
            self.overlay_item.clear()
        elif event.key() == Qt.Key.Key_D:
            self.player.setPosition(self.player.position() + step)
            self.overlay_item.clear()
            self.clear_distance()
            self.update_time_label()
        elif event.key() == Qt.Key.Key_A:
            self.player.setPosition(self.player.position() - step)
            self.overlay_item.clear()
            self.clear_distance()
            self.update_time_label()
        elif event.key() == Qt.Key.Key_Escape:
            self.overlay_item.clear()
            self.clear_distance()
            self.timer.stop()
            self.close()
            self.open_window = OpenVideoWindow()
            self.open_window.show()

    def set_distance(self, distance):
        self.label_distance.setText(f"Дистанция: {distance:.2f}м")

    def clear_distance(self):
        self.label_distance.setText("Дистанция: 0.00м")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view.fitInView(self.video_item, Qt.AspectRatioMode.KeepAspectRatio)
        self.view.fitInView(self.overlay_item, Qt.AspectRatioMode.KeepAspectRatio)

    def updateDurationEvent(self, duration):
        self.slider.setRange(0, duration)
        self.slider.setSingleStep(1000)

    def videoFrameChangedEvent(self, frame: QVideoFrame):
        self.view.fitInView(self.video_item, Qt.AspectRatioMode.KeepAspectRatio)
        self.view.fitInView(self.overlay_item, Qt.AspectRatioMode.KeepAspectRatio)

    def timerUpdateSliderEvent(self):
        if not self.is_slider_active:
            position = self.player.position()
            self.slider.blockSignals(True)
            self.slider.setValue(position)
            self.slider.blockSignals(False)
            self.update_time_label()

    def sliderValueChangedEvent(self, value):
        if self.is_slider_active:
            self.player.setPosition(value)
            self.update_time_label()

    def sliderPressedReleaseEvent(self):
        self.is_slider_active = not self.is_slider_active
        if self.is_slider_active:
            self.player.pause()
        else:
            self.player.play()

    def update_time_label(self):
        current_time = QTime(0, 0).addMSecs(self.player.position()).toString("HH:mm:ss")
        total_time = QTime(0, 0).addMSecs(self.player.duration()).toString("HH:mm:ss")
        self.time_label.setText(f"{current_time} - {total_time}")

    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.frame_point_one = None
            self.frame_point_two = None
            self.overlay_item.clear()
            self.clear_distance()
            self.player.play()

    def viewMousePressEvent(self, event):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            return

        # Размер виджета с видео
        widget_size = self.view.viewport().size()

        # Кадр видео
        frame_size = self.player.videoSink().videoFrame().size()

        # Коэффициент масштабирования
        scale = min(
            widget_size.width() / frame_size.width(),
            widget_size.height() / frame_size.height(),
        )

        # Вычисляем смещение
        offset_x = (widget_size.width() - frame_size.width() * scale) / 2
        offset_y = (widget_size.height() - frame_size.height() * scale) / 2

        # Получаем реальные координаты
        frame_x = int((event.pos().x() - offset_x) / scale)
        frame_y = int((event.pos().y() - offset_y) / scale)

        # Очистка точек, если их уже две
        if self.frame_point_one is not None and self.frame_point_two is not None:
            self.frame_point_one = None
            self.frame_point_two = None
            self.overlay_item.clear()
            self.clear_distance()

        # Установка значения первой точки
        if self.frame_point_one is None:
            self.frame_point_one = QPoint(frame_x, frame_y)
            self.overlay_item.set_point_one(self.view.mapToScene(event.pos()))

        # Установка значения второй точки
        elif self.frame_point_two is None:
            self.frame_point_two = QPoint(frame_x, frame_y)
            self.overlay_item.set_point_two(self.view.mapToScene(event.pos()))

        # Расчет дистанции в реальных координатах
        if self.frame_point_one is not None and self.frame_point_two is not None:
            # Преобразование в реальные координаты
            real_point_one = CoordinateTranslator.transform(self.frame_point_one)
            real_point_two = CoordinateTranslator.transform(self.frame_point_two)
            # Расчет дистанции
            square_diff_one = math.pow(real_point_one.x() - real_point_two.x(), 2)
            square_diff_two = math.pow(real_point_one.y() - real_point_two.y(), 2)
            distance = math.sqrt(square_diff_one + square_diff_two)
            # Установка значения
            self.set_distance(distance)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    open_window = OpenVideoWindow()
    open_window.show()
    sys.exit(app.exec())
