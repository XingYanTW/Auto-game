import math
import shutil
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGraphicsView, QGraphicsScene,
    QMenu, QGraphicsLineItem, QGraphicsPixmapItem, QGraphicsPolygonItem
)
from PySide6.QtGui import (
    QPixmap, QDragEnterEvent, QDropEvent, QFont, QWheelEvent,
    QPen, QPainter, QMouseEvent, QContextMenuEvent, QKeyEvent,
    QPolygonF
)
from PySide6.QtCore import Qt, QPointF, QEvent
from functions import get_resource_path

class ArrowItem(QGraphicsPolygonItem):
    """
    小箭頭形狀，原點在箭頭尖端，往負 X 方向延伸。
    這樣在旋轉時，0 度即指向右邊，角度沿逆時針方向正增。
    """
    def __init__(self):
        super().__init__()
        arrow_shape = QPolygonF([
            QPointF(0, 0),
            QPointF(-15, -8),
            QPointF(-15, 8)
        ])
        self.setPolygon(arrow_shape)
        self.setBrush(Qt.white)
        self.setPen(QPen(Qt.white))

class PixmapNode(QGraphicsPixmapItem):
    """
    自訂類別，承載 connections (所有連線)。
    一旦位置改變 (itemChange)，更新所有連線，使線條跟著移動。
    connections: List[ (otherNode, lineObj, arrowObj, myOffset, otherOffset) ]
       → (對方的 PixmapNode, 連線物件, 箭頭物件, 我方 local_offset, 對方 local_offset)
    """
    def __init__(self, pixmap):
        super().__init__(pixmap)
        self.setFlag(QGraphicsPixmapItem.ItemSendsScenePositionChanges, True)
        self.connections = []

    def itemChange(self, change, value):
        if change == QGraphicsPixmapItem.ItemPositionChange:
            for otherNode, lineObj, arrowObj, myOffset, otherOffset in self.connections:
                self.updateLineAndArrow(lineObj, arrowObj, otherNode, myOffset, otherOffset)
        return super().itemChange(change, value)

    def updateLineAndArrow(self, lineObj, arrowObj, otherNode, myOffset, theirOffset):
        """
        動態更新線條端點和箭頭位置與角度，使其指向「由自己 → otherNode」。
        """
        my_point_in_scene = self.mapToScene(myOffset)
        their_point_in_scene = otherNode.mapToScene(theirOffset)

        # 更新線條
        lineObj.setLine(
            my_point_in_scene.x(), my_point_in_scene.y(),
            their_point_in_scene.x(), their_point_in_scene.y()
        )

        # 箭頭擺在中點
        mid_x = (my_point_in_scene.x() + their_point_in_scene.x()) / 2
        mid_y = (my_point_in_scene.y() + their_point_in_scene.y()) / 2
        arrowObj.setPos(mid_x, mid_y)

        # 算出角度，atan2(dy, dx) 傳回弧度，轉度數後再套用
        dx = their_point_in_scene.x() - my_point_in_scene.x()
        dy = their_point_in_scene.y() - my_point_in_scene.y()
        angle_deg = math.degrees(math.atan2(dy, dx))
        arrowObj.setRotation(angle_deg)

