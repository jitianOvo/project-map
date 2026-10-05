from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


INSTANCE_NAME = "ProjectMap.SingleInstance.v1"


class SingleInstance(QObject):
    activation_requested = Signal()

    def __init__(self, name=INSTANCE_NAME, parent=None):
        super().__init__(parent)
        self.name = name
        self.server: QLocalServer | None = None
        self.is_primary = not self._notify_existing_instance()
        if not self.is_primary:
            return
        QLocalServer.removeServer(self.name)
        self.server = QLocalServer(self)
        if not self.server.listen(self.name):
            self.is_primary = False
            self._notify_existing_instance()
            return
        self.server.newConnection.connect(self._accept_connections)

    def _notify_existing_instance(self):
        socket = QLocalSocket(self)
        socket.connectToServer(self.name)
        if not socket.waitForConnected(350):
            return False
        socket.write(b"activate")
        socket.flush()
        socket.waitForBytesWritten(350)
        socket.disconnectFromServer()
        return True

    def _accept_connections(self):
        if not self.server:
            return
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.waitForReadyRead(80)
            socket.readAll()
            socket.disconnectFromServer()
            socket.deleteLater()
            self.activation_requested.emit()
