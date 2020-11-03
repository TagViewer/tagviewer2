import json
import os
import subprocess
from enum import Enum
from enum import auto as enumauto
from operator import itemgetter
from os import path
from re import match as rlike
import platform
from shutil import copyfile
import sys
from threading import Timer
from typing import Callable, Optional

import appdirs
import gi
import toml

from stateman import StateMan

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, Gtk, GdkPixbuf  # noqa: E402

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


def open_file(filename: str):
	'''Open file with default application.'''
	useros = platform.system()
	if useros == 'Windows':
		os.startfile(filename)
	elif useros == 'Darwin':
		subprocess.Popen(['open', filename])
	elif useros == 'Linux':
		subprocess.Popen(['xdg-open', filename])
	else:
		raise OSError(f"No suitable file opening utility was found for your operating system. Please open the file manually; the path is “{filename}”.")


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


class SettingsWindow(Gtk.Dialog):
	def __init__(self, parent, conf):
		Gtk.Dialog.__init__(self, 'Settings', parent, modal=True, destroy_with_parent=True)
		self.add_button('OK', Gtk.ResponseType.ACCEPT)
		self.conf = conf
		self.base = self.get_child()

		self.panel = Gtk.Stack()
		self.panel.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
		self.panel.set_transition_duration(200)

		self.ui_settings_panel = Gtk.ListBox()
		self.ui_settings_panel.set_selection_mode(Gtk.SelectionMode.NONE)

		self.behavior_settings_panel = Gtk.ListBox()
		self.behavior_settings_panel.set_selection_mode(Gtk.SelectionMode.NONE)

		self.panel.add_titled(self.ui_settings_panel, 'ui', 'UI')
		self.panel.add_titled(self.behavior_settings_panel, 'behavior', 'Behavior')

		self.panel_select = Gtk.StackSwitcher()
		self.panel_select.set_stack(self.panel)

		self.base.pack_start(self.panel_select, False, False, 0)
		self.base.pack_end(self.panel, True, True, 0)
		self.base.show_all()


