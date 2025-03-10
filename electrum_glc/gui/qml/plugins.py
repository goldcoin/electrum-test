from PyQt5.QtCore import pyqtSignal, pyqtSlot, pyqtProperty, QObject

from electrum_glc.i18n import _
from electrum_glc.logging import get_logger

class PluginQObject(QObject):
    logger = get_logger(__name__)

    pluginChanged = pyqtSignal()
    busyChanged = pyqtSignal()
    pluginEnabledChanged = pyqtSignal()

    _busy = False

    def __init__(self, plugin, parent):
        super().__init__(parent)
        self.plugin = plugin
        self.app = parent

    @pyqtProperty(str, notify=pluginChanged)
    def name(self): return self._name

    @pyqtProperty(bool, notify=busyChanged)
    def busy(self): return self._busy

    @pyqtProperty(bool, notify=pluginEnabledChanged)
    def pluginEnabled(self): return self.plugin.is_enabled()

    @pluginEnabled.setter
    def pluginEnabled(self, enabled):
        if enabled != self.plugin.is_enabled():
            self.logger.debug(f'can {self.plugin.can_user_disable()}, {self.plugin.is_available()}')
            if not self.plugin.can_user_disable() and not enabled:
                return
            if enabled:
                self.app.plugins.enable(self.plugin.name)
            else:
                self.app.plugins.disable(self.plugin.name)
            self.pluginEnabledChanged.emit()

