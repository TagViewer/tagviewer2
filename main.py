import json
import os
from collections import ChainMap
from enum import Enum
from enum import auto as enumauto
from operator import itemgetter
from os import path
from re import match as rlike
from threading import Timer
from typing import Callable, Optional
from warnings import warn

import appdirs
import gi
import toml

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, Gtk  # noqa: E402

VERSION = '2.0.0a'


class BuiltinSortProps(Enum):
	INTRINSIC = enumauto()
	TITLE = enumauto()
	SIZE = enumauto()
	RESOLUTION = enumauto()


class SortMethods(Enum):
	SORT_AZ = enumauto()
	SORT_ZA = enumauto()
	SORT_19 = enumauto()
	SORT_91 = enumauto()
	SORT_TF = enumauto()
	SORT_FT = enumauto()


class StateManager():
	def __init__(self, win: Gtk.Window, conf: dict, cache: dict):
		self.win = win
		self.conf = conf
		self.cache = cache
		self.tagviewer_meta = {}
		self.open_directory = None
		self.media_number = 1
		self.current_filters = []
		self.item_properties = []
		self.sort_by = BuiltinSortProps.INTRINSIC
		self.sort_method = None
		self.is_fullscreen = False
		self.slideshow_active = False
	filters_active = property(lambda self: len(self.current_filters) > 0)
	num_of_files = property(lambda self: len(self.current_files_json))
	current_files = property(lambda self: map(itemgetter('_path'),
	                         self.current_files_json))
	tagspace_is_open = property(lambda self: self.open_directory is not None)

	@property
	def current_files_json(self):
		if self.tagspace_is_open:
			if self.sort_by != BuiltinSortProps.INTRINSIC:
				pass
		else: return []

	def toggle_fullscreen(self):
		if self.is_fullscreen:
			self.win.top_bar_items['fullscreen_toggle_button'].get_icon_widget().set_from_file('icons/fullscreen.svg')
			self.win.unfullscreen()
			self.win.top_bar_items['left_expander'].set_expand(self.conf['ui']['center_toolbar_items']['in_normal'])
			pass  # TODO: disable autohide for widgets
			self.is_fullscreen = False
			if self.slideshow_active and self.conf['behavior']['slideshow']['end_on_fullscreen_exit']:
				pass  # TODO: End slideshow
		else:
			self.win.top_bar_items['fullscreen_toggle_button'].get_icon_widget().set_from_file('icons/fullscreen_exit.svg')
			self.win.fullscreen()
			self.win.top_bar_items['left_expander'].set_expand(self.conf['ui']['center_toolbar_items']['in_fullscreen'])
			pass  # TODO: enable autohide for widgets
			self.is_fullscreen = True


def debounce(wait):
	"""Postpone a functions execution until after some time has elapsed

	:type wait: int|float
	:param wait: The amount of Seconds to wait before the next call can execute.
	"""
	def decorator(fun):
		def debounced(*args, **kwargs):
			def call_it():
				fun(*args, **kwargs)
			try:
				debounced.t.cancel()
			except AttributeError:
				pass
			debounced.t = Timer(wait, call_it)
			debounced.t.start()
		return debounced
	return decorator


