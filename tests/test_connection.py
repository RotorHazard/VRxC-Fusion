"""Connection lifecycle tests using real greenlets and simulated serial hardware.

Run with: python -m pytest tests (requires pytest, gevent and pyserial).
"""

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import gevent
from gevent.event import Event
import pytest


PORT = '/dev/serial/by-path/platform-3f980000.usb-usb-0:1.1.2:1.0-port0'


@pytest.fixture(scope='module')
def plugin():
    class Controller:
        def __init__(self, *args):
            self.ready = True  # Match RotorHazard's default setup().

    @dataclass
    class Field:
        name: str
        label: str
        field_type: str
        value: object = None
        desc: str = None
        persistent_section: str = None

    with pytest.MonkeyPatch.context() as patch:
        modules = {
            'RHRace': SimpleNamespace(WinCondition=Mock()),
            'RHUtils': Mock(),
            'Results': Mock(),
            'eventmanager': SimpleNamespace(Evt=SimpleNamespace(VRX_INITIALIZE='vrx')),
            'RHUI': SimpleNamespace(UIField=Field, UIFieldType=SimpleNamespace(TEXT='text')),
            'VRxControl': SimpleNamespace(VRxController=Controller, VRxDevice=object,
                                         VRxDeviceMethod=object),
        }
        for name, module in modules.items():
            patch.setitem(sys.modules, name, module)
        path = Path(__file__).parents[1] / 'custom_plugins/vrx_tbs/__init__.py'
        spec = importlib.util.spec_from_file_location('fusion_test_plugin', path)
        module = importlib.util.module_from_spec(spec)
        patch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        yield module


@pytest.fixture
def env(plugin, monkeypatch):
    api = Mock()
    api.__ = lambda message: message
    api.config.get.return_value = PORT
    api.db.option.return_value = ''
    serial = Mock()
    serial.is_open = False
    opened = []

    def open_port():
        opened.append(serial.port)
        serial.is_open = True

    def close_port():
        serial.is_open = False

    def write(data):
        if not serial.is_open:
            raise plugin.serial.SerialException('closed')
        return len(data)

    serial.open.side_effect = open_port
    serial.close.side_effect = close_port
    serial.write.side_effect = write
    serial.read.return_value = b'Fusion ESP'
    monkeypatch.setattr(plugin.serial, 'Serial', Mock(return_value=serial))
    scan = Mock(return_value=[])
    monkeypatch.setattr(plugin.serial.tools.list_ports, 'comports', scan)
    monkeypatch.setattr(plugin, 'DEVICE_STARTUP_DELAY', 0)
    monkeypatch.setattr(plugin, 'RETRY_DELAY', 0)
    controller = plugin.FusionController(api, 'tbs', 'TBS')
    yield SimpleNamespace(plugin=plugin, api=api, serial=serial, controller=controller,
                          scan=scan, opened=opened)
    controller.onShutdown({})


def connect(env, manual=False):
    worker = env.controller.discoverPort({'manual': manual})
    worker.get(timeout=1)
    assert not env.controller._discovering
    return env.controller.ready


@pytest.mark.parametrize('manual', [False, True])
def test_ready_only_after_verified_identity_and_notifies(env, manual):
    assert not env.controller.ready
    worker = env.controller.discoverPort({'manual': manual})
    assert not env.controller.ready
    worker.get(timeout=1)
    assert env.controller.ready
    assert env.serial.is_open
    assert env.opened == [PORT]
    env.scan.assert_not_called()
    assert env.serial.baudrate == 921600
    assert env.serial.timeout == env.serial.write_timeout == 1
    env.serial.write.assert_called_once_with(b'\x00\x01\x01\xff')
    env.api.ui.message_notify.assert_called_once_with('Fusion connected at ' + PORT)


@pytest.mark.parametrize('response', [b'', b'Fusion ES', b'ELRS', b'\xff' * 10])
def test_invalid_response_exhausts_retries_closes_and_notifies_once(env, response):
    env.serial.read.return_value = response
    assert not connect(env)
    assert env.opened == [PORT] * 5
    assert not env.serial.is_open
    env.scan.assert_not_called()
    env.api.ui.message_notify.assert_called_once()
    assert 'Failed to connect' in env.api.ui.message_notify.call_args.args[0]


def test_missing_port_never_scans_other_devices(env):
    env.serial.open.side_effect = env.plugin.serial.SerialException('missing')
    assert not connect(env)
    assert env.serial.open.call_count == 5
    assert not env.serial.is_open
    env.scan.assert_not_called()
    env.api.ui.message_notify.assert_called_once()


def test_late_device_connects_on_later_attempt(env):
    original_open = env.serial.open.side_effect
    attempts = []

    def late_open():
        attempts.append(1)
        if len(attempts) < 3:
            raise env.plugin.serial.SerialException('not enumerated yet')
        original_open()

    env.serial.open.side_effect = late_open
    assert connect(env)
    assert len(attempts) == 3
    env.api.ui.message_notify.assert_called_once_with('Fusion connected at ' + PORT)


def test_slow_firmware_can_answer_a_later_probe(env):
    env.serial.read.side_effect = [b'', b'Fusion ESP']
    assert connect(env)
    assert len(env.opened) == 2
    env.api.ui.message_notify.assert_called_once()


@pytest.mark.parametrize('stage', ['reset_input_buffer', 'write', 'read'])
def test_identification_io_errors_are_bounded_and_close_port(env, stage):
    getattr(env.serial, stage).side_effect = env.plugin.serial.SerialException('unplugged')
    assert not connect(env)
    assert env.serial.open.call_count == 5
    assert not env.serial.is_open
    env.api.ui.message_notify.assert_called_once()


