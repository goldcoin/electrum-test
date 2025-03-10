import re
import os
import sys
import time
import datetime
import traceback
from decimal import Decimal
import threading
import asyncio
from typing import TYPE_CHECKING, Optional, Union, Callable, Sequence

from electrum_glc.storage import WalletStorage, StorageReadWriteError
from electrum_glc.wallet_db import WalletDB
from electrum_glc.wallet import Wallet, InternalAddressCorruption, Abstract_Wallet

from electrum_glc.plugin import run_hook
from electrum_glc import util
from electrum_glc.util import (profiler, InvalidPassword, send_exception_to_crash_reporter,
                               format_satoshis, format_satoshis_plain, format_fee_satoshis,
                               parse_max_spend)
from electrum_glc.util import EventListener, event_listener
from electrum_glc.invoices import PR_PAID, PR_FAILED, Invoice
from electrum_glc import blockchain
from electrum_glc.network import Network, TxBroadcastError, BestEffortRequestFailed
from electrum_glc.interface import PREFERRED_NETWORK_PROTOCOL, ServerAddr
from electrum_glc.logging import Logger
from electrum_glc.bitcoin import COIN

from electrum_glc.gui import messages
from .i18n import _
from .util import get_default_language
from . import KIVY_GUI_PATH

from kivy.app import App
from kivy.core.window import Window
from kivy.utils import platform
from kivy.properties import (OptionProperty, AliasProperty, ObjectProperty,
                             StringProperty, ListProperty, BooleanProperty, NumericProperty)
from kivy.cache import Cache
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.metrics import inch
from kivy.lang import Builder
from .uix.dialogs.password_dialog import OpenWalletDialog, ChangePasswordDialog, PincodeDialog, PasswordDialog
from .uix.dialogs.choice_dialog import ChoiceDialog

## lazy imports for factory so that widgets can be used in kv
#Factory.register('InstallWizard', module='electrum_glc.gui.kivy.uix.dialogs.installwizard')
#Factory.register('InfoBubble', module='electrum_glc.gui.kivy.uix.dialogs')
#Factory.register('OutputList', module='electrum_glc.gui.kivy.uix.dialogs')
#Factory.register('OutputItem', module='electrum_glc.gui.kivy.uix.dialogs')

from .uix.dialogs.installwizard import InstallWizard
from .uix.dialogs import InfoBubble, crash_reporter
from .uix.dialogs import OutputList, OutputItem
from .uix.dialogs import TopLabel, RefLabel
from .uix.dialogs.question import Question

#from kivy.core.window import Window
#Window.softinput_mode = 'below_target'

# delayed imports: for startup speed on android
notification = app = ref = None

# register widget cache for keeping memory down timeout to forever to cache
# the data
Cache.register('electrum_glc_widgets', timeout=0)

from kivy.uix.screenmanager import Screen
from kivy.uix.tabbedpanel import TabbedPanel
from kivy.uix.label import Label
from kivy.core.clipboard import Clipboard

Factory.register('TabbedCarousel', module='electrum_glc.gui.kivy.uix.screens')

# Register fonts without this you won't be able to use bold/italic...
# inside markup.
from kivy.core.text import Label
Label.register(
    'Roboto',
    KIVY_GUI_PATH + '/data/fonts/Roboto.ttf',
    KIVY_GUI_PATH + '/data/fonts/Roboto.ttf',
    KIVY_GUI_PATH + '/data/fonts/Roboto-Bold.ttf',
    KIVY_GUI_PATH + '/data/fonts/Roboto-Bold.ttf',
)


from electrum_glc.util import (NoDynamicFeeEstimates, NotEnoughFunds,
                               BITCOIN_BIP21_URI_SCHEME, LIGHTNING_URI_SCHEME,
                               UserFacingException)

from .uix.dialogs.lightning_open_channel import LightningOpenChannelDialog
from .uix.dialogs.lightning_channels import LightningChannelsDialog, SwapDialog

if TYPE_CHECKING:
    from . import ElectrumGui
    from electrum_glc.simple_config import SimpleConfig
    from electrum_glc.plugin import Plugins
    from electrum_glc.paymentrequest import PaymentRequest