def check_config(obj):
	def config_test(value, prop, expected):
		if not isinstance(value, expected): warn(f'Bad type in config.toml: '
		                                         f'for {prop} expected type '
		                                         f'{expected}, got {repr(value)} '
		                                         f'of type {type(value)}')
	if 'ui' in obj:
		config_test(obj['ui'], 'ui', dict)
		if 'dark' in obj['ui']: config_test(obj['ui']['dark'], 'ui.dark', bool)
		if 'injections' in obj['ui']: config_test(obj['ui']["injections"], 'ui.injections', str)
		if 'sidebar_widths' in obj['ui']:
			config_test(obj['ui']["sidebar_widths"], 'ui.sidebar_widths', dict)
			if 'file_list' in obj['ui']["sidebar_widths"]: config_test(obj['ui']["sidebar_widths"]["file_list"], 'ui.sidebar_widths.file_list', int)
			if 'aside' in obj['ui']["sidebar_widths"]: config_test(obj['ui']["sidebar_widths"]["aside"], 'ui.sidebar_widths.aside', int)
			if 'save' in obj['ui']["sidebar_widths"]: config_test(obj['ui']["sidebar_widths"]["save"], 'ui.sidebar_widths.save', bool)
	if 'behavior' in obj:
		config_test(obj["behavior"], 'behavior', dict)
		if 'history' in obj["behavior"]:
			config_test(obj["behavior"]["history"], 'behavior.history', dict)
			if 'save_history' in obj["behavior"]["history"]:
				if 'save_history' in obj["behavior"]["history"]: config_test(obj["behavior"]["history"]["save_history"], 'behavior.history.save_history', bool)
				if 'save_previous' in obj["behavior"]["history"]: config_test(obj["behavior"]["history"]["save_previous"], 'behavior.history.save_previous', bool)
				if 'auto_resume' in obj["behavior"]["history"]: config_test(obj["behavior"]["history"]["auto_resume"], 'behavior.history.auto_resume', bool)
		if 'tagspace_defaults' in obj["behavior"]:
			config_test(obj["behavior"]["tagspace_defaults"], 'behavior.tagspace_defaults', dict)
			if 'tags' in obj["behavior"]["tagspace_defaults"]:
				config_test(obj["behavior"]["tagspace_defaults"]["tags"], 'behavior.tagspace_defaults.tags', list)
				for i in range(len(obj["behavior"]["tagspace_defaults"]["tags"])):
					if not isinstance(obj["behavior"]["tagspace_defaults"]["tags"][i], list):
						warn(f'Bad type in config.toml: for behavior.tagspace_defaults.tags[{i}] expected type list, '
						     f'got {repr(obj["behavior"]["tagspace_defaults"]["tags"][i])} of type {type(obj["behavior"]["tagspace_defaults"]["tags"][i])}')
					elif len(obj["behavior"]["tagspace_defaults"]["tags"][i]) != 2:
						warn(f'Bad type in config.toml: for behavior.tagspace_defaults.tags[{i}] expected length 2, '
						     f'got length {len(obj["behavior"]["tagspace_defaults"]["tags"][i])}')
					else:
						if not isinstance(obj["behavior"]["tagspace_defaults"]["tags"][i][0], str):
							warn(f'Bad type in config.toml: for behavior.tagspace_defaults.tags[{i}][0] expected type str, '
							     f'got {repr(obj["behavior"]["tagspace_defaults"]["tags"][i][0])} of type {type(obj["behavior"]["tagspace_defaults"]["tags"][i][0])}')
						if not isinstance(obj["behavior"]["tagspace_defaults"]["tags"][i][1], str):
							warn(f'Bad type in config.toml: for behavior.tagspace_defaults.tags[{i}][1] expected type str, '
							     f'got {repr(obj["behavior"]["tagspace_defaults"]["tags"][i][1])} of type {type(obj["behavior"]["tagspace_defaults"]["tags"][i][1])}')
						elif rlike('#[0-9a-fA-F]{6}', obj["behavior"]["tagspace_defaults"]["tags"][i][1]) is None:
							warn(f'Bad type in config.toml: for behavior.tagspace_defaults.tags[{i}][1] expected hex color string, '
							     f'got {repr(obj["behavior"]["tagspace_defaults"]["tags"][i][1])}')
			if 'props' in obj["behavior"]["tagspace_defaults"]:
				config_test(obj["behavior"]["tagspace_defaults"]["props"], 'behavior.tagspace_defaults.props', list)
				for i in range(len(obj["behavior"]["tagspace_defaults"]["props"])):
					if not isinstance(obj["behavior"]["tagspace_defaults"]["props"][i], list):
						warn(f'Bad type in config.toml: for behavior.tagspace_defaults.props[{i}] expected type list, '
						     f'got {repr(obj["behavior"]["tagspace_defaults"]["props"][i])} of type {type(obj["behavior"]["tagspace_defaults"]["props"][i])}')
					elif len(obj["behavior"]["tagspace_defaults"]["props"][i]) != 2:
						warn(f'Bad type in config.toml: for behavior.tagspace_defaults.props[{i}] expected length 2, '
						     f'got length {len(obj["behavior"]["tagspace_defaults"]["props"][i])}')
					else:
						if not isinstance(obj["behavior"]["tagspace_defaults"]["props"][i][0], str):
							warn(f'Bad type in config.toml: for behavior.tagspace_defaults.props[{i}][0] expected type str, '
							     f'got {repr(obj["behavior"]["tagspace_defaults"]["props"][i][0])} of type {type(obj["behavior"]["tagspace_defaults"]["props"][i][0])}')
						if not isinstance(obj["behavior"]["tagspace_defaults"]["props"][i][1], str):
							warn(f'Bad type in config.toml: for behavior.tagspace_defaults.props[{i}][1] expected type str, '
							     f'got {repr(obj["behavior"]["tagspace_defaults"]["props"][i][1])} of type {type(obj["behavior"]["tagspace_defaults"]["props"][i][1])}')
						elif not (obj["behavior"]["tagspace_defaults"]["props"][i][1] == 'String'
						          or obj["behavior"]["tagspace_defaults"]["props"][i][1] == 'Boolean'
						          or obj["behavior"]["tagspace_defaults"]["props"][i][1] == 'Number'):
							warn(f'Bad type in config.toml: for behavior.tagspace_defaults.props[{i}][1] expected valid type (Boolean, String, Number), '
							     f'got {repr(obj["behavior"]["tagspace_defaults"]["props"][i][1])}')
		if 'slideshow' in obj["behavior"]:
			if 'interval' in obj["behavior"]["slideshow"]:
				config_test(obj["behavior"]["slideshow"]["interval"], 'behavior.slideshow.interval', int)
			if 'end_on_fullscreen_exit' in obj["behavior"]["slideshow"]:
				config_test(obj["behavior"]["slideshow"]["end_on_fullscreen_exit"], 'behavior.slideshow.end_on_fullscreen_exit', bool)
			if 'stop_at_end' in obj["behavior"]["slideshow"]:
				config_test(obj["behavior"]["slideshow"]["stop_at_end"], 'behavior.slideshow.stop_at_end', bool)


