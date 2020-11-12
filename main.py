import json
import os
import subprocess
import traceback
from enum import Enum
from enum import auto as enumauto
from operator import itemgetter
from os import path
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

from gi.repository import Gdk, Gtk, GdkPixbuf, GLib  # noqa: E402

VERSION = '2.0.0a'


class ConfigError(Exception):
	pass


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


def convert_list_store_to_list(list_store):
	return list(map(list, list_store))


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
	def __init__(self, parent, conf, state):
		Gtk.Dialog.__init__(self, 'Settings', parent, modal=True, destroy_with_parent=True)
		self.set_name('settingsDialog')
		self.set_default_size(700, 500)
		self.add_button('OK', Gtk.ResponseType.ACCEPT)
		self.conf = conf
		self.state = state
		self.base = self.get_child()

		self.main = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
		self.main.set_name('main')

		self.model = Gtk.TreeStore(str)
		ui_parent = self.model.append(None, ['UI'])
		self.model.append(ui_parent, ['Center Toolbar Items'])
		behavior_parent = self.model.append(None, ['Behavior'])
		self.model.append(behavior_parent, ['History'])
		tagspace_defaults_parent = self.model.append(behavior_parent, ['TagSpace Defaults'])
		self.model.append(tagspace_defaults_parent, ['Tags'])
		self.model.append(tagspace_defaults_parent, ['Props'])
		self.model.append(behavior_parent, ['Slideshow'])

		self.tree = Gtk.TreeView(model=self.model)
		self.tree.append_column(Gtk.TreeViewColumn('Name', Gtk.CellRendererText(), text=0))
		self.tree.set_headers_visible(False)
		self.tree.set_enable_search(True)
		self.tree.set_enable_tree_lines(False)

		self.tree.expand_all()

		self.main.pack_start(self.tree, False, False, 0)

		def generate_settings_panel(panel_name, *settings):
			container = Gtk.Grid()
			panel_label = Gtk.Label(label=panel_name)
			panel_label.set_halign(Gtk.Align.START)
			container.attach(panel_label, 0, 0, 3, 1)
			for i, setting in enumerate(settings, start=1):
				# setting: (name label, type of input, extra info for type if necessary,
				# value, setter fn, help text?)
				label = Gtk.Label(label=setting[0])
				label.set_halign(Gtk.Align.END)
				container.attach(label, 0, i, 1, 1)
				if setting[1] == 'entry':
					control = Gtk.Entry()
					control.set_text(setting[3])
					control.connect('changed', lambda self, *_, callbackfn=setting[4]: callbackfn(self.get_text()))
				elif setting[1] == 'combo':
					store = Gtk.ListStore(str)
					for val in setting[2]: store.append([val])
					control = Gtk.ComboBox.new_with_model(store)
					control.set_active(setting[2].index(setting[3]))
					control.connect('changed', lambda self, *_, callbackfn=setting[4]: callbackfn(store[self.get_active()][0]))
				elif setting[1] == 'switch':
					control = Gtk.Switch()
					control.set_active(setting[3])
					control.connect('state-set', lambda self, *_, callbackfn=setting[4]: callbackfn(self.get_active()))
				elif setting[1] == 'checkbox':
					control = Gtk.CheckButton()
					control.set_active(setting[3])
					control.connect('toggled', lambda self, *_, callbackfn=setting[4]: callbackfn(self.get_active()))
				elif setting[1] == 'int':
					control = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=setting[3],
						lower=lower if (lower := setting[2][0]) is not None else -sys.maxsize - 1,
						upper=upper if (upper := setting[2][1]) is not None else sys.maxsize, step_increment=setting[2][2]))
					control.set_digits(len(str(setting[2][2]).split('.')[-1]))
					control.connect('value-changed', lambda self, *_, callbackfn=setting[4]: callbackfn(self.get_value()))
				container.attach(control, 1, i, 1, 1)
				if setting[5] is not None:
					help_tooltip = Gtk.Image.new_from_icon_name('help-faq', Gtk.IconSize.SMALL_TOOLBAR)
					help_tooltip.set_tooltip_text(setting[5])
					container.attach(help_tooltip, 2, i, 1, 1)
			return container
		def set_dark_mode(val):
			self.state['dark_mode'] = val
		def set_injections(val):
			self.state['injections'] = val
		def set_save_sidebar_widths(val):
			self.conf['ui']['save_sidebar_widths'] = val
			if val:  # force event handlers to be fired so that the previously ignored resizes are saved as the user would expect.
				# TODO: This is really hacky, but it works!
				parent.middle_pane.set_position(parent.middle_pane.get_position() + 1)
				parent.middle_pane.set_position(parent.middle_pane.get_position() - 1)
				parent.middle_pane_child.set_position(parent.middle_pane_child.get_position() + 1)
				parent.middle_pane_child.set_position(parent.middle_pane_child.get_position() - 1)

		ui_box = generate_settings_panel('General UI Settings',
			('Dark Mode', 'switch', None, self.state['dark_mode'], set_dark_mode, None),
			('CSS Injections', 'entry', None, self.state['injections'], set_injections,
				'Any extra CSS styles to be added to the stylesheet. If you don\'t know what this is, you can safely ignore it.'),
			('Save Sidebar Widths', 'switch', None, self.conf['ui']['save_sidebar_widths'], set_save_sidebar_widths,
				'Whether to save the widths of the sidebars in the main window between restarts'),
		)

		def set_normal_centering(val):
			self.conf['ui']['center_toolbar_items']['in_normal'] = val
			parent.update_toolbar_centering()
		def set_fullscreen_centering(val):
			self.conf['ui']['center_toolbar_items']['in_fullscreen'] = val
			parent.update_toolbar_centering()

		center_toolbar_items_box = generate_settings_panel('Whether to Center Toolbar Items',
			('In Normal Mode', 'checkbox', None, self.conf['ui']['center_toolbar_items']['in_normal'], set_normal_centering, None),
			('In Fullscreen', 'checkbox', None, self.conf['ui']['center_toolbar_items']['in_fullscreen'], set_fullscreen_centering, None),
		)

		def set_media_persistence(val):
			self.conf['behavior']['persist_media_on_sort_change'] = val

		behavior_box = generate_settings_panel('General Behavior Settings',
			('Persist Media on Sort Change', 'switch', None, self.conf['behavior']['persist_media_on_sort_change'], set_media_persistence,
			 'If true, change the media index to keep the shown media the same when the sort method is changed. If false, keep the index '
			 'the same, changing the media.'),
		)

		def set_save_history(val):
			self.conf['behavior']['history']['save_history'] = val
		def set_auto_resume(val):
			self.conf['behavior']['history']['auto_resume'] = val

		history_box = generate_settings_panel('History Settings',
			('Save History', 'switch', None, self.conf['behavior']['history']['save_history'], set_save_history, 'Save the history of opened TagSpaces in a Recently '
			 'Opened menu? Disabling this setting will stop the saving of these entries and will hide the Recently Opened menu, but will not purge the previous '
			 'history.'),
			('Automatically Reopen Previous TagSpace', 'switch', None, self.conf['behavior']['history']['auto_resume'], set_auto_resume, 'If a previous TagSpace is '
			 'saved, should it be opened automatically?'),
		)

		default_tags_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		panel_label = Gtk.Label(label='Default Tags')
		panel_label.set_halign(Gtk.Align.START)
		default_tags_box.add(panel_label)

		tags_model = Gtk.ListStore(str, str)
		for row in self.conf['behavior']['tagspace_defaults']['tags']: tags_model.append(row)
		tags_view = Gtk.TreeView(model=tags_model)
		tags_view.append_column(Gtk.TreeViewColumn(title='Name', cell_renderer=Gtk.CellRendererText(editable=True), text=0))
		color_renderer = Gtk.CellRendererText(editable=True)  # TODO: make this be a ColorButton
		tags_view.append_column(Gtk.TreeViewColumn(title='Color', cell_renderer=color_renderer, text=1))
		default_tags_box.add(tags_view)

		default_props_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		panel_label = Gtk.Label(label='Default Props')
		panel_label.set_halign(Gtk.Align.START)
		default_props_box.add(panel_label)

		prop_types_list = Gtk.ListStore(str)
		for prop_type in ['Text', 'True/False', 'Number']:
			prop_types_list.append([prop_type])
		props_model = Gtk.ListStore(str, str)  # int represents an enum of the possible types
		for row in self.conf['behavior']['tagspace_defaults']['props']: props_model.append(row)
		props_view = Gtk.TreeView(model=props_model)
		props_view.append_column(Gtk.TreeViewColumn(title='Name', cell_renderer=Gtk.CellRendererText(editable=True), text=0))
		type_input = Gtk.CellRendererCombo(editable=True, model=prop_types_list)
		type_input.set_property('text-column', 0)
		type_input.set_property('has-entry', False)
		def on_type_change(widget, path, val):
			props_model[path][1] = val
		type_input.connect('edited', on_type_change)
		props_view.append_column(Gtk.TreeViewColumn(title='Type', cell_renderer=type_input, text=1))
		default_props_box.add(props_view)

		def set_slideshow_interval(val):
			self.conf['behavior']['slideshow']['interval'] = round(val * 1000)
		def set_end_on_fs_exit(val):
			self.conf['behavior']['slideshow']['end_on_fs_exit'] = val
		def set_slideshow_stop_at_end(val):
			self.conf['behavior']['slideshow']['stop_at_end'] = val
		slideshow_box = generate_settings_panel('Slideshow Settings',
			('Interval', 'int', (0.01, None, 0.001), self.conf['behavior']['slideshow']['interval'] / 1000, set_slideshow_interval,
			 'How long to show each item in the slideshow, in seconds'),
			('End on Fullscreen Exit', 'switch', None, self.conf['behavior']['slideshow']['end_on_fullscreen_exit'], set_end_on_fs_exit,
			 'If a slideshow is playing and the application is in fullscreen, should the slideshow be stopped when you exit fullscreen?'),
			('Stop at End', 'switch', None, self.conf['behavior']['slideshow']['stop_at_end'], set_slideshow_stop_at_end,
			 'Should the slideshow be stopped when the last item is reached? If false, keep going, wrapping back around to the first item.'),
		)

		self.stack_pages = {
			'UI': ui_box,
			'Center Toolbar Items': center_toolbar_items_box,
			'Behavior': behavior_box,
			'History': history_box,
			'Tags': default_tags_box,
			'Props': default_props_box,
			'Slideshow': slideshow_box
		}

		self.content_stack = Gtk.Stack()

		for page in self.stack_pages:
			self.content_stack.add(self.stack_pages[page])

		def handle_cursor_changed(*_):
			selection = self.tree.get_selection().get_selected()
			self.content_stack.set_visible_child(self.stack_pages[selection[0].get_value(selection[1], 0)])
		self.tree.connect('cursor-changed', handle_cursor_changed)

		self.main.pack_end(self.content_stack, True, True, 0)

		self.base.pack_start(self.main, True, True, 0)

		self.open_toml = Gtk.Button(label='Open Config File')
		def open_config_handler(*_):
			conf_path = path.join(appdirs.user_config_dir('tagviewer'), 'config.toml')
			open_file(conf_path)
		self.open_toml.connect('clicked', open_config_handler)
		button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
		button_box.pack_start(self.open_toml, True, False, 0)
		self.base.pack_start(button_box, False, False, 5)

		self.base.show_all()


