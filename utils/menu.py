import gi
import dbus
import time

gi.require_version('Keybinder', '3.0')

from gi.repository import GLib
from gi.repository import Keybinder

from utils.fuzzy import match_replace
from utils.window import WindowManager
from utils.service import MyService

from handlers.default import HudMenu
from handlers.global_menu import GlobalMenu

from menu_model.menu_model import DbusGtkMenu, DbusAppMenu


class DbusMenu:

	def __init__(self):
		self.keyb = GlobalKeybinder(self.on_keybind_activated)
		self.app = None
		self.session = dbus.SessionBus()
		self.window = WindowManager.new_window()
		self.tries = 0
		self.retry_timer_id = 0
		self.collect_timer = 0
		self._init_window()
		self._listen_menu_activated()
		self._listen_hud_activated()
		self._width_offset = 300
		WindowManager.add_listener(self.on_window_switched)

	def _init_window(self):
		self.appmenu = DbusAppMenu(self.session, self.window)
		self.gtkmenu = DbusGtkMenu(self.session, self.window)
		self._update()

	def on_window_switched(self, window):
		self.reset_timeout()
		self.window = window
		self._init_window()

	def reset_timeout(self):
		if self.retry_timer_id:
			GLib.source_remove(self.retry_timer_id)
		self.tries = 0
		self.retry_timer_id = 0

		if self.collect_timer:
			GLib.source_remove(self.collect_timer)

	def _listen_menu_activated(self):
		proxy  = self.session.get_object(MyService.BUS_NAME, MyService.BUS_PATH)
		signal = proxy.connect_to_signal("MenuActivated", self.on_menu_activated)

	def _listen_hud_activated(self):
		proxy  = self.session.get_object(MyService.BUS_NAME, MyService.BUS_PATH)
		signal = proxy.connect_to_signal("HudActivated", self.on_hud_activated)

	def on_menu_activated(self, menu: str, x: int):
		if menu == '__fildem_move':
			self._move_menu(x)
			return

		if x != -1:
			self._width_offset = x
		self._start_app(menu)

	def on_hud_activated(self):
		menu = HudMenu(self)
		menu.run()

	def on_keybind_activated(self, character: str):
		self.on_app_started()
		self._start_app(character)

	def _move_menu(self, x: int):
		if self.app is None:
			return

		self.app.move_window(x) 

	def _start_app(self, menu_activated: str):
		if self.app is None:
			self.app = GlobalMenu(self, menu_activated, self._width_offset)
			self.app.connect('shutdown', self.on_app_shutdown)
			self.app.run()

	def on_app_started(self):
		self._echo_onoff(True)

	def on_app_shutdown(self, app):
		self._echo_onoff(False)
		self.app = None

	def _echo_onoff(self, on: bool):
		self.proxy = dbus.SessionBus().get_object(MyService.BUS_NAME, MyService.BUS_PATH)
		self.proxy.EchoMenuOnOff(on)

	def _handle_shortcuts(self, top_level_menus):
		self.keyb.remove_all_keybindings()
		for label in top_level_menus:
			idx = label.find('_')
			if idx == -1:
				continue
			c = label[idx + 1]
			self.keyb.add_keybinding(c)

	def _retry_init(self):
		self.retry_timer_id = 0
		self._init_window()

	def _add_retry(self):
		N = 2 # Amount of tries
		if self.tries < N and not len(self.items):
			self.tries += 1
			self.retry_timer_id = GLib.timeout_add_seconds(2, self._retry_init)

	def collect_entries(self):
		def collect():
			self.collect_timer = 0
			self.gtkmenu.collect_entries()
			self.appmenu.collect_entries()

		self.collect_timer = GLib.timeout_add(200, collect)

	def _update(self):
		self.gtkmenu.get_results()
		top_level_menus = self.gtkmenu.get_top_level_menus()
		if not len(top_level_menus):
			self.appmenu.get_results()
			top_level_menus = self.appmenu.get_top_level_menus()

		if not len(top_level_menus):
			self._add_retry()
		else:
			self.collect_entries()
		self._send_msg(top_level_menus)
		self._handle_shortcuts(top_level_menus)

	def _send_msg(self, top_level_menus):
		if len(top_level_menus) == 0:
			top_level_menus = dbus.Array(signature="s")
		proxy  = self.session.get_object(MyService.BUS_NAME, MyService.BUS_PATH)
		proxy.EchoSendTopLevelMenus(top_level_menus)

	@property
	def prompt(self):
		return self.window.get_app_name()

	@property
	def actions(self):
		actions = self.gtkmenu.actions
		if not len(actions):
			actions = self.appmenu.actions

		self.handle_empty(actions)

		return actions.keys()

	def accel(self):
		accel = self.gtkmenu.accels
		if not len(accel):
			accel = self.appmenu.accels
		return accel

	@property
	def items(self):
		items = self.appmenu.items
		if not len(items):
			items = self.gtkmenu.items
		return items

	def activate(self, selection):
		if selection in self.gtkmenu.actions:
			self.gtkmenu.activate(selection)

		elif selection in self.appmenu.actions:
			self.appmenu.activate(selection)

	def handle_empty(self, actions):
		if not len(actions):
			alert = 'No menu items available!'
			promt = ''
			try:
				promt = self.prompt
			except Exception as e:
				pass
			print('Gnome HUD: WARNING: (%s) %s' % (promt, alert))


class GlobalKeybinder(object):
	"""
	Global keybinder for mnemonic, like Alt+F for files, etc.
	"""
	def __init__(self, callback=None):
		super(GlobalKeybinder, self).__init__()
		Keybinder.init()
		self.keybinding_strings = []
		self.keybinder_callback = callback

	def add_keybinding(self, character):
		acc = '<Alt>' + character
		Keybinder.bind(acc, lambda accelerator: self.on_keybind_activated(character))
		self.keybinding_strings.append(acc)

	def on_keybind_activated(self, char):
		self.keybinder_callback(char)

	def remove_all_keybindings(self):
		for k in self.keybinding_strings:
			Keybinder.unbind(k)
		self.keybinding_strings = []
