# coding: utf-8

import times
import datetime
import mock
import thebot
import six

from thebot import Request, Adapter, Plugin, Storage, route
from thebot.batteries import todo
from nose.tools import eq_, assert_raises


class Bot(thebot.Bot):
    """Test bot which uses slightly different settings."""
    def __init__(self, *args, **kwargs):
        kwargs['config_dict'] = dict(
            unittest=True,
            log_filename='unittest.log',
            storage_filename='unittest.storage',
        )
        super(Bot, self).__init__(*args, **kwargs)

        self.storage.clear()


class TestRequest(Request):
    def __init__(self, message, bot, user):
        super(TestRequest, self).__init__(message)
        self.bot = bot
        self.user = user

    def respond(self, message):
        adapter = self.bot.get_adapter('test')
        adapter._lines.append(message)

    def get_user(self):
        return self.user


class TestAdapter(Adapter):
    name = 'test'

    def __init__(self, *args, **kwargs):
        super(TestAdapter, self).__init__(*args, **kwargs)
        self._lines = []

    def write(self, input_line, user='some user'):
        """This method is for test purpose.
        """
        lines = self._lines
        self.callback(TestRequest(input_line, self.bot, user))


class TestPlugin(Plugin):
    @route('show me a cat')
    def show_a_cat(self, request):
        """Shows a cat."""
        request.respond('the Cat')

    @route('find (?P<this>.*)')
    def find(self, request, this=None):
        """Making a fake search of the term."""
        request.respond('I found {0}'.format(this))


def test_install_adapters():
    bot = Bot(adapters=[TestAdapter], plugins=[])
    assert len(bot.adapters) == 1


def test_install_plugins():
    bot = Bot(adapters=[], plugins=[TestPlugin])
    eq_(0, len(bot.adapters))
    eq_(2, len(bot.plugins)) # Help plugin is added by default
    eq_(3, len(bot.patterns))


def test_one_line():
    bot = Bot(adapters=[TestAdapter], plugins=[TestPlugin])
    adapter = bot.get_adapter('test')

    eq_(adapter._lines, [])
    adapter.write('show me a cat')
    eq_(adapter._lines, ['the Cat'])

    adapter.write('find Umputun')
    eq_(adapter._lines[-1], 'I found Umputun')


def test_unknown_command():
    bot = Bot(adapters=[TestAdapter], plugins=[TestPlugin])
    adapter = bot.adapters[0]

    eq_(adapter._lines, [])
    adapter.write('some command')
    eq_(adapter._lines, ['I don\'t know command "some command".'])


def test_exception_raised_if_plugin_returns_not_none():
    class BadPlugin(Plugin):
        @route('^do$')
        def do(self, request):
            return 'Hello world'


    bot = Bot(adapters=[TestAdapter], plugins=[BadPlugin])
    adapter = bot.adapters[0]

    assert_raises(RuntimeError, adapter.write, 'do')


def test_simple_storage():
    storage = Storage('/tmp/thebot.storage')
    storage.clear()

    eq_([], storage.keys())

    storage['blah'] = 'minor'
    storage['one'] = {'some': 'dict'}

    eq_(['blah', 'one'], sorted(storage.keys()))
    eq_('minor', storage['blah'])


def test_storage_nesting():
    storage = Storage('/tmp/thebot.storage')
    storage.clear()

    first = storage.with_prefix('first:')
    second = storage.with_prefix('second:')

    eq_([], storage.keys())

    first['blah'] = 'minor'
    second['one'] = {'some': 'dict'}

    eq_(['first:blah', 'second:one'], sorted(storage.keys()))
    eq_(['first:blah'], sorted(first.keys()))
    eq_(['second:one'], sorted(second.keys()))

    eq_('minor', first['blah'])
    assert_raises(KeyError, lambda: second['blah'])

    first.clear()
    eq_(['second:one'], sorted(storage.keys()))


def test_help_command():
    bot = Bot(adapters=[TestAdapter], plugins=[TestPlugin])
    adapter = bot.adapters[0]

    adapter.write('help')
    eq_(
        [
            six.u('I support following commands:\n'
                  '  find (?P<this>.*) — Making a fake search of the term.\n'
                  '  help — Shows a help.\n'
                  '  show me a cat — Shows a cat.'
            )
        ],
        adapter._lines
    )


def test_delete_from_storage():
    storage = Storage('/tmp/thebot.storage')
    storage.clear()

    storage['blah'] = 'minor'
    del storage['blah']

    eq_([], sorted(storage.keys()))