class NewTagSpaceWindow(Gtk.Assistant):
	def __init__(self, parent, conf, state):
		Gtk.Assistant.__init__(self)
		self.conf = conf
		self.state = state

		basic_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		title_input_label = Gtk.Label(label='Title*')
		title_input_label.set_tooltip_text("Please fill out this field.")
		basic_info_box.add(title_input_label)
		title_input = Gtk.Entry()
		basic_info_box.add(title_input)
		basic_info_box.add(Gtk.Label(label='Description'))
		desc_input = Gtk.Entry()
		basic_info_box.add(desc_input)

		basic_info_page = self.get_nth_page(self.append_page(basic_info_box))
		self.set_page_title(basic_info_page, "Basic Information")
		self.set_page_type(basic_info_page, Gtk.AssistantPageType.CONTENT)
		def basic_info_set_complete(the_input, *_):
			self.set_page_complete(basic_info_page, len(the_input.get_text()) > 0)
		title_input.connect('changed', basic_info_set_complete)

		tags_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		tags_model = Gtk.ListStore(str, str)
		for row in self.conf['behavior']['tagspace_defaults']['tags']: tags_model.append(row)
		tags_view = Gtk.TreeView(model=tags_model)
		tags_view.append_column(Gtk.TreeViewColumn(title='Name', cell_renderer=Gtk.CellRendererText(editable=True), text=0))
		color_renderer = Gtk.CellRendererText(editable=True)  # TODO: make this be a ColorButton
		tags_view.append_column(Gtk.TreeViewColumn(title='Color', cell_renderer=color_renderer, text=1))
		tags_box.add(tags_view)
		tags_page = self.get_nth_page(self.append_page(tags_box))
		self.set_page_title(tags_page, "Tags")
		self.set_page_type(tags_page, Gtk.AssistantPageType.CONTENT)
		self.set_page_complete(tags_page, True)

		props_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		prop_types_list = Gtk.ListStore(str)
		for prop_type in ['Text', 'True/False', 'Number']:
			prop_types_list.append([prop_type])
		props_model = Gtk.ListStore(str, str)  # int represents an enum of the possible types
		for row in self.conf['behavior']['tagspace_defaults']['props']: props_model.append(row)
		props_view = Gtk.TreeView(model=props_model)
		props_view.append_column(Gtk.TreeViewColumn(title='Name', cell_renderer=Gtk.CellRendererText(editable=True), text=0))
		type_input = Gtk.CellRendererCombo(editable=True, model=prop_types_list)
		type_input.set_property('text-column', 0)
		type_input.set_property('has-entry', False)
		def on_type_change(widget, path, val):
			props_model[path][1] = val
		type_input.connect('edited', on_type_change)
		props_view.append_column(Gtk.TreeViewColumn(title='Type', cell_renderer=type_input, text=1))
		props_box.add(props_view)

		props_page = self.get_nth_page(self.append_page(props_box))
		self.set_page_title(props_page, "Props")
		self.set_page_type(props_page, Gtk.AssistantPageType.CONTENT)
		self.set_page_complete(props_page, True)

		final_page = self.get_nth_page(self.append_page(Gtk.Label(label="The TagSpace is ready to be created.")))
		self.set_page_title(final_page, "End")
		self.set_page_type(final_page, Gtk.AssistantPageType.CONFIRM)
		self.set_page_complete(final_page, True)

		self.connect('close', lambda self, *_: self.destroy())
		self.connect('cancel', lambda self, *_: self.destroy())
		def finish_handler(self, *_):
			parent._create_tagspace({
				'title': title_input.get_text(),
				'desc': desc_input.get_text(),
				'tags': convert_list_store_to_list(tags_model),
				'props': convert_list_store_to_list(props_model),
			})
			self.close()
		self.connect('apply', finish_handler)
		self.show_all()


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
		try:
			css_provider_2.load_from_data(self.config['ui']['injections'].encode())
		except GLib.Error as e:
			if e.domain == 'gtk-css-provider-error-quark':  # Error parsing injections
				msg = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, text="The CSS injections could not be parsed.", buttons=Gtk.ButtonsType.OK_CANCEL)
				msg.format_secondary_text("If you choose OK, the injections will not be applied. "
				"Alternatively, you can exit to edit the injections by selecting Cancel.")
				response = msg.run()
				msg.hide()
				if response == Gtk.ResponseType.CANCEL:
					exit(0)
			else:
				raise  # other `GLib.Error`s should be treated normally
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
			'media_is_open': (lambda model: model['tagspace_is_open'] and ('_path' in model['current_item']
			                  or model['filters_active'] or len(model['files']) == 0),
			                  ('tagspace_is_open', 'current_item', 'filters_active', 'files')),
			'can_go_previous': (lambda model: model['media_number'] > 1, ('media_number',)),
			'can_go_next': (lambda model: len(model['files']) > 0 and len(model['files']) > model['media_number'], ('files', 'media_number')),
			# ↓ deps doesn't include `files` intentionally!
			'current_item': (lambda model: model['files'][model['media_number']] if model['media_number'] in files else {}, ('media_number',)),
			'current_path': (lambda model: model['current_item']['_path'] if model['media_is_open'] else None, ('current_item', 'media_is_open')),
			'current_tags': (lambda model: list(map(lambda x: model['tagviewer_meta']['tagList'][x], model['current_item']['tags']))
			                 if 'tagList' in model['tagviewer_meta'] else [],
			                 ('current_item', 'tagviewer_meta'))
		}, refs={'win': self, 'conf': self.config, 'cache': self.cache, 'settings': Gtk.Settings.get_default(), 'injections_provider': css_provider_2})

		def handle_fullscreen_change(model, _):
			if model['is_fullscreen']:
				model.refs['win'].top_bar_items['fullscreen_toggle_button'].get_icon_widget()\
				    .set_from_file(f'icons/{("dark" if model["dark_mode"] else "light")}/fullscreen_exit.svg')
				model.refs['win'].fullscreen()
				model.refs['win'].update_toolbar_centering()
				pass  # TODO: enable autohide for widgets
			else:
				model.refs['win'].top_bar_items['fullscreen_toggle_button'].get_icon_widget()\
				    .set_from_file(f'icons/{("dark" if model["dark_mode"] else "light")}/fullscreen.svg')
				model.refs['win'].unfullscreen()
				model.refs['win'].update_toolbar_centering()
				pass  # TODO: disable autohide for widgets
				if model['slideshow_active'] and model.refs['conf']['behavior']['slideshow']['end_on_fullscreen_exit']:
					model['slideshow_active'] = False
		self.state.bind('is_fullscreen', handle_fullscreen_change)

		def handle_dark_mode_change(model, _):
			model.refs['settings'].set_property('gtk-application-prefer-dark-theme', model['dark_mode'])
			model.refs['conf']['ui']['dark'] = model['dark_mode']

		self.state.bind('dark_mode', handle_dark_mode_change)

		def handle_injections_change(model, _):
			try:
				model.refs['injections_provider'].load_from_data(model['injections'].encode())
			except GLib.Error:
				pass  # the injections CSS is invalid. Fail silently.
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
					item.get_icon_widget().set_from_file(f'icons/'
					f'{"dark" if model["dark_mode"] else "light"}/'
					f'{"fullscreen_exit" if model["is_fullscreen"] else "fullscreen"}.svg')
				else:
					item.get_icon_widget().set_from_file(f'icons/'
					f'{"dark" if model["dark_mode"] else "light"}/{item.icon_name}.svg')
		self.state.bind('dark_mode', invert_icon_colors)

		def toggle_fullscreen():
			self.state['is_fullscreen'] = not self.state['is_fullscreen']
		self.top_bar_items['fullscreen_toggle_button'].connect('clicked', lambda widget: toggle_fullscreen())

		def toggle_dark_mode():
			self.state['dark_mode'] = not self.state['dark_mode']
		self.top_bar_items['dark_mode_toggle_button'].connect('clicked', lambda widget: toggle_dark_mode())

		self.top_bar_items['new_tagspace_button'].connect('clicked', lambda widget: self.new_tagspace())

		self.about_dialog = Gtk.AboutDialog()
		self.about_dialog.set_program_name('TagViewer 2')
		self.about_dialog.set_version(VERSION)
		self.about_dialog.set_copyright('Copyright (C) 2020  Matt Fellenz, under the GPL 3.0')
		self.about_dialog.set_comments('A simple program that allows viewing of media within a TagSpace, '
		'and rich filtering of that media with tags and properties that are stored by the program.')
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
			settings_dialog.destroy()

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

		if self.config['ui']['save_sidebar_widths']:
			self.middle_pane.set_position(self.cache['sidebar_widths'][0])
			self.middle_pane_child.set_position(1000 - self.cache['sidebar_widths'][0] - self.cache['sidebar_widths'][1])
		else:
			self.middle_pane.set_position(200)
			self.middle_pane_child.set_position(600)

		@debounce(0.2)
		def file_list_resize(middle_pane: Gtk.Paned, *_):
			if self.config['ui']['save_sidebar_widths']:
				self.cache['sidebar_widths'][0] = middle_pane.get_position()
			return True
		self.middle_pane.connect('notify::position', file_list_resize)

		@debounce(0.2)
		def aside_resize(middle_pane_child: Gtk.Paned, *_):
			if self.config['ui']['save_sidebar_widths']:
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

	def update_toolbar_centering(self):
		self.top_bar_items['left_expander'].set_expand(
			self.config['ui']['center_toolbar_items']['in_fullscreen' if self.state['is_fullscreen'] else 'in_normal']
		)

	def new_tagspace(self):
		win = NewTagSpaceWindow(self, self.config, self.state)

	def _create_tagspace(self, data):
		pass  # TODO: Actually make the TagSpace

	def exit_handler(self, *_):
		with open(path.join(appdirs.user_config_dir('tagviewer'), 'config.toml'), 'w') as config_file:
			toml.dump(self.config, config_file)
		with open(path.join(appdirs.user_cache_dir('tagviewer'), 'cache.json'), 'w') as cache_file:
			json.dump(self.cache, cache_file)

		Gtk.main_quit()


def graphical_except_hook(exctype, value, tb):
	if exctype != KeyboardInterrupt:
		msg = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, text='An error was encountered and TagViewer will now exit.')
		msg.format_secondary_text(f'The error is as follows:\n\n    {exctype.__name__}: {str(value)}\n\nThe full exception was printed to STDERR.')
		msg.run()
		msg.hide()
		traceback.print_exception(exctype, value, tb)
	try:
		win.exit_handler()
	except NameError:
		pass
	exit(1)
sys.excepthook = graphical_except_hook

win = MainWindow()
win.connect("destroy", win.exit_handler)
win.show_all()
Gtk.main()