class TestView(QWidget):
    def __init__(self, parent=None):
        super(TestView, self).__init__(parent)
        self.setAcceptDrops(True)  # 啟用拖放功能

        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)

        # 場景與視圖
        self.graphics_view = CustomGraphicsView()
        self.graphics_scene = QGraphicsScene(self)
        self.graphics_view.setScene(self.graphics_scene)
        self.graphics_view.setRenderHint(QPainter.Antialiasing)
        self.graphics_view.setRenderHint(QPainter.SmoothPixmapTransform)
        self.graphics_view.setDragMode(QGraphicsView.ScrollHandDrag)
        main_layout.addWidget(self.graphics_view)

        # 提示標籤
        self.label = QLabel("拖曳圖片到此區域", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setFont(QFont("Arial", 16, QFont.Bold))
        self.label.setStyleSheet("color: white; background-color: darkblue; padding: 10px;")
        main_layout.addWidget(self.label)

        # 連線模式
        self.is_connection_mode = False
        self.is_connecting = False
        self.start_item = None       # 儲存連線起始 PixmapNode
        self.start_offset = QPointF()  # 該 PixmapNode 上的 local offset
        self.temp_line = None

        # 監聽事件
        self.graphics_view.viewport().installEventFilter(self)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)
        if self.is_connection_mode:
            toggle_action = menu.addAction("停止連線模式")
        else:
            toggle_action = menu.addAction("啟用連線模式")
        action = menu.exec_(self.mapToGlobal(event.pos()))
        if action == toggle_action:
            self.toggleConnectionMode()
        event.accept()

    def toggleConnectionMode(self):
        self.is_connection_mode = not self.is_connection_mode
        if self.is_connection_mode:
            self.label.setText("連線模式：點選圖片並拖曳到另一張圖片，以建立連線")
            for item in self.graphics_scene.items():
                if isinstance(item, PixmapNode):
                    item.setFlag(QGraphicsPixmapItem.ItemIsMovable, False)
        else:
            self.label.setText("一般模式：拖曳圖片或場景")
            for item in self.graphics_scene.items():
                if isinstance(item, PixmapNode):
                    item.setFlag(QGraphicsPixmapItem.ItemIsMovable, True)

    def eventFilter(self, watched, event):
        if watched == self.graphics_view.viewport() and isinstance(event, QMouseEvent):
            scene_pos = self.graphics_view.mapToScene(event.pos())

            # 僅在連線模式下處理
            if self.is_connection_mode:
                if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                    item = self.graphics_scene.itemAt(scene_pos, self.graphics_view.transform())
                    if isinstance(item, PixmapNode):
                        # 記錄起始物件與使用者點擊的位置 (local offset)
                        self.start_item = item
                        self.start_offset = item.mapFromScene(scene_pos)
                        self.is_connecting = True

                        # 建立暫時線
                        self.temp_line = QGraphicsLineItem()
                        pen = QPen(Qt.white)
                        pen.setStyle(Qt.DashLine)
                        pen.setWidth(4)
                        # 確保非 cosmetic，會跟隨縮放 (預設已有可能是False，但這裡明確指定)
                        pen.setCosmetic(False)
                        self.temp_line.setPen(pen)
                        self.graphics_scene.addItem(self.temp_line)

                        start_scene_pt = item.mapToScene(self.start_offset)
                        self.temp_line.setLine(
                            start_scene_pt.x(),
                            start_scene_pt.y(),
                            scene_pos.x(),
                            scene_pos.y()
                        )

                elif event.type() == QEvent.MouseMove and self.is_connecting and self.temp_line and self.start_item:
                    start_scene_pt = self.start_item.mapToScene(self.start_offset)
                    self.temp_line.setLine(
                        start_scene_pt.x(),
                        start_scene_pt.y(),
                        scene_pos.x(),
                        scene_pos.y()
                    )

                elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                    if self.temp_line:
                        self.graphics_scene.removeItem(self.temp_line)
                        self.temp_line = None

                    if self.is_connecting:
                        end_item = self.graphics_scene.itemAt(scene_pos, self.graphics_view.transform())
                        if isinstance(end_item, PixmapNode) and end_item != self.start_item:
                            end_offset = end_item.mapFromScene(scene_pos)
                            self.connectTwoItems(self.start_item, self.start_offset, end_item, end_offset)
                            self.label.setText("已建立連線")
                        else:
                            self.label.setText("取消連線")

                    self.start_item = None
                    self.is_connecting = False

        return super().eventFilter(watched, event)

    def connectTwoItems(self, itemA: PixmapNode, offsetA: QPointF,
                        itemB: PixmapNode, offsetB: QPointF):
        """
        建立「A -> B」的實線與箭頭，並記錄端點對應的 local offset。
        同時確保線條非 cosmetic，讓它能跟隨場景縮放。
        """
        # 計算 A / B 對應點的世界座標，用來畫線
        a_in_scene = itemA.mapToScene(offsetA)
        b_in_scene = itemB.mapToScene(offsetB)

        # 畫實線
        line = QGraphicsLineItem()
        line.setZValue(-1)
        pen = QPen(Qt.white)
        pen.setWidth(4)
        pen.setCosmetic(False)  # 關鍵：確保線條非 cosmetic，會跟隨縮放
        line.setPen(pen)
        line.setLine(a_in_scene.x(), a_in_scene.y(),
                     b_in_scene.x(), b_in_scene.y())
        self.graphics_scene.addItem(line)

        # 建立箭頭
        arrow = ArrowItem()
        arrow.setZValue(0)  # 顯示在線條之上
        # 不設定忽略變形 (ItemIgnoresTransformations=False)，讓箭頭也可以跟隨縮放
        self.graphics_scene.addItem(arrow)

        # 箭頭初始位置與角度
        mid_x = (a_in_scene.x() + b_in_scene.x()) / 2
        mid_y = (a_in_scene.y() + b_in_scene.y()) / 2
        arrow.setPos(mid_x, mid_y)
        dx = b_in_scene.x() - a_in_scene.x()
        dy = b_in_scene.y() - a_in_scene.y()
        angle_deg = math.degrees(math.atan2(dy, dx))
        arrow.setRotation(angle_deg)

        # 雙向記錄連線 (多半只需要 A->B 的箭頭，但可依需求同時做 B->A)
        itemA.connections.append((itemB, line, arrow, offsetA, offsetB))
        # itemB.connections.append(...) # 若需要反向箭頭，可在此補上

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path) and file_path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                self.handle_image_drop(file_path)

    def handle_image_drop(self, file_path):
        detect_folder = get_resource_path('detect')
        if not os.path.exists(detect_folder):
            os.makedirs(detect_folder)

        file_name = os.path.basename(file_path)
        destination_path = os.path.join(detect_folder, file_name)
        shutil.copy(file_path, destination_path)

        pixmap = QPixmap(destination_path)
        if pixmap.isNull():
            return

        pixmap_node = PixmapNode(pixmap)
        pixmap_node.setFlag(QGraphicsPixmapItem.ItemIsMovable, not self.is_connection_mode)
        pixmap_node.setFlag(QGraphicsPixmapItem.ItemIsSelectable, True)
        self.graphics_scene.addItem(pixmap_node)

        self.label.setText(f"已載入圖片: {file_name}")

    def wheelEvent(self, event: QWheelEvent):
        """
        使用滾輪放大縮小。由於線條與箭頭不是 cosmetic，所以會跟隨場景同步縮放。
        """
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.graphics_view.scale(factor, factor)

class CustomGraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