def test_short_identification_write_is_not_ready(env):
    env.serial.write.side_effect = lambda data: len(data) - 1
    assert not connect(env)
    env.serial.read.assert_not_called()
    assert not env.serial.is_open


@pytest.mark.parametrize('path', ['', '   '])
def test_empty_path_scans_once_skips_reserved_ports_and_finds_fusion(env, path):
    env.api.config.get.return_value = path
    env.scan.return_value = [SimpleNamespace(device=p) for p in
                             ['COM1', '/dev/ttyAMA0', '/dev/ttyAMA10',
                              '/dev/ttyUSB0', '/dev/ttyUSB1']]
    env.serial.read.side_effect = [b'ELRS', b'Fusion ESP']
    assert connect(env)
    env.scan.assert_called_once()
    assert env.opened == ['/dev/ttyUSB0', '/dev/ttyUSB1']


def test_no_devices_finishes_without_retrying_or_stale_ready(env):
    env.api.config.get.return_value = ''
    assert not connect(env)
    env.scan.assert_called_once()
    env.serial.open.assert_not_called()
    env.api.ui.message_notify.assert_called_once()


def test_scan_failure_releases_guard_for_next_attempt(env):
    env.api.config.get.return_value = ''
    env.scan.side_effect = OSError('enumeration failed')
    assert not connect(env)
    assert not env.serial.is_open
    env.api.ui.message_notify.assert_called_once()
    env.api.config.get.return_value = PORT
    assert connect(env, manual=True)


def test_startup_is_background_and_overlapping_requests_share_one_worker(env):
    release = Event()
    env.serial.read.side_effect = lambda size: (release.wait(), b'Fusion ESP')[1]
    env.controller.onStartup({})
    worker = env.controller._discovery
    assert worker is not None
    assert env.controller.discoverPort({'manual': True}) is worker
    gevent.sleep(0)
    assert not env.controller.ready
    assert env.controller.discoverPort({'manual': True}) is worker
    assert env.serial.open.call_count == 1
    release.set()
    worker.get(timeout=1)
    assert env.controller.ready


def test_send_failure_clears_ready_and_notifies_once_until_reconnected(env):
    assert connect(env)
    env.api.ui.message_notify.reset_mock()
    env.serial.write.side_effect = env.plugin.serial.SerialException('USB removed')
    message = env.plugin.OSDData(1, 2, 'one', 'two', 'three')
    env.controller.sendLapMessage(1234, message)
    assert not env.controller.ready
    assert not env.serial.is_open
    writes = env.serial.write.call_count
    env.controller.sendLapMessage(1234, message)
    assert env.serial.write.call_count == writes
    env.api.ui.message_notify.assert_called_once()
    assert 'connection lost' in env.api.ui.message_notify.call_args.args[0]
    env.serial.write.side_effect = len
    assert connect(env, manual=True)


def test_short_osd_write_clears_ready(env):
    assert connect(env)
    env.serial.write.side_effect = lambda data: len(data) - 1
    env.controller.sendLapMessage(1234, env.plugin.OSDData(1, 2, '', '', ''))
    assert not env.controller.ready
    assert not env.serial.is_open


def test_no_osd_writes_during_discovery(env):
    worker = env.controller.discoverPort()
    env.controller.sendLapMessage(1234, env.plugin.OSDData(1, 2, '', '', ''))
    env.serial.write.assert_not_called()
    worker.get(timeout=1)


@pytest.mark.parametrize('started', [False, True])
def test_shutdown_cancels_discovery_and_closes_port(env, started):
    release = Event()
    env.serial.read.side_effect = lambda size: release.wait()
    worker = env.controller.discoverPort()
    if started:
        gevent.sleep(0)
    env.controller.onShutdown({})
    assert worker.dead
    assert not env.controller.ready
    assert not env.serial.is_open
    assert not env.controller._discovering
    assert env.controller.discoverPort() is None
    env.api.ui.message_notify.assert_not_called()


@pytest.mark.parametrize('persistent', [PORT, ''])
def test_persistent_config_wins_over_old_db_value(env, persistent):
    env.api.config.get.return_value = persistent
    env.api.db.option.return_value = '/dev/old-port'
    assert env.controller._configured_port() == persistent


@pytest.mark.parametrize('missing', [None, False])
def test_missing_config_falls_back_to_legacy_db(env, missing):
    env.api.config.get.return_value = missing
    env.api.db.option.return_value = '  ' + PORT + '  '
    assert env.controller._configured_port() == PORT


def test_field_preserves_persistent_storage_and_seeds_legacy_value(env):
    env.api.db.option.return_value = PORT
    env.plugin.initialize(env.api)
    env.api.config.register_section.assert_called_once_with('VRX_TBS')
    field, panel = env.api.fields.register_option.call_args.args
    assert field.persistent_section == 'VRX_TBS'
    assert field.value == PORT
    assert panel == 'vrx_tbs'


def test_older_host_keeps_database_storage(env, monkeypatch):
    @dataclass
    class LegacyField:
        name: str
        label: str
        field_type: str
        value: object = None
        desc: str = None

    monkeypatch.setattr(env.plugin, 'UIField', LegacyField)
    env.api.db.option.return_value = PORT
    env.plugin.initialize(env.api)
    field, panel = env.api.fields.register_option.call_args.args
    assert not hasattr(field, 'persistent_section')
    assert env.controller._configured_port() == PORT
    env.api.config.get.assert_not_called()
    env.api.config.register_section.assert_not_called()