def test_storage_restores_bot_attribute():
    bot = Bot(adapters=[TestAdapter], plugins=[TestPlugin])

    storage = Storage('/tmp/thebot.storage', global_objects=dict(bot=bot))
    storage.clear()

    original = Request('blah')
    original.bot = bot

    storage['request'] = original

    restored = storage['request']
    eq_(restored.bot, original.bot)


def test_storage_with_prefix_keeps_global_objects():
    storage = Storage('/tmp/thebot.storage', global_objects=dict(some='value'))
    prefixed = storage.with_prefix('nested:')

    eq_(storage.global_objects, prefixed.global_objects)


def test_get_adapter_by_name():
    bot = Bot(adapters=[TestAdapter])
    adapter = bot.get_adapter('test')
    assert isinstance(adapter, TestAdapter)


def test_todo_plugin():
    bot = Bot(adapters=[TestAdapter], plugins=[todo.Plugin])
    adapter = bot.get_adapter('test')

    adapter.write('remind at 2012-10-05 to Celebrate my birthday')
    adapter.write('remind at 2012-12-18 to Celebrate daughter\'s birthday')
    adapter.write('remind at 2012-09-01 to Write a doc for TheBot')
    adapter.write('my tasks')

    eq_(
        [
            'ok',
            'ok',
            'ok',
            '16) 2012-09-01 00:00 Write a doc for TheBot\n'
            'cd) 2012-10-05 00:00 Celebrate my birthday\n'
            '9c) 2012-12-18 00:00 Celebrate daughter\'s birthday',
        ],
        adapter._lines
    )


def test_todo_plugin_for_different_users():
    bot = Bot(adapters=[TestAdapter], plugins=[todo.Plugin])
    adapter = bot.get_adapter('test')

    adapter.write('remind at 2012-10-05 to Celebrate my birthday', user='blah')
    adapter.write('remind at 2012-12-18 to Celebrate daughter\'s birthday', user='minor')

    adapter._lines[:] = []
    adapter.write('my tasks', user='minor')

    eq_(
        [
            '9c) 2012-12-18 00:00 Celebrate daughter\'s birthday',
        ],
        adapter._lines
    )


def test_todo_remind():
    bot = Bot(adapters=[TestAdapter], plugins=[todo.Plugin])
    adapter = bot.get_adapter('test')
    plugin = bot.get_plugin('todo')


    adapter.write('set my timezone to Asia/Shanghai')
    # these are the local times
    adapter.write('remind at 2012-09-05 10:00 to do task1')
    adapter.write('remind at 2012-09-05 10:30 to do task2')

    with mock.patch.object(times, 'now') as now:
        # this is a server time in UTC
        # it is 10:01 at Shanghai (+8 hours)
        now.return_value = datetime.datetime(2012, 9, 5, 2, 1)

        adapter._lines[:] = []
        plugin._remind_users_about_their_tasks()

        eq_(['TODO: do task1 (03f9)'], adapter._lines)

        # but it does not reminds twice
        now.return_value = datetime.datetime(2012, 9, 5, 2, 12)

        adapter._lines[:] = []
        plugin._remind_users_about_their_tasks()
        eq_([], adapter._lines)


def test_todo_done():
    bot = Bot(adapters=[TestAdapter], plugins=[todo.Plugin])

    adapter = bot.get_adapter('test')
    plugin = bot.get_plugin('todo')


    adapter.write('set my timezone to Asia/Shanghai')
    adapter.write('remind at 2012-09-05 10:00 to do task1')
    adapter.write('remind at 2012-09-05 10:30 to do task2')
    adapter.write('03 done')

    adapter._lines[:] = []
    adapter.write('my tasks')

    eq_(
        [
            '26) 2012-09-05 10:30 do task2',
        ],
       adapter._lines
    )


def test_todo_remind_at_uses_timezones():
    bot = Bot(adapters=[TestAdapter], plugins=[todo.Plugin])
    adapter = bot.get_adapter('test')
    plugin = bot.get_plugin('todo')


    with mock.patch.object(times, 'now') as now:
        adapter.write('set my timezone to Asia/Shanghai')
        adapter.write('remind at 2012-09-05 00:00 to do task1')
        tasks = plugin._get_tasks('some user')
        eq_(datetime.datetime(2012, 9, 4, 16, 0), tasks[0][0])

