# coding: utf-8

import argparse
import importlib
import logging
import re
import shelve
import threading
import time

__version__ = '0.1.0'

# pass this object to callback, to terminate the bot
EXIT = object()


class Request(object):
    def __init__(self, message):
        self.message = message

    def respond(self, message):
        raise NotImplementedError('You have to implement \'respond\' method in you Request class.')


class Adapter(object):
    def __init__(self, bot, callback):
        self.bot = bot
        self.callback = callback

    def start(self):
        """You have to override this method, if you plugin requires some background activity.

        Here you can create a thread, but don't forget to make its `daemon` attrubute equal to True.
        """


class Plugin(object):
    def __init__(self, bot):
        self.bot = bot
        self.storage = self.bot.storage.with_prefix(self.__module__)

    def get_callbacks(self):
        for name in dir(self):
            value = getattr(self, name)
            if callable(value):
                patterns = getattr(value, '_patterns', [])
                for pattern in patterns:
                    yield (pattern, value)


class ThreadedPlugin(Plugin):
    """ThreadedPlugin allows you to do some processing in a background thread.

    This class will take care on proper thread execution and termination.

    * First, implement method `do_job`, which will be executed with given interval.
    * Then run method `self.start_worker(interval=60)` to run a thread.
      It will call your do_job callback each 60 seconds.
    * To stop job execution, call `self.stop_worker()`.

    See `thebot-instagram`, as an example.
    """
    def do_job(self):
        raise NotImplemented('Implement "do_job" method to get real work done.')


    def start_worker(self, interval=60):
        thread = getattr(self, '_thread', None)
        if thread is not None and thread.is_alive():
            return

        self._event = threading.Event()
        self._thread = threading.Thread(target=self._worker, kwargs=dict(interval=interval))
        self._thread.daemon = True
        self._thread.start()

    def stop_worker(self):
        event = getattr(self, '_event', None)
        if event is not None:
            event.set()

    def _worker(self, interval=60):
        countdown = 0
        logger = logging.getLogger('thebot.' + self.__class__.__name__)

        on_start = getattr(self, 'on_start', None)
        if on_start is not None:
            on_start()

        while not self._event.is_set():
            if countdown == 0:
                try:
                    self.do_job()
                except Exception:
                    logger.exception('Error during the task execution')

                countdown = interval
            else:
                countdown -= 1

            time.sleep(1)

        on_stop = getattr(self, 'on_stop', None)
        if on_stop is not None:
            on_stop()


def route(pattern):
    """Decorator to assign routes to plugin's methods.
    """
    def deco(func):
        if getattr(func, '_patterns', None) is None:
            func._patterns = []
        func._patterns.append(pattern)
        return func
    return deco


class HelpPlugin(Plugin):
    @route('help')
    def help(self, request):
        """Shows a help."""
        lines = []
        for pattern, callback in self.bot.patterns:
            docstring = callback.__doc__
            if docstring:
                lines.append('  ' + pattern + ' — ' + docstring)
            else:
                lines.append('  ' + pattern)

        lines.sort()
        lines.insert(0, 'I support following commands:')

        request.respond('\n'.join(lines))



class Storage(object):
    def __init__(self, filename, prefix=''):
        if isinstance(filename, basestring):
            self._shelve = shelve.open(filename)
        else:
            self._shelve = filename

        self.prefix = prefix

    def __getitem__(self, name):
        return self._shelve.__getitem__(self.prefix + name)

    def get(self, name):
        return self._shelve.get(self.prefix + name)

    def __setitem__(self, name, value):
        return self._shelve.__setitem__(self.prefix + name, value)

    def keys(self):
        return filter(lambda x: x.startswith(self.prefix), self._shelve.keys())

    def clear(self):
        for key in self.keys():
            del self._shelve[key]

    def with_prefix(self, prefix):
        return Storage(self._shelve, prefix=prefix)

    def close(self):
        self._shelve.close()


class Bot(object):
    def __init__(self, command_line_args=[], adapters=None, plugins=None):
        self.adapters = []
        self.plugins = []
        self.patterns = []
        self.exiting = False

        def load(value, cls='Adapter'):
            """Returns class by it's name.

            Given a 'irc' string it will try to load the following:

            1) from thebot_irc import Adapter
            2) from thebot.batteries.irc import Adapter

            If all of them fail, it will raise ImportError
            """
            if isinstance(value, basestring):
                try:
                    module = importlib.import_module('thebot_' + value)
                except ImportError:
                    module = importlib.import_module('thebot.batteries.' + value)

                return getattr(module, cls)
            return value

        parser = Bot.get_general_options()
        args, unknown = parser.parse_known_args(filter(lambda x: x not in ('--help', '-h'), command_line_args))

        if adapters is None:
            adapter_classes = map(lambda a: load(a, 'Adapter'), args.adapters.split(','))
        else:
            # we've got adapters argument (it is used for testing purpose
            adapter_classes = adapters

        if plugins is None:
            plugin_classes = map(lambda a: load(a, 'Plugin'), args.plugins.split(','))
        else:
            # we've got adapters argument (it is used for testing purpose
            plugin_classes = plugins

        plugin_classes.append(HelpPlugin)

        for cls in adapter_classes + plugin_classes:
            if hasattr(cls, 'get_options'):
                cls.get_options(parser)

        self.config = parser.parse_args(command_line_args)

        self.storage = Storage(self.config.storage_filename)

        logging.basicConfig(
            filename=self.config.log_filename,
            format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
            level=logging.DEBUG if self.config.verbose else logging.WARNING,
        )

        # adapters and plugins initialization

        for adapter in adapter_classes:
            a = adapter(self, callback=self.on_request)
            a.start()
            self.adapters.append(a)

        for plugin_cls in plugin_classes:
            p = plugin_cls(self)
            self.plugins.append(p)
            self.patterns.extend(p.get_callbacks())

    @staticmethod
    def get_general_options():
        parser = argparse.ArgumentParser(
            description='The Bot — Hubot\'s killer.'
        )
        parser.add_argument(
            '--verbose', '-v', action='store_true', default=False,
            help='Show more output.'
        )
        parser.add_argument(
            '--log-filename', default='thebot.log',
            help='Log\'s filename. Default: thebot.log.'
        )
        parser.add_argument(
            '--storage-filename', default='thebot.storage',
            help='Path to a database file, used for TheBot\'s memory.'
        )

        group = parser.add_argument_group('General options')
        group.add_argument(
            '--adapters', '-a', default='console',
            help='Adapters to use. You can specify a comma-separated list to use more than one adapter. Default: console.',
        )
        group.add_argument(
            '--plugins', '-p', default='image',
            help='Plugins to use. You can specify a comma-separated list to use more than one plugin. Default: image.',
        )
        return parser

    def on_request(self, request):
        if request is EXIT:
            self.exiting = True
        else:
            for pattern, callback in self.patterns:
                match = re.match(pattern, request.message)
                if match is not None:
                    result = callback(request, **match.groupdict())
                    if result is not None:
                        raise RuntimeError('Plugin {0} should not return response directly. Use request.respond(some message).')
                    break
            else:
                request.respond('I don\'t know command "{0}".'.format(request.message))

    def close(self):
        """Will close all connections here.
        """
        self.storage.close()