class MainWindow(Gtk.Window):
	def __init__(self):
		Gtk.Window.__init__(self, title=f"TagViewer {VERSION}")
		self.set_default_size(1000, 600)

		if not path.exists(appdirs.user_config_dir('tagviewer')): os.mkdir(appdirs.user_config_dir('tagviewer'))
		if not path.exists(appdirs.user_cache_dir('tagviewer')): os.mkdir(appdirs.user_cache_dir('tagviewer'))
		self.load_config()
		self.load_cache()

		css_provider = Gtk.CssProvider()
		css_provider.load_from_path('main.css')
		context = Gtk.StyleContext()
		context.add_provider_for_screen(Gdk.Screen.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

		css_provider_2 = Gtk.CssProvider()
		css_provider_2.load_from_data(self.config['ui']['injections'].encode())
		context.add_provider_for_screen(Gdk.Screen.get_default(), css_provider_2, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

		self.state = StateMan({
			'tagviewer_meta': {},
			'files': (lambda model: model['tagviewer_meta']['files'] if 'files' in tagviewer_meta else [], ('tagviewer_meta',)),
			'open_directory': None,
			'media_number': 1,
			'filters': [],
			'sort_options': None,
			'is_fullscreen': False,
			'dark_mode': self.config['ui']['dark'],
			'injections': self.config['ui']['injections'],
			'slideshow_active': False,
			'filters_active': (lambda model: len(model['filters']) > 0, ('filters',)),
			'num_of_files': (lambda model: len(model['files'], ('files',))),
			'file_paths': (lambda model: map(itemgetter('_path'), model['files']), ('files',)),
			'tagspace_is_open': (lambda model: model['open_directory'] is not None, ('open_directory')),
			'media_is_open': (lambda model: model['tagspace_is_open'] and ('_path' in model['current_item'] or model['filters_active'] or len(model['files']) == 0), ('tagspace_is_open', 'current_item', 'filters_active', 'files')),
			'can_go_previous': (lambda model: model['media_number'] > 1, ('media_number',)),
			'can_go_next': (lambda model: len(model['files']) > 0 and len(model['files']) > model['media_number'], ('files', 'media_number')),
			'current_item': (lambda model: model['files'][model['media_number']] if model['media_number'] in files else {}, ('media_number',)),  # deps doesn't include `files` intentionally!
			'current_path': (lambda model: model['current_item']['_path'] if model['media_is_open'] else None, ('current_item', 'media_is_open')),
			'current_tags': (lambda model: list(map(lambda x: model['tagviewer_meta']['tagList'][x], model['current_item']['tags'])) if 'tagList' in model['tagviewer_meta'] else [], ('current_item', 'tagviewer_meta'))
		}, refs={'win': self, 'conf': self.config, 'cache': self.cache, 'settings': Gtk.Settings.get_default(), 'injections_provider': css_provider_2})

		def handle_fullscreen_change(model, _):
			if model['is_fullscreen']:
				model.refs['win'].top_bar_items['fullscreen_toggle_button'].get_icon_widget().set_from_file(f'icons/{("dark" if model["dark_mode"] else "light")}/fullscreen_exit.svg')
				model.refs['win'].fullscreen()
				model.refs['win'].top_bar_items['left_expander'].set_expand(model.refs['conf']['ui']['center_toolbar_items']['in_fullscreen'])
				pass  # TODO: enable autohide for widgets
			else:
				model.refs['win'].top_bar_items['fullscreen_toggle_button'].get_icon_widget().set_from_file(f'icons/{("dark" if model["dark_mode"] else "light")}/fullscreen.svg')
				model.refs['win'].unfullscreen()
				model.refs['win'].top_bar_items['left_expander'].set_expand(model.refs['conf']['ui']['center_toolbar_items']['in_normal'])
				pass  # TODO: disable autohide for widgets
				if model['slideshow_active'] and model.refs['conf']['behavior']['slideshow']['end_on_fullscreen_exit']:
					model['slideshow_active'] = False
		self.state.bind('is_fullscreen', handle_fullscreen_change)

		def handle_dark_mode_change(model, _):
			model.refs['settings'].set_property('gtk-application-prefer-dark-theme', model['dark_mode'])
			model.refs['conf']['ui']['dark'] = model['dark_mode']

		self.state.bind('dark_mode', handle_dark_mode_change)

		def handle_injections_change(model, _):
			model.refs['injections_provider'].load_from_data(model['injections'].encode())
			model.refs['conf']['ui']['injections'] = model['injections']

		self.state.bind('injections', handle_injections_change)

		css_provider = Gtk.CssProvider()
		css_provider.load_from_path('main.css')
		context = Gtk.StyleContext()
		context.add_provider_for_screen(Gdk.Screen.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

		Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', self.config['ui']['dark'])

		self.base = Gtk.Box()
		self.base.set_orientation(Gtk.Orientation.VERTICAL)

		self.top_bar = Gtk.Toolbar()
		self.top_bar.set_icon_size(Gtk.IconSize.SMALL_TOOLBAR)
		self.top_bar.set_show_arrow(True)

		def add_toolbar_button(label: str, icon_name: str, callback: Optional[Callable[[Gtk.ToolButton], None]]=None, disabled: bool=False) -> Gtk.ToolButton:
			button = Gtk.ToolButton()
			button.set_sensitive(not disabled)
			button.set_label(label)
			button.set_tooltip_text(label)
			image = Gtk.Image()
			image.show()
			image.set_from_file(f'icons/{"dark" if self.state["dark_mode"] else "light"}/{icon_name}.svg')
			button.set_icon_widget(image)
			button.icon_name = icon_name
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

		def invert_icon_colors(model, _):
			top_bar_items = model.refs['win'].top_bar_items
			for btn in filter(lambda item: item.endswith('button'), top_bar_items):
				item = top_bar_items[btn]
				if btn == 'fullscreen_toggle_button':
					item.get_icon_widget().set_from_file(f'icons/{"dark" if model["dark_mode"] else "light"}/{"fullscreen_exit" if model["is_fullscreen"] else "fullscreen"}.svg')
				else:
					item.get_icon_widget().set_from_file(f'icons/{"dark" if model["dark_mode"] else "light"}/{item.icon_name}.svg')
		self.state.bind('dark_mode', invert_icon_colors)

		def toggle_fullscreen():
			self.state['is_fullscreen'] = not self.state['is_fullscreen']
		self.top_bar_items['fullscreen_toggle_button'].connect('clicked', lambda widget: toggle_fullscreen())

		def toggle_dark_mode():
			self.state['dark_mode'] = not self.state['dark_mode']
		self.top_bar_items['dark_mode_toggle_button'].connect('clicked', lambda widget: toggle_dark_mode())

		self.about_dialog = Gtk.AboutDialog()
		self.about_dialog.set_program_name('TagViewer 2')
		self.about_dialog.set_version(VERSION)
		self.about_dialog.set_copyright('Copyright (C) 2020  Matt Fellenz, under the GPL 3.0')
		self.about_dialog.set_comments('A simple program that allows viewing of media within a TagSpace, and rich filtering of that media with tags and properties that are stored by the program.')
		with open('LICENSE') as f:
			self.about_dialog.set_license(''.join(f.readlines()))
		self.about_dialog.set_website('https://github.com/tagviewer/tagviewer2')
		self.about_dialog.set_authors(('Matt Fellenz',))
		self.about_dialog.set_logo(GdkPixbuf.Pixbuf.new_from_file('logos/universal/icon.png'))
		self.about_dialog.connect('close', lambda *_: self.about_dialog.hide())
		self.about_dialog.connect('response', lambda *_: self.about_dialog.hide())

		def show_about_dialog(*_):
			self.about_dialog.show()

		self.top_bar_items['about_button'].connect('clicked', show_about_dialog)

		def show_settings_dialog(*_):
			settings_dialog = SettingsWindow(self, self.config, self.state)
			settings_dialog.run()
			settings_dialog.hide()

		self.top_bar_items['settings_button'].connect('clicked', show_settings_dialog)

		self.base.pack_start(self.top_bar, False, False, 0)

		self.middle_pane = Gtk.Paned()
		self.middle_pane_child = Gtk.Paned()

		self.file_list = Gtk.ListBox()

		self.file_list.add(Gtk.Label(label="file list"))

		self.file_list.set_selection_mode(Gtk.SelectionMode.BROWSE)

		self.content = Gtk.Box()
		self.content.set_hexpand(True)
		self.content.set_vexpand(True)
		self.content.set_halign(Gtk.Align.CENTER)
		self.content.set_valign(Gtk.Align.CENTER)

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

	def load_config(self):
		if path.exists(path.join(appdirs.user_config_dir('tagviewer'), 'config.toml')):
			self.config = toml.load(path.join(appdirs.user_config_dir('tagviewer'), 'config.toml'))
		else:
			self.config = toml.load(path.join(path.dirname(__file__), 'fullconfig.toml'))
			copyfile(path.join(path.dirname(__file__), 'fullconfig.toml'), path.join(appdirs.user_config_dir('tagviewer'), 'config.toml'))

	def load_cache(self):
		if path.exists(path.join(appdirs.user_cache_dir('tagviewer'), 'cache.json')):
			with open(path.join(appdirs.user_cache_dir('tagviewer'), 'cache.json'), 'r') as cache_file:
				self.cache = json.load(cache_file)
		else:
			with open(path.join(path.join(path.dirname(__file__), 'fullcache.json')), 'r') as cache_fallback:
				self.cache = json.load(cache_fallback)

	def exit_handler(self, *_):
		with open(path.join(appdirs.user_config_dir('tagviewer'), 'config.toml'), 'w') as config_file:
			toml.dump(self.config, config_file)
		with open(path.join(appdirs.user_cache_dir('tagviewer'), 'cache.json'), 'w') as cache_file:
			json.dump(self.cache, cache_file)

		Gtk.main_quit()


def graphical_except_hook(exctype, value, traceback):
	msg = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, text=f'{exctype.__name__}: {str(value)}')
	msg.run()
	msg.hide()
sys.excepthook = graphical_except_hook

win = MainWindow()
win.connect("destroy", win.exit_handler)
win.show_all()
Gtk.main()