class MainWindow(Gtk.Window):
	def __init__(self):
		Gtk.Window.__init__(self, title=f"TagViewer {VERSION}")
		self.set_default_size(1000, 600)

		if not path.exists(appdirs.user_config_dir('tagviewer')): os.mkdir(appdirs.user_config_dir('tagviewer'))
		if not path.exists(appdirs.user_cache_dir('tagviewer')): os.mkdir(appdirs.user_cache_dir('tagviewer'))
		if path.exists(path.join(appdirs.user_config_dir('tagviewer'), 'config.toml')):
			self._config = toml.load(path.join(appdirs.user_config_dir('tagviewer'), 'config.toml'))
		else:
			self._config = {}
		self.config = ChainMap(self._config, toml.load(path.join(path.dirname(__file__), 'fullconfig.toml')))

		if path.exists(path.join(appdirs.user_cache_dir('tagviewer'), 'cache.json')):
			with open(path.join(appdirs.user_cache_dir('tagviewer'), 'cache.json'), 'r') as cache_file:
				self._cache = json.load(cache_file)
		else:
			self._cache = {}
		with open(path.join(path.join(path.dirname(__file__), 'fullcache.json')), 'r') as cache_fallback:
			self.cache = ChainMap(self._cache, json.load(cache_fallback))

		check_config(self._config)

		self.state = StateManager(self, self.config, self.cache)

		css_provider = Gtk.CssProvider()
		css_provider.load_from_path('/home/matt/Desktop/code/python/tagviewer2/main.css')
		context = Gtk.StyleContext()
		context.add_provider_for_screen(Gdk.Screen.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

		self.base = Gtk.Box()
		self.base.set_orientation(Gtk.Orientation.VERTICAL)

		self.top_bar = Gtk.Toolbar()
		self.top_bar.set_icon_size(Gtk.IconSize.SMALL_TOOLBAR)
		self.top_bar.set_show_arrow(True)

		def add_toolbar_button(label: str, icon_name: str, callback: Optional[Callable[[Gtk.ToolButton], None]]=None, disabled: bool=False) -> Gtk.ToolButton:
			button = Gtk.ToolButton()
			button.set_sensitive(not disabled)
			button.set_label(label)
			image = Gtk.Image()
			image.show()
			image.set_from_file(f'icons/{icon_name}.svg')
			button.set_icon_widget(image)
			if callback is not None: button.connect('clicked', callback)
			self.top_bar.insert(button, self.top_bar.get_n_items())
			return button

		def add_toolbar_medianumber():
			spinbutton = Gtk.SpinButton()
			spinbutton.set_adjustment(Gtk.Adjustment(value=1, lower=1, upper=1, step_increment=1))
			spinbutton.set_sensitive(False)
			item = Gtk.ToolItem()
			item.add(spinbutton)
			self.top_bar.insert(item, self.top_bar.get_n_items())
			return item

		def add_toolbar_separator():
			separator = Gtk.SeparatorToolItem()
			separator.set_draw(True)
			self.top_bar.insert(separator, self.top_bar.get_n_items())
			return separator

		def add_toolbar_expander(expand=False):
			expander = Gtk.SeparatorToolItem()
			expander.set_draw(False)
			expander.set_expand(expand)
			self.top_bar.insert(expander, self.top_bar.get_n_items())
			return expander

		self.top_bar_items = {
			'left_expander': add_toolbar_expander(expand=self.config['ui']['center_toolbar_items']['in_normal']),
			'open_tagspace_button': add_toolbar_button('Open TagSpace', 'folder'),
			'new_tagspace_button': add_toolbar_button('New TagSpace', 'create_new_folder'),
			'recent_tagspace_button': add_toolbar_button('Open Previous TagSpace', 'undo', disabled=True),
			'add_media_button': add_toolbar_button('Add Media', 'add_photo_alternate', disabled=True),
			'separator1': add_toolbar_separator(),
			'go_first_button': add_toolbar_button('First Media', 'first_page', disabled=True),
			'go_prev_button': add_toolbar_button('Previous Media', 'navigate_before', disabled=True),
			'set_index_entry': add_toolbar_medianumber(),
			'go_next_button': add_toolbar_button('Next Media', 'navigate_next', disabled=True),
			'go_last_button': add_toolbar_button('Last Media', 'last_page', disabled=True),
			'separator2': add_toolbar_separator(),
			'open_external_button': add_toolbar_button('Open Media in Files', 'publish', disabled=True),
			'delete_media_button': add_toolbar_button('Delete Current Media', 'remove_circle', disabled=True),
			'replace_media_button': add_toolbar_button('Replace Current Media', 'flip_camera_ios', disabled=True),
			'separator3': add_toolbar_separator(),
			'remove_filter_button': add_toolbar_button('Remove Filters', 'filter_none', disabled=True),
			'separator4': add_toolbar_separator(),
			'slideshow_start_button': add_toolbar_button('Slideshow', 'slideshow_small', disabled=True),
			'slideshow_start_fs_button': add_toolbar_button('Slideshow (Fullscreen)', 'slideshow_large', disabled=True),
			'slideshow_end_button': add_toolbar_button('End Slideshow', 'stop', disabled=True),
			'separator5': add_toolbar_separator(),
			'configure_tagspace_button': add_toolbar_button('Configure TagSpace', 'edit', disabled=True),
			'settings_button': add_toolbar_button('Settings', 'settings'),
			'about_button': add_toolbar_button('About TagViewer', 'info'),
			'help_button': add_toolbar_button('TagViewer Help', 'help'),
			'separator6': add_toolbar_separator(),
			'fullscreen_toggle_button': add_toolbar_button('Toggle Fullscreen', 'fullscreen'),
			'dark_mode_toggle_button': add_toolbar_button('Light/Dark Mode', 'invert_colors'),
			'right_expander': add_toolbar_expander(expand=True)
		}
		self.top_bar_items['fullscreen_toggle_button'].connect('clicked', lambda widget: self.state.toggle_fullscreen())

		self.base.pack_start(self.top_bar, False, False, 0)

		self.middle_pane = Gtk.Paned()
		self.middle_pane_child = Gtk.Paned()

		self.file_list = Gtk.ListBox()

		self.file_list.add(Gtk.Label(label="file list"))

		self.content = Gtk.FlowBox()

		self.content.add(Gtk.Label(label="content"))

		self.aside = Gtk.Notebook()

		self.aside.set_show_border(False)

		self.aside.append_page(Gtk.Label(label='(properties)'), Gtk.Label(label='properties'))
		self.aside.append_page(Gtk.Label(label='(filters)'), Gtk.Label(label='filters'))

		self.middle_pane.pack1(self.file_list, resize=False, shrink=True)
		self.middle_pane_child.pack1(self.content, resize=True, shrink=False)
		self.middle_pane_child.pack2(self.aside, resize=False, shrink=True)
		self.middle_pane.pack2(self.middle_pane_child, resize=True, shrink=True)

		self.middle_pane.set_position(self.cache['sidebar_widths'][0])
		self.middle_pane_child.set_position(1000 - self.cache['sidebar_widths'][0] - self.cache['sidebar_widths'][1])

		if self.config['ui']['save_sidebar_widths']:
			@debounce(0.2)
			def file_list_resize(middle_pane: Gtk.Paned, *_):
				self.cache['sidebar_widths'][0] = middle_pane.get_position()
				return True
			self.middle_pane.connect('notify::position', file_list_resize)

			@debounce(0.2)
			def aside_resize(middle_pane_child: Gtk.Paned, *_):
				self.cache['sidebar_widths'][1] = self.get_size()[0] - self.middle_pane.get_position() - middle_pane_child.get_position()
				return True
			self.middle_pane_child.connect('notify::position', aside_resize)

		self.base.pack_start(self.middle_pane, True, True, 0)

		self.status_bar = Gtk.Box()
		self.status_bar.add(Gtk.Label(label="test"))
		self.base.pack_start(self.status_bar, False, False, 0)

		self.add(self.base)

	def exit_handler(self, *_):
		with open(path.join(appdirs.user_config_dir('tagviewer'), 'config.toml'), 'w') as config_file:
			toml.dump(self._config, config_file)
		with open(path.join(appdirs.user_cache_dir('tagviewer'), 'cache.json'), 'w') as cache_file:
			json.dump(self._cache, cache_file)

		Gtk.main_quit()


win = MainWindow()
win.connect("destroy", win.exit_handler)
win.show_all()
Gtk.main()