class ElectrumWindow(App, Logger, EventListener):

    electrum_config = ObjectProperty(None)
    language = StringProperty('en')

    # properties might be updated by the network
    num_blocks = NumericProperty(0)
    num_nodes = NumericProperty(0)
    server_host = StringProperty('')
    server_port = StringProperty('')
    num_chains = NumericProperty(0)
    blockchain_name = StringProperty('')
    fee_status = StringProperty('Fee')
    balance = StringProperty('')
    fiat_balance = StringProperty('')
    is_fiat = BooleanProperty(False)
    blockchain_forkpoint = NumericProperty(0)

    lightning_gossip_num_peers = NumericProperty(0)
    lightning_gossip_num_nodes = NumericProperty(0)
    lightning_gossip_num_channels = NumericProperty(0)
    lightning_gossip_num_queries = NumericProperty(0)

    auto_connect = BooleanProperty(False)
    def on_auto_connect(self, instance, x):
        if not self._init_finished:
            return
        net_params = self.network.get_parameters()
        net_params = net_params._replace(auto_connect=self.auto_connect)
        self.network.run_from_another_thread(self.network.set_parameters(net_params))

    def set_auto_connect(self, b: bool):
        # This method makes sure we persist x into the config even if self.auto_connect == b.
        # Note: on_auto_connect() only gets called if the value of the self.auto_connect property *changes*.
        self.electrum_config.set_key('auto_connect', b)
        self.auto_connect = b

    def toggle_auto_connect(self, x):
        self.auto_connect = not self.auto_connect

    oneserver = BooleanProperty(False)
    def on_oneserver(self, instance, x):
        if not self._init_finished:
            return
        net_params = self.network.get_parameters()
        net_params = net_params._replace(oneserver=self.oneserver)
        self.network.run_from_another_thread(self.network.set_parameters(net_params))
    def toggle_oneserver(self, x):
        self.oneserver = not self.oneserver

    proxy_str = StringProperty('')
    def update_proxy_str(self, proxy: dict):
        mode = proxy.get('mode')
        host = proxy.get('host')
        port = proxy.get('port')
        self.proxy_str = (host + ':' + port) if mode else _('None')

    def choose_server_dialog(self, popup):
        protocol = PREFERRED_NETWORK_PROTOCOL
        def cb2(server_str):
            popup.ids.server_str.text = server_str
        servers = self.network.get_servers()
        server_choices = {}
        for _host, d in sorted(servers.items()):
            port = d.get(protocol)
            if port:
                server = ServerAddr(_host, port, protocol=protocol)
                server_choices[server.net_addr_str()] = _host
        ChoiceDialog(_('Choose a server'), server_choices, popup.ids.server_str.text, cb2).open()

    def maybe_switch_to_server(self, server_str: str):
        net_params = self.network.get_parameters()
        try:
            server = ServerAddr.from_str_with_inference(server_str)
            if not server: raise Exception("failed to parse")
        except Exception as e:
            self.show_error(_("Invalid server details: {}").format(repr(e)))
            return
        net_params = net_params._replace(server=server)
        self.network.run_from_another_thread(self.network.set_parameters(net_params))

    def choose_blockchain_dialog(self, dt):
        chains = self.network.get_blockchains()
        def cb(name):
            with blockchain.blockchains_lock: blockchain_items = list(blockchain.blockchains.items())
            for chain_id, b in blockchain_items:
                if name == b.get_name():
                    self.network.run_from_another_thread(self.network.follow_chain_given_id(chain_id))
        chain_objects = [blockchain.blockchains.get(chain_id) for chain_id in chains]
        chain_objects = filter(lambda b: b is not None, chain_objects)
        names = [b.get_name() for b in chain_objects]
        if len(names) > 1:
            cur_chain = self.network.blockchain().get_name()
            ChoiceDialog(_('Choose your chain'), names, cur_chain, cb).open()

    use_rbf = BooleanProperty(False)
    def on_use_rbf(self, instance, x):
        self.electrum_config.set_key('use_rbf', self.use_rbf, True)

    use_gossip = BooleanProperty(False)
    def on_use_gossip(self, instance, x):
        self.electrum_config.set_key('use_gossip', self.use_gossip, True)
        if self.network:
            if self.use_gossip:
                self.network.start_gossip()
            else:
                self.network.run_from_another_thread(
                    self.network.stop_gossip())

    enable_debug_logs = BooleanProperty(False)
    def on_enable_debug_logs(self, instance, x):
        self.electrum_config.set_key('gui_enable_debug_logs', self.enable_debug_logs, True)

    use_change = BooleanProperty(False)
    def on_use_change(self, instance, x):
        if self.wallet:
            self.wallet.use_change = self.use_change
            self.wallet.db.put('use_change', self.use_change)
            self.wallet.save_db()

    use_unconfirmed = BooleanProperty(False)
    def on_use_unconfirmed(self, instance, x):
        self.electrum_config.set_key('confirmed_only', not self.use_unconfirmed, True)

    use_recoverable_channels = BooleanProperty(True)
    def on_use_recoverable_channels(self, instance, x):
        self.electrum_config.set_key('use_recoverable_channels', self.use_recoverable_channels, True)

    def switch_to_send_screen(func):
        # try until send_screen is available
        def wrapper(self, *args):
            f = lambda dt: (bool(func(self, *args) and False) if self.send_screen else bool(self.switch_to('send') or True)) if self.wallet else True
            Clock.schedule_interval(f, 0.1)
        return wrapper

    @switch_to_send_screen
    def set_URI(self, uri):
        self.send_screen.set_URI(uri)

    def on_new_intent(self, intent):
        data = str(intent.getDataString())
        scheme = str(intent.getScheme()).lower()
        if scheme == BITCOIN_BIP21_URI_SCHEME or scheme == LIGHTNING_URI_SCHEME:
            self.set_URI(data)

    def on_language(self, instance, language):
        self.logger.info('language: {}'.format(language))
        _.switch_lang(language)

    def update_history(self, *dt):
        if self.history_screen:
            self.history_screen.update()

    @event_listener
    def on_event_on_quotes(self):
        self.logger.info("on_quotes")
        self._trigger_update_status()
        self._trigger_update_history()

    @event_listener
    def on_event_on_history(self):
        self.logger.info("on_history")
        if self.wallet:
            self.wallet.clear_coin_price_cache()
        self._trigger_update_history()

    @event_listener
    def on_event_fee_histogram(self, *args):
        self._trigger_update_history()

    @event_listener
    def on_event_request_status(self, wallet, key, status):
        if wallet != self.wallet:
            return
        req = self.wallet.get_request(key)
        if req is None:
            return
        if self.receive_screen:
            if status == PR_PAID:
                self.receive_screen.update()
            else:
                self.receive_screen.update_item(key, req)
        if self.request_popup and self.request_popup.key == key:
            self.request_popup.update_status()
        if status == PR_PAID:
            self.show_info(_('Payment Received') + '\n' + key)
            self._trigger_update_history()

    @event_listener
    def on_event_invoice_status(self, wallet, key, status):
        if wallet != self.wallet:
            return
        req = self.wallet.get_invoice(key)
        if req is None:
            return
        if self.send_screen:
            if status == PR_PAID:
                self.send_screen.update()
            else:
                self.send_screen.update_item(key, req)

        if self.invoice_popup and self.invoice_popup.key == key:
            self.invoice_popup.update_status()

    @event_listener
    def on_event_payment_succeeded(self, wallet, key):
        if wallet != self.wallet:
            return
        description = self.wallet.get_label_for_rhash(key)
        self.show_info(_('Payment succeeded') + '\n\n' + description)
        self._trigger_update_history()

    @event_listener
    def on_event_payment_failed(self, wallet, key, reason):
        if wallet != self.wallet:
            return
        self.show_info(_('Payment failed') + '\n\n' + reason)

    def _get_bu(self):
        return self.electrum_config.get_base_unit()

    def _set_bu(self, value):
        self.electrum_config.set_base_unit(value)
        self._trigger_update_status()
        self._trigger_update_history()

    wallet_name = StringProperty(_('No Wallet'))
    base_unit = AliasProperty(_get_bu, _set_bu)
    fiat_unit = StringProperty('')

    def on_fiat_unit(self, a, b):
        self._trigger_update_history()

    def decimal_point(self):
        return self.electrum_config.get_decimal_point()

    def btc_to_fiat(self, amount_str):
        if not amount_str:
            return ''
        if not self.fx.is_enabled():
            return ''
        rate = self.fx.exchange_rate()
        if rate.is_nan():
            return ''
        fiat_amount = self.get_amount(amount_str + ' ' + self.base_unit) * rate / COIN
        return "{:.2f}".format(fiat_amount).rstrip('0').rstrip('.')

    def fiat_to_btc(self, fiat_amount):
        if not fiat_amount:
            return ''
        rate = self.fx.exchange_rate()
        if rate.is_nan():
            return ''
        satoshis = COIN * Decimal(fiat_amount) / Decimal(rate)
        return format_satoshis_plain(satoshis, decimal_point=self.decimal_point())

    def get_amount(self, amount_str: str) -> Optional[int]:
        if not amount_str:
            return None
        a, u = amount_str.split()
        assert u == self.base_unit
        try:
            x = Decimal(a)
        except:
            return None
        p = pow(10, self.decimal_point())
        return int(p * x)


    _orientation = OptionProperty('landscape',
                                 options=('landscape', 'portrait'))

    def _get_orientation(self):
        return self._orientation

    orientation = AliasProperty(_get_orientation,
                                None,
                                bind=('_orientation',))
    '''Tries to ascertain the kind of device the app is running on.
    Cane be one of `tablet` or `phone`.

    :data:`orientation` is a read only `AliasProperty` Defaults to 'landscape'
    '''

    _ui_mode = OptionProperty('phone', options=('tablet', 'phone'))

    def _get_ui_mode(self):
        return self._ui_mode

    ui_mode = AliasProperty(_get_ui_mode,
                            None,
                            bind=('_ui_mode',))
    '''Defines tries to ascertain the kind of device the app is running on.
    Cane be one of `tablet` or `phone`.

    :data:`ui_mode` is a read only `AliasProperty` Defaults to 'phone'
    '''

    _init_finished = False

    def __init__(self, **kwargs):
        # initialize variables
        self._clipboard = Clipboard
        self.info_bubble = None
        self.nfcscanner = None
        self.tabs = None
        self.is_exit = False
        self.wallet = None  # type: Optional[Abstract_Wallet]
        self.pause_time = 0
        self.asyncio_loop = util.get_asyncio_loop()
        self.password = None
        self._use_single_password = False
        self.resume_dialog = None
        self.gui_thread = threading.current_thread()

        App.__init__(self)#, **kwargs)
        Logger.__init__(self)

        self.electrum_config = config = kwargs.get('config', None)  # type: SimpleConfig
        self.language = config.get('language', get_default_language())
        self.network = network = kwargs.get('network', None)  # type: Network
        if self.network:
            self.num_blocks = self.network.get_local_height()
            self.num_nodes = len(self.network.get_interfaces())
            net_params = self.network.get_parameters()
            self.server_host = net_params.server.host
            self.server_port = str(net_params.server.port)
            self.auto_connect = net_params.auto_connect
            self.oneserver = net_params.oneserver
            self.proxy_config = net_params.proxy if net_params.proxy else {}
            self.update_proxy_str(self.proxy_config)

        self.plugins = kwargs.get('plugins', None)  # type: Plugins
        self.gui_object = kwargs.get('gui_object', None)  # type: ElectrumGui
        self.daemon = self.gui_object.daemon
        self.fx = self.daemon.fx
        self.use_rbf = config.get('use_rbf', True)
        self.use_gossip = config.get('use_gossip', False)
        self.use_unconfirmed = not config.get('confirmed_only', False)
        self.enable_debug_logs = config.get('gui_enable_debug_logs', False)

        # create triggers so as to minimize updating a max of 2 times a sec
        self._trigger_update_wallet = Clock.create_trigger(self.update_wallet, .5)
        self._trigger_update_status = Clock.create_trigger(self.update_status, .5)
        self._trigger_update_history = Clock.create_trigger(self.update_history, .5)
        self._trigger_update_interfaces = Clock.create_trigger(self.update_interfaces, .5)

        self._periodic_update_status_during_sync = Clock.schedule_interval(self.update_wallet_synchronizing_progress, .5)

        # cached dialogs
        self._settings_dialog = None
        self._channels_dialog = None
        self._addresses_dialog = None
        self.set_fee_status()
        self.invoice_popup = None
        self.request_popup = None

        self._init_finished = True

    def on_pr(self, pr: 'PaymentRequest'):
        Clock.schedule_once(lambda dt, pr=pr: self._on_pr(pr))

    def _on_pr(self, pr: 'PaymentRequest'):
        if not self.wallet:
            self.show_error(_('No wallet loaded.'))
            return
        if pr.verify(self.wallet.contacts):
            invoice = Invoice.from_bip70_payreq(pr, height=0)
            if invoice and self.wallet.get_invoice_status(invoice) == PR_PAID:
                self.show_error("invoice already paid")
                self.send_screen.do_clear()
            elif pr.has_expired():
                self.show_error(_('Payment request has expired'))
            else:
                self.switch_to('send')
                self.send_screen.set_request(pr)
        else:
            self.show_error("invoice error:" + pr.error)
            self.send_screen.do_clear()

    def on_qr(self, data: str):
        self.on_data_input(data)

    def on_data_input(self, data: str) -> None:
        """on_qr / on_paste shared logic"""
        data = data.strip()
        if data.lower().startswith('channel_backup:'):
            self.import_channel_backup(data)
            return
        # try to decode as transaction
        from electrum_glc.transaction import tx_from_any
        try:
            tx = tx_from_any(data)
        except:
            tx = None
        if tx:
            self.tx_dialog(tx)
            return
        # try to decode as URI/address
        self.set_URI(data)

    def update_tab(self, name):
        s = getattr(self, name + '_screen', None)
        if s:
            s.update()

    @profiler
    def update_tabs(self):
        for name in ['send', 'history', 'receive']:
            self.update_tab(name)

    def switch_to(self, name):
        s = getattr(self, name + '_screen', None)
        panel = self.tabs.ids.panel
        tab = self.tabs.ids[name + '_tab']
        panel.switch_to(tab)

    def show_request(self, key):
        from .uix.dialogs.request_dialog import RequestDialog
        self.request_popup = RequestDialog('Request', key)
        self.request_popup.open()

    def show_invoice(self, key):
        from .uix.dialogs.invoice_dialog import InvoiceDialog
        invoice = self.wallet.get_invoice(key)
        if not invoice:
            return
        data = invoice.lightning_invoice if invoice.is_lightning() else key
        self.invoice_popup = InvoiceDialog('Invoice', data, key)
        self.invoice_popup.open()

    def qr_dialog(self, title, data, show_text=False, text_for_clipboard=None, help_text=None):
        from .uix.dialogs.qr_dialog import QRDialog
        def on_qr_failure():
            popup.dismiss()
            msg = _('Failed to display QR code.')
            if text_for_clipboard:
                msg += '\n' + _('Text copied to clipboard.')
                self._clipboard.copy(text_for_clipboard)
            Clock.schedule_once(lambda dt: self.show_info(msg))
        popup = QRDialog(
            title, data, show_text,
            failure_cb=on_qr_failure,
            text_for_clipboard=text_for_clipboard,
            help_text=help_text)
        popup.open()

    def scan_qr(self, on_complete):
        if platform != 'android':
            return self.scan_qr_non_android(on_complete)
        from jnius import autoclass, cast
        from android import activity
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        SimpleScannerActivity = autoclass("org.electrum.qr.SimpleScannerActivity")
        Intent = autoclass('android.content.Intent')
        intent = Intent(PythonActivity.mActivity, SimpleScannerActivity)

        def on_qr_result(requestCode, resultCode, intent):
            try:
                if resultCode == -1:  # RESULT_OK:
                    #  this doesn't work due to some bug in jnius:
                    # contents = intent.getStringExtra("text")
                    String = autoclass("java.lang.String")
                    contents = intent.getStringExtra(String("text"))
                    on_complete(contents)
            except Exception as e:  # exc would otherwise get lost
                send_exception_to_crash_reporter(e)
            finally:
                activity.unbind(on_activity_result=on_qr_result)
        activity.bind(on_activity_result=on_qr_result)
        PythonActivity.mActivity.startActivityForResult(intent, 0)

    def scan_qr_non_android(self, on_complete):
        from electrum_glc import qrscanner
        try:
            video_dev = self.electrum_config.get_video_device()
            data = qrscanner.scan_barcode(video_dev)
            if data is not None:
                on_complete(data)
        except UserFacingException as e:
            self.show_error(e)
        except BaseException as e:
            self.logger.exception('camera error')
            self.show_error(repr(e))

    def do_share(self, data, title):
        if platform != 'android':
            return
        from jnius import autoclass, cast
        JS = autoclass('java.lang.String')
        Intent = autoclass('android.content.Intent')
        sendIntent = Intent()
        sendIntent.setAction(Intent.ACTION_SEND)
        sendIntent.setType("text/plain")
        sendIntent.putExtra(Intent.EXTRA_TEXT, JS(data))
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        currentActivity = cast('android.app.Activity', PythonActivity.mActivity)
        it = Intent.createChooser(sendIntent, cast('java.lang.CharSequence', JS(title)))
        currentActivity.startActivity(it)

    def build(self):
        return Builder.load_file(KIVY_GUI_PATH + '/main.kv')

    def _pause(self):
        if platform == 'android':
            # move activity to back
            from jnius import autoclass
            python_act = autoclass('org.kivy.android.PythonActivity')
            mActivity = python_act.mActivity
            mActivity.moveTaskToBack(True)

    def handle_crash_on_startup(func):
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                self.logger.exception('crash on startup')
                from .uix.dialogs.crash_reporter import CrashReporter
                # show the crash reporter, and when it's closed, shutdown the app
                cr = CrashReporter(self, exctype=type(e), value=e, tb=e.__traceback__)
                cr.on_dismiss = lambda: self.stop()
                Clock.schedule_once(lambda _, cr=cr: cr.open(), 0)
        return wrapper

    @handle_crash_on_startup
    def on_start(self):
        ''' This is the start point of the kivy ui
        '''
        import time
        self.logger.info('Time to on_start: {} <<<<<<<<'.format(time.process_time()))
        Window.bind(size=self.on_size, on_keyboard=self.on_keyboard)
        #Window.softinput_mode = 'below_target'
        self.on_size(Window, Window.size)
        self.init_ui()
        crash_reporter.ExceptionHook(self)
        # init plugins
        run_hook('init_kivy', self)
        # fiat currency
        self.fiat_unit = self.fx.ccy if self.fx.is_enabled() else ''
        # default tab
        self.switch_to('history')
        # bind intent for bitcoin: URI scheme
        if platform == 'android':
            from android import activity
            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            mactivity = PythonActivity.mActivity
            self.on_new_intent(mactivity.getIntent())
            activity.bind(on_new_intent=self.on_new_intent)
        self.register_callbacks()
        if self.network and self.electrum_config.get('auto_connect') is None:
            self.popup_dialog("first_screen")
            # load_wallet_on_start will be called later, after initial network setup is completed
        else:
            # load wallet
            self.load_wallet_on_start()
            # URI passed in config
            uri = self.electrum_config.get('url')
            if uri:
                self.set_URI(uri)

    @event_listener
    def on_event_channel_db(self, num_nodes, num_channels, num_policies):
        self.lightning_gossip_num_nodes = num_nodes
        self.lightning_gossip_num_channels = num_channels

    @event_listener
    def on_event_gossip_peers(self, num_peers):
        self.lightning_gossip_num_peers = num_peers

    @event_listener
    def on_event_unknown_channels(self, unknown):
        self.lightning_gossip_num_queries = unknown

    def get_wallet_path(self):
        if self.wallet:
            return self.wallet.storage.path
        else:
            return ''

    def on_wizard_success(self, storage, db, password):
        self.password = password
        if self.electrum_config.get('single_password'):
            self._use_single_password = self.daemon.update_password_for_directory(
                old_password=password, new_password=password)
        self.logger.info(f'use single password: {self._use_single_password}')
        wallet = Wallet(db, storage, config=self.electrum_config)
        wallet.start_network(self.daemon.network)
        self.daemon.add_wallet(wallet)
        self.load_wallet(wallet)

    def on_wizard_aborted(self):
        # wizard did not return a wallet; and there is no wallet open atm
        if not self.wallet:
            self.stop()

    def load_wallet_by_name(self, path):
        if not path:
            return
        if self.wallet and self.wallet.storage.path == path:
            return
        if self.password and self._use_single_password:
            storage = WalletStorage(path)
            # call check_password to decrypt
            storage.check_password(self.password)
            self.on_open_wallet(self.password, storage)
            return
        d = OpenWalletDialog(self, path, self.on_open_wallet)
        d.open()

    def load_wallet_on_start(self):
        """As part of app startup, try to load last wallet."""
        self.load_wallet_by_name(self.electrum_config.get_wallet_path(use_gui_last_wallet=True))

    def on_open_wallet(self, password, storage):
        if not storage.file_exists():
            wizard = InstallWizard(self.electrum_config, self.plugins)
            wizard.path = storage.path
            wizard.run('new')
        else:
            assert storage.is_past_initial_decryption()
            db = WalletDB(storage.read(), manual_upgrades=False)
            assert not db.requires_upgrade()
            self.on_wizard_success(storage, db, password)

    def on_stop(self):
        self.logger.info('on_stop')
        self.stop_wallet()

    def stop_wallet(self):
        if self.wallet:
            self.daemon.stop_wallet(self.wallet.storage.path)
            self.wallet = None

    def on_keyboard(self, instance, key, keycode, codepoint, modifiers):
        if key == 27 and self.is_exit is False:
            self.is_exit = True
            self.show_info(_('Press again to exit'))
            return True
        # override settings button
        if key in (319, 282): #f1/settings button on android
            #self.gui.main_gui.toggle_settings(self)
            return True

    def settings_dialog(self):
        from .uix.dialogs.settings import SettingsDialog
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(self)
        else:
            self._settings_dialog.update()
        self._settings_dialog.open()

    def lightning_open_channel_dialog(self):
        if not self.wallet.has_lightning():
            self.show_error(_('Lightning is not enabled for this wallet'))
            return
        if not self.wallet.lnworker.channels and not self.wallet.lnworker.channel_backups:
            warning = _(messages.MSG_LIGHTNING_WARNING)
            d = Question(_('Do you want to create your first channel?') +
                         '\n\n' + warning, self.open_channel_dialog_with_warning)
            d.open()
        else:
            d = LightningOpenChannelDialog(self)
            d.open()

    def swap_dialog(self):
        d = SwapDialog(self, self.electrum_config)
        d.open()

    def open_channel_dialog_with_warning(self, b):
        if b:
            d = LightningOpenChannelDialog(self)
            d.open()

    def lightning_channels_dialog(self):
        if self._channels_dialog is None:
            self._channels_dialog = LightningChannelsDialog(self)
        self._channels_dialog.open()

    def delete_ln_gossip_dialog(self):
        def delete_gossip(b: bool):
            if not b:
                return
            if self.network:
                self.network.run_from_another_thread(
                    self.network.stop_gossip(full_shutdown=True))

            os.unlink(gossip_db_file)
            self.show_error(_("Local gossip database deleted."))
            self.network.start_gossip()

        if self.network is None or self.network.channel_db is None:
            return  # TODO show msg to user, or the button should be disabled instead
        gossip_db_file = self.network.channel_db.get_file_path(self.electrum_config)
        try:
            size_mb = os.path.getsize(gossip_db_file) / (1024**2)
        except OSError:
            self.logger.exception("Cannot get file size.")
            return
        d = Question(
            _('Do you want to delete the local gossip database?') + '\n' +
            '(' + _('file size') + f': {size_mb:.2f} MiB)\n' +
            _('It will be automatically re-downloaded after, unless you disable the gossip.'),
            delete_gossip)
        d.open()

    @event_listener
    def on_event_channel(self, wallet, chan):
        if self._channels_dialog:
            Clock.schedule_once(lambda dt: self._channels_dialog.update())

    @event_listener
    def on_event_channels(self, wallet):
        if self._channels_dialog:
            Clock.schedule_once(lambda dt: self._channels_dialog.update())

    def is_wallet_creation_disabled(self):
        return bool(self.electrum_config.get('single_password')) and self.password is None

    def wallets_dialog(self):
        from .uix.dialogs.wallets import WalletDialog
        dirname = os.path.dirname(self.electrum_config.get_wallet_path())
        d = WalletDialog(dirname, self.load_wallet_by_name, self.is_wallet_creation_disabled())
        d.open()

    def popup_dialog(self, name):
        if name == 'settings':
            self.settings_dialog()
        elif name == 'wallets':
            self.wallets_dialog()
        elif name == 'status':
            popup = Builder.load_file(KIVY_GUI_PATH + f'/uix/ui_screens/{name}.kv')
            master_public_keys_layout = popup.ids.master_public_keys
            for xpub in self.wallet.get_master_public_keys()[1:]:
                master_public_keys_layout.add_widget(TopLabel(text=_('Master Public Key')))
                ref = RefLabel()
                ref.name = _('Master Public Key')
                ref.data = xpub
                master_public_keys_layout.add_widget(ref)
            popup.open()
        elif name == 'lightning_channels_dialog' and not self.wallet.can_have_lightning():
            self.show_error(_("Not available for this wallet.") + "\n\n" +
                            _("Lightning is currently restricted to HD wallets with p2wpkh addresses."))
        elif name.endswith("_dialog"):
            getattr(self, name)()
        else:
            popup = Builder.load_file(KIVY_GUI_PATH + f'/uix/ui_screens/{name}.kv')
            popup.open()

    @profiler
    def init_ui(self):
        ''' Initialize The Ux part of electrum. This function performs the basic
        tasks of setting up the ui.
        '''
        #from weakref import ref

        self.funds_error = False
        # setup UX
        self.screens = {}

        #setup lazy imports for mainscreen
        Factory.register('AnimatedPopup',
                         module='electrum_glc.gui.kivy.uix.dialogs')
        Factory.register('QRCodeWidget',
                         module='electrum_glc.gui.kivy.uix.qrcodewidget')

        # preload widgets. Remove this if you want to load the widgets on demand
        #Cache.append('electrum_glc_widgets', 'AnimatedPopup', Factory.AnimatedPopup())
        #Cache.append('electrum_glc_widgets', 'QRCodeWidget', Factory.QRCodeWidget())

        # load and focus the ui
        self.root.manager = self.root.ids['manager']

        self.history_screen = None
        self.send_screen = None
        self.receive_screen = None
        self.icon = os.path.dirname(KIVY_GUI_PATH) + "/icons/electrum-ltc.png"
        self.tabs = self.root.ids['tabs']

    def update_interfaces(self, dt):
        net_params = self.network.get_parameters()
        self.num_nodes = len(self.network.get_interfaces())
        self.num_chains = len(self.network.get_blockchains())
        chain = self.network.blockchain()
        self.blockchain_forkpoint = chain.get_max_forkpoint()
        self.blockchain_name = chain.get_name()
        interface = self.network.interface
        if interface:
            self.server_host = interface.host
        else:
            self.server_host = str(net_params.server.host) + ' (connecting...)'
        self.proxy_config = net_params.proxy or {}
        self.update_proxy_str(self.proxy_config)

    @event_listener
    def on_event_network_updated(self):
        self._trigger_update_interfaces()
        self._trigger_update_status()

    @event_listener
    def on_event_wallet_updated(self, *args):
        self._trigger_update_wallet()
        self._trigger_update_status()

    @event_listener
    def on_event_blockchain_updated(self, *args):
        # to update number of confirmations in history
        self._trigger_update_wallet()

    @event_listener
    def on_event_status(self, *args):
        self._trigger_update_status()

    @event_listener
    def on_event_new_transaction(self, *args):
        self._trigger_update_wallet()

    @event_listener
    def on_event_verified(self, *args):
        self._trigger_update_wallet()

    @profiler
    def load_wallet(self, wallet: 'Abstract_Wallet'):
        if self.wallet:
            self.stop_wallet()
        self.wallet = wallet
        self.wallet_name = wallet.basename()
        self.update_wallet()
        # Once GUI has been initialized check if we want to announce something
        # since the callback has been called before the GUI was initialized
        if self.receive_screen:
            self.receive_screen.clear()
        self.update_tabs()
        run_hook('load_wallet', wallet, self)
        try:
            wallet.try_detecting_internal_addresses_corruption()
        except InternalAddressCorruption as e:
            self.show_error(str(e))
            send_exception_to_crash_reporter(e)
            return
        self.use_change = self.wallet.use_change
        self.electrum_config.save_last_wallet(wallet)
        self.request_focus_for_main_view()

    def request_focus_for_main_view(self):
        if platform != 'android':
            return
        # The main view of the activity might be not have focus
        # in which case e.g. the OS "back" button would not work.
        # see #6276 (specifically "method 2" and "method 3")
        from jnius import autoclass
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity
        activity.requestFocusForMainView()

    def update_status(self, *dt):
        if not self.wallet:
            return
        if self.network is None or not self.network.is_connected():
            status = _("Offline")
        elif self.network.is_connected():
            self.num_blocks = self.network.get_local_height()
            server_height = self.network.get_server_height()
            server_lag = self.num_blocks - server_height
            if not self.wallet.is_up_to_date() or server_height == 0:
                num_sent, num_answered = self.wallet.adb.get_history_sync_state_details()
                status = ("{} [size=18dp]({}/{})[/size]"
                          .format(_("Synchronizing..."), num_answered, num_sent))
            elif server_lag > 1:
                status = _("Server is lagging ({} blocks)").format(server_lag)
            else:
                status = ''
        else:
            status = _("Disconnected")
        if status:
            self.balance = status
            self.fiat_balance = status
        else:
            c, u, x = self.wallet.get_balance()
            l = int(self.wallet.lnworker.get_balance()) if self.wallet.lnworker else 0
            balance_sat = c + u + x + l
            text = self.format_amount(balance_sat)
            self.balance = str(text.strip()) + ' [size=22dp]%s[/size]'% self.base_unit
            self.fiat_balance = self.fx.format_amount(balance_sat) + ' [size=22dp]%s[/size]'% self.fx.ccy

    def update_wallet_synchronizing_progress(self, *dt):
        if not self.wallet:
            return
        if not self.wallet.is_up_to_date():
            self._trigger_update_status()

    def get_max_amount(self):
        from electrum_glc.transaction import PartialTxOutput
        if run_hook('abort_send', self):
            return ''
        inputs = self.wallet.get_spendable_coins(None)
        if not inputs:
            return ''
        addr = None
        if self.send_screen:
            addr = str(self.send_screen.address)
        if not addr:
            addr = self.wallet.dummy_address()
        outputs = [PartialTxOutput.from_address_and_value(addr, '!')]
        try:
            tx = self.wallet.make_unsigned_transaction(coins=inputs, outputs=outputs)
        except NoDynamicFeeEstimates as e:
            Clock.schedule_once(lambda dt, bound_e=e: self.show_error(str(bound_e)))
            return ''
        except NotEnoughFunds:
            return ''
        except InternalAddressCorruption as e:
            self.show_error(str(e))
            send_exception_to_crash_reporter(e)
            return ''
        amount = tx.output_value()
        __, x_fee_amount = run_hook('get_tx_extra_fee', self.wallet, tx) or (None, 0)
        amount_after_all_fees = amount - x_fee_amount
        return format_satoshis_plain(amount_after_all_fees, decimal_point=self.decimal_point())

    def format_amount(self, x, is_diff=False, whitespaces=False):
        return self.electrum_config.format_amount(x, is_diff=is_diff, whitespaces=whitespaces)

    def format_amount_and_units(self, x) -> str:
        if x is None:
            return 'none'
        if parse_max_spend(x):
            return f'max({x})'
        # FIXME this is using format_satoshis_plain instead of config.format_amount
        #       as we sometimes convert the returned string back to numbers,
        #       via self.get_amount()... the need for converting back should be removed
        return format_satoshis_plain(x, decimal_point=self.decimal_point()) + ' ' + self.base_unit

    def format_amount_and_units_with_fiat(self, x) -> str:
        text = self.format_amount_and_units(x)
        fiat = self.fx.format_amount_and_units(x) if self.fx else None
        if text and fiat:
            text += f' ({fiat})'
        return text

    def format_fee_rate(self, fee_rate):
        # fee_rate is in sat/kB
        return format_fee_satoshis(fee_rate/1000) + ' sat/byte'

    #@profiler
    def update_wallet(self, *dt):
        self._trigger_update_status()
        if self.wallet and (self.wallet.is_up_to_date() or not self.network or not self.network.is_connected()):
            self.update_tabs()

    def notify(self, message):
        try:
            global notification, os
            if not notification:
                from plyer import notification
            icon = (os.path.dirname(os.path.realpath(__file__))
                    + '/../../' + self.icon)
            notification.notify('Electrum-LTC', message,
                            app_icon=icon, app_name='Electrum-LTC')
        except ImportError:
            self.logger.Error('Notification: needs plyer; `sudo python3 -m pip install plyer`')

    def on_pause(self):
        self.pause_time = time.time()
        # pause nfc
        if self.nfcscanner:
            self.nfcscanner.nfc_disable()
        return True

    def on_resume(self):
        if self.nfcscanner:
            self.nfcscanner.nfc_enable()
        if self.resume_dialog is not None:
            return
        now = time.time()
        if self.wallet and self.has_pin_code() and now - self.pause_time > 5*60:
            def on_success(x):
                self.resume_dialog = None
            d = PincodeDialog(
                self,
                check_password=self.check_pin_code,
                on_success=on_success,
                on_failure=self.stop)
            self.resume_dialog = d
            d.open()

    def on_size(self, instance, value):
        width, height = value
        self._orientation = 'landscape' if width > height else 'portrait'
        self._ui_mode = 'tablet' if min(width, height) > inch(3.51) else 'phone'

    def on_ref_label(self, label, *, show_text_with_qr: bool = True):
        if not label.data:
            return
        self.qr_dialog(label.name, label.data, show_text_with_qr)

    def scheduled_in_gui_thread(func):
        """Decorator to ensure that func runs in the GUI thread.
        Note: the return value is swallowed!
        """
        def wrapper(self: 'ElectrumWindow', *args, **kwargs):
            if threading.current_thread() == self.gui_thread:
                func(self, *args, **kwargs)
            else:
                Clock.schedule_once(lambda dt: func(self, *args, **kwargs))
        return wrapper

    def show_error(self, error, width='200dp', pos=None, arrow_pos=None,
                   exit=False, icon=f'atlas://{KIVY_GUI_PATH}/theming/atlas/light/error', duration=0,
                   modal=False):
        ''' Show an error Message Bubble.
        '''
        self.show_info_bubble(text=error, icon=icon, width=width,
            pos=pos or Window.center, arrow_pos=arrow_pos, exit=exit,
            duration=duration, modal=modal)

    def show_info(self, error, width='200dp', pos=None, arrow_pos=None,
                  exit=False, duration=0, modal=False):
        ''' Show an Info Message Bubble.
        '''
        self.show_error(error, icon=f'atlas://{KIVY_GUI_PATH}/theming/atlas/light/important',
            duration=duration, modal=modal, exit=exit, pos=pos,
            arrow_pos=arrow_pos)

    @scheduled_in_gui_thread
    def show_info_bubble(self, text=_('Hello World'), pos=None, duration=0,
                         arrow_pos='bottom_mid', width=None, icon='', modal=False, exit=False):
        '''Method to show an Information Bubble

        .. parameters::
            text: Message to be displayed
            pos: position for the bubble
            duration: duration the bubble remains on screen. 0 = click to hide
            width: width of the Bubble
            arrow_pos: arrow position for the bubble
        '''
        text = str(text)  # so that we also handle e.g. Exception
        info_bubble = self.info_bubble
        if not info_bubble:
            info_bubble = self.info_bubble = Factory.InfoBubble()

        win = Window
        if info_bubble.parent:
            win.remove_widget(info_bubble
                                 if not info_bubble.modal else
                                 info_bubble._modal_view)

        if not arrow_pos:
            info_bubble.show_arrow = False
        else:
            info_bubble.show_arrow = True
            info_bubble.arrow_pos = arrow_pos
        img = info_bubble.ids.img
        if text == 'texture':
            # icon holds a texture not a source image
            # display the texture in full screen
            text = ''
            img.texture = icon
            info_bubble.fs = True
            info_bubble.show_arrow = False
            img.allow_stretch = True
            info_bubble.dim_background = True
            info_bubble.background_image = f'atlas://{KIVY_GUI_PATH}/theming/atlas/light/card'
        else:
            info_bubble.fs = False
            info_bubble.icon = icon
            #if img.texture and img._coreimage:
            #    img.reload()
            img.allow_stretch = False
            info_bubble.dim_background = False
            info_bubble.background_image = 'atlas://data/images/defaulttheme/bubble'
        info_bubble.message = text
        if not pos:
            pos = (win.center[0], win.center[1] - (info_bubble.height/2))
        info_bubble.show(pos, duration, width, modal=modal, exit=exit)

    def tx_dialog(self, tx):
        from .uix.dialogs.tx_dialog import TxDialog
        d = TxDialog(self, tx)
        d.open()

    def show_transaction(self, txid):
        tx = self.wallet.db.get_transaction(txid)
        if not tx and self.wallet.lnworker:
            tx = self.wallet.adb.get_transaction(txid)
        if tx:
            self.tx_dialog(tx)
        else:
            self.show_error(f'Transaction not found {txid}')

    def lightning_tx_dialog(self, tx):
        from .uix.dialogs.lightning_tx_dialog import LightningTxDialog
        d = LightningTxDialog(self, tx)
        d.open()

    def sign_tx(self, *args):
        threading.Thread(target=self._sign_tx, args=args).start()

    def _sign_tx(self, tx, password, on_success, on_failure):
        try:
            self.wallet.sign_transaction(tx, password)
        except InvalidPassword:
            Clock.schedule_once(lambda dt: on_failure(_("Invalid PIN")))
            return
        on_success = run_hook('tc_sign_wrapper', self.wallet, tx, on_success, on_failure) or on_success
        Clock.schedule_once(lambda dt: on_success(tx))

    def _broadcast_thread(self, tx, on_complete):
        status = False
        try:
            self.network.run_from_another_thread(self.network.broadcast_transaction(tx))
        except TxBroadcastError as e:
            msg = e.get_message_for_gui()
        except BestEffortRequestFailed as e:
            msg = repr(e)
        else:
            status, msg = True, tx.txid()
        Clock.schedule_once(lambda dt: on_complete(status, msg))

    def broadcast(self, tx):
        def on_complete(ok, msg):
            if ok:
                self.show_info(_('Payment sent.'))
                if self.send_screen:
                    self.send_screen.do_clear()
            else:
                msg = msg or ''
                self.show_error(msg)

        if self.network and self.network.is_connected():
            self.show_info(_('Sending'))
            threading.Thread(target=self._broadcast_thread, args=(tx, on_complete)).start()
        else:
            self.show_info(_('Cannot broadcast transaction') + ':\n' + _('Not connected'))

    def description_dialog(self, screen):
        from .uix.dialogs.label_dialog import LabelDialog
        text = screen.message
        def callback(text):
            screen.message = text
        d = LabelDialog(_('Enter description'), text, callback)
        d.open()

    def amount_dialog(self, screen, show_max):
        from .uix.dialogs.amount_dialog import AmountDialog
        amount = screen.amount
        if amount:
            amount, u = str(amount).split()
            assert u == self.base_unit
        def cb(amount):
            if amount == '!':
                screen.is_max = True
                max_amt = self.get_max_amount()
                screen.amount = (max_amt + ' ' + self.base_unit) if max_amt else ''
            else:
                screen.amount = amount
                screen.is_max = False
        popup = AmountDialog(show_max, amount, cb)
        popup.open()

    def addresses_dialog(self):
        from .uix.dialogs.addresses import AddressesDialog
        if self._addresses_dialog is None:
            self._addresses_dialog = AddressesDialog(self)
        else:
            self._addresses_dialog.update()
        self._addresses_dialog.open()

    def fee_dialog(self):
        from .uix.dialogs.fee_dialog import FeeDialog
        fee_dialog = FeeDialog(self, self.electrum_config, self.set_fee_status)
        fee_dialog.open()

    def set_fee_status(self):
        target, tooltip, dyn = self.electrum_config.get_fee_target()
        self.fee_status = target

    @event_listener
    def on_event_fee(self, *arg):
        self.set_fee_status()

    def protected(self, msg, f, args):
        if self.electrum_config.get('pin_code'):
            msg += "\n" + _("Enter your PIN code to proceed")
            on_success = lambda pw: f(*args, self.password)
            d = PincodeDialog(
                self,
                message = msg,
                check_password=self.check_pin_code,
                on_success=on_success,
                on_failure=lambda: None)
            d.open()
        else:
            d = Question(
                msg,
                lambda b: f(*args, self.password) if b else None,
                yes_str=_("OK"),
                no_str=_("Cancel"),
                title=_("Confirm action"))
            d.open()

    def delete_wallet(self):
        basename = os.path.basename(self.wallet.storage.path)
        d = Question(_('Delete wallet?') + '\n' + basename, self._delete_wallet)
        d.open()

    def _delete_wallet(self, b):
        if b:
            basename = self.wallet.basename()
            self.protected(_("Are you sure you want to delete wallet {}?").format(basename),
                           self.__delete_wallet, ())

    def __delete_wallet(self, pw):
        wallet_path = self.get_wallet_path()
        basename = os.path.basename(wallet_path)
        if self.wallet.has_password():
            try:
                self.wallet.check_password(pw)
            except InvalidPassword:
                self.show_error("Invalid password")
                return
        self.stop_wallet()
        os.unlink(wallet_path)
        self.show_error(_("Wallet removed: {}").format(basename))
        new_path = self.electrum_config.get_wallet_path(use_gui_last_wallet=True)
        self.load_wallet_by_name(new_path)

    def show_seed(self, label):
        self.protected(_("Display your seed?"), self._show_seed, (label,))

    def _show_seed(self, label, password):
        if self.wallet.has_password() and password is None:
            return
        keystore = self.wallet.keystore
        seed = keystore.get_seed(password)
        passphrase = keystore.get_passphrase(password)
        label.data = seed
        if passphrase:
            label.data += '\n\n' + _('Passphrase') + ': ' + passphrase

    def has_pin_code(self):
        return bool(self.electrum_config.get('pin_code'))

    def check_pin_code(self, pin):
        if pin != self.electrum_config.get('pin_code'):
            raise InvalidPassword

    def change_password(self, cb):
        def on_success(old_password, new_password):
            # called if old_password works on self.wallet
            self.password = new_password
            if self._use_single_password:
                self.daemon.update_password_for_directory(old_password=old_password, new_password=new_password)
                msg = _("Password updated successfully")
            else:
                self.wallet.update_password(old_password, new_password)
                msg = _("Password updated for {}").format(os.path.basename(self.wallet.storage.path))
            self.show_info(msg)
        on_failure = lambda: self.show_error(_("Password not updated"))
        d = ChangePasswordDialog(self, self.wallet, on_success, on_failure)
        d.open()

    def pin_code_dialog(self, cb):
        if self._use_single_password and self.has_pin_code():
            def on_choice(choice):
                if choice == 0:
                    self.change_pin_code(cb)
                else:
                    self.reset_pin_code(cb)
            choices = {0:'Change PIN code', 1:'Reset PIN'}
            dialog = ChoiceDialog(
                _('PIN Code'), choices, 0,
                on_choice,
                keep_choice_order=True)
            dialog.open()
        else:
            self.change_pin_code(cb)

    def reset_pin_code(self, cb):
        on_success = lambda x: self._set_new_pin_code(None, cb)
        d = PasswordDialog(self,
            basename = self.wallet.basename(),
            check_password = self.wallet.check_password,
            on_success=on_success,
            on_failure=lambda: None,
            is_change=False,
            has_password=self.wallet.has_password())
        d.open()

    def _set_new_pin_code(self, new_pin, cb):
        self.electrum_config.set_key('pin_code', new_pin)
        cb()
        self.show_info(_("PIN updated") if new_pin else _('PIN disabled'))

    def change_pin_code(self, cb):
        on_failure = lambda: self.show_error(_("PIN not updated"))
        on_success = lambda old_pin, new_pin: self._set_new_pin_code(new_pin, cb)
        d = PincodeDialog(
            self,
            check_password=self.check_pin_code,
            on_success=on_success,
            on_failure=on_failure,
            is_change=True,
            has_password = self.has_pin_code())
        d.open()

    def save_backup(self):
        if platform != 'android':
            backup_dir = self.electrum_config.get_backup_dir()
            if backup_dir:
                self._save_backup(backup_dir)
            else:
                self.show_error(_("Backup NOT saved. Backup directory not configured."))
            return

        from android.permissions import request_permissions, Permission
        def cb(permissions, grant_results: Sequence[bool]):
            if not grant_results or not grant_results[0]:
                self.show_error(_("Cannot save backup without STORAGE permission"))
                return
            try:
                backup_dir = util.android_backup_dir()
            except OSError as e:
                self.logger.exception("Cannot save backup")
                self.show_error(f"Cannot save backup: {e!r}")
                return
            # note: Clock.schedule_once is a hack so that we get called on a non-daemon thread
            #       (needed for WalletDB.write)
            Clock.schedule_once(lambda dt: self._save_backup(backup_dir))
        request_permissions([Permission.WRITE_EXTERNAL_STORAGE], cb)

    def _save_backup(self, backup_dir):
        try:
            new_path = self.wallet.save_backup(backup_dir)
        except Exception as e:
            self.logger.exception("Failed to save wallet backup")
            self.show_error("Failed to save wallet backup" + '\n' + str(e))
            return
        self.show_info(_("Backup saved:") + f"\n{new_path}")

    def export_private_keys(self, pk_label, addr):
        if self.wallet.is_watching_only():
            self.show_info(_('This is a watching-only wallet. It does not contain private keys.'))
            return
        def show_private_key(addr, pk_label, password):
            if self.wallet.has_password() and password is None:
                return
            if not self.wallet.can_export():
                return
            try:
                key = str(self.wallet.export_private_key(addr, password))
                pk_label.data = key
            except InvalidPassword:
                self.show_error("Invalid PIN")
                return
        self.protected(_("Decrypt your private key?"), show_private_key, (addr, pk_label))

    def import_channel_backup(self, encrypted):
        if not self.wallet.has_lightning():
            msg = _('Cannot import channel backup.')
            if self.wallet.can_have_lightning():
                msg += ' ' + _('Lightning is not enabled.')
            else:
                msg += ' ' + _('Lightning is not available for this wallet.')
            self.show_error(msg)
            return
        d = Question(_('Import Channel Backup?'), lambda b: self._import_channel_backup(b, encrypted))
        d.open()

    def _import_channel_backup(self, b, encrypted):
        if not b:
            return
        try:
            self.wallet.lnworker.import_channel_backup(encrypted)
        except Exception as e:
            self.logger.exception("failed to import backup")
            self.show_error("failed to import backup" + '\n' + str(e))
            return
        self.lightning_channels_dialog()

    def lightning_status(self):
        if self.wallet.has_lightning():
            if self.wallet.lnworker.has_deterministic_node_id():
                status = _('Enabled')
            else:
                status = _('Enabled, non-recoverable channels')
        else:
            if self.wallet.can_have_lightning():
                status = _('Not enabled')
            else:
                status = _("Not available for this wallet.")
        return status

    def on_lightning_status(self, root):
        if self.wallet.has_lightning():
            if self.wallet.lnworker.has_deterministic_node_id():
                pass
            else:
                if self.wallet.db.get('seed_type') == 'segwit':
                    msg = _("Your channels cannot be recovered from seed, because they were created with an old version of Electrum. "
                            "This means that you must save a backup of your wallet everytime you create a new channel.\n\n"
                            "If you want this wallet to have recoverable channels, you must close your existing channels and restore this wallet from seed")
                else:
                    msg = _("Your channels cannot be recovered from seed. "
                            "This means that you must save a backup of your wallet everytime you create a new channel.\n\n"
                            "If you want to have recoverable channels, you must create a new wallet with an Electrum seed")
                self.show_info(msg)
        elif self.wallet.can_have_lightning():
            root.dismiss()
            if self.wallet.can_have_deterministic_lightning():
                msg = _(
                    "Lightning is not enabled because this wallet was created with an old version of Electrum. "
                    "Create lightning keys?")
            else:
                msg = _(
                    "Warning: this wallet type does not support channel recovery from seed. "
                    "You will need to backup your wallet everytime you create a new channel. "
                    "Create lightning keys?")
            d = Question(msg, self._enable_lightning, title=_('Enable Lightning?'))
            d.open()

    def _enable_lightning(self, b):
        if not b:
            return
        self.wallet.init_lightning(password=self.password)
        self.show_info(_('Lightning keys have been initialized.'))
