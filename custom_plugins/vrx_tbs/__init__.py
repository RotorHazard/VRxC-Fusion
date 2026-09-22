
import logging
import gevent
from gevent.lock import Semaphore
import serial
import serial.tools.list_ports
from struct import pack
from RHRace import WinCondition
import RHUtils
import Results
from eventmanager import Evt
from RHUI import UIField, UIFieldType
from VRxControl import VRxController, VRxDevice, VRxDeviceMethod

logger = logging.getLogger(__name__)

MAC_ADDR_OPT_NAME = 'comm_tbs_mac'
PORT_CONFIG_SECTION = 'VRX_TBS'
PORT_OPTION = 'tbs_comms_port'
CONNECT_ATTEMPTS = 5
RETRY_DELAY = 2
DEVICE_STARTUP_DELAY = 2
SERIAL_TIMEOUT = 1
AVOIDED_PORTS = {'/dev/ttyAMA0', '/dev/ttyAMA10', 'COM1'}

def initialize(rhapi):
    controller = FusionController(
        rhapi,
        'tbs',
        'TBS'
    ) 
    rhapi.events.on(Evt.VRX_INITIALIZE, controller.registerHandlers)
    rhapi.fields.register_pilot_attribute(UIField(MAC_ADDR_OPT_NAME, "Fusion MAC Address", UIFieldType.TEXT))
    rhapi.ui.register_panel('vrx_tbs', 'VRX Control: TBS', 'settings')
    port_field = UIField(
        PORT_OPTION, "Manual Port Override", UIFieldType.TEXT,
        value=rhapi.db.option(PORT_OPTION, '') or '',
        desc="Leave empty for automatic detection. Use Run Port Assignment after changing the port.",
    )
    # Preserve config.json storage on current RotorHazard, while allowing older
    # hosts to retain database options. Existing DB values seed new config keys.
    if hasattr(port_field, 'persistent_section'):
        rhapi.config.register_section(PORT_CONFIG_SECTION)
        port_field.persistent_section = PORT_CONFIG_SECTION
    rhapi.fields.register_option(port_field, 'vrx_tbs')
    rhapi.ui.register_quickbutton('vrx_tbs', 'run_autodetect', "Run Port Assignment", controller.discoverPort, args={'manual':True})

class FusionController(VRxController):
    def __init__(self, rhapi, name, label):
        self._rhapi = rhapi
        self.ser = serial.Serial()
        self._serial_lock = Semaphore()
        self._discovering = False
        self._discovery = None
        self._shutting_down = False
        super().__init__(name, label)
        # The base controller's setup() marks controllers ready by default.
        self.ready = False

    def registerHandlers(self, args):
        args['register_fn'](self)

    def _configured_port(self):
        port = None
        if hasattr(UIField, 'persistent_section'):
            port = self._rhapi.config.get(PORT_CONFIG_SECTION, PORT_OPTION)
        if port is None or port is False:
            port = self._rhapi.db.option(PORT_OPTION, '')
        return (port or '').strip()

    def discoverPort(self, args=None):
        manual = bool((args or {}).get('manual'))
        if self._shutting_down:
            return
        if self._discovering:
            if manual:
                self._rhapi.ui.message_notify(self._rhapi.__("Fusion port assignment already in progress"))
            return self._discovery

        port = self._configured_port()
        # Set the guard before spawning so startup and button requests cannot race.
        self._discovering = True
        self.ready = False
        self._discovery = gevent.spawn(self._discover_port, port)
        return self._discovery

    def _close_serial(self):
        self.ready = False
        try:
            self.ser.close()
        except (OSError, serial.SerialException):
            logger.exception("Unable to close Fusion serial port")

    def _probe_port(self, port):
        self._close_serial()
        try:
            self.ser.port = port
            self.ser.baudrate = 921600
            self.ser.timeout = SERIAL_TIMEOUT
            self.ser.write_timeout = SERIAL_TIMEOUT
            self.ser.open()
            gevent.sleep(DEVICE_STARTUP_DELAY)
            self.ser.reset_input_buffer()
            payload = pack(">BBBB", 0x00, 0x01, TBSCommand.IDENTIFY, 0xFF)
            if self.ser.write(payload) != len(payload):
                raise serial.SerialException("Incomplete Fusion identification request")
            response = self.ser.read(10)
            if response == b"Fusion ESP":
                self.ready = True
                logger.info("Found Fusion comms module at %s", port)
                return True
            logger.warning("No Fusion identity response from %s (got %r)", port, response)
        except (OSError, serial.SerialException) as exc:
            logger.warning("Unable to identify Fusion comms module at %s: %s", port, exc)
        finally:
            if not self.ready:
                self._close_serial()
        return False

    def _discover_port(self, configured_port):
        try:
            with self._serial_lock:
                self._close_serial()
                if configured_port:
                    ports = [configured_port]
                    attempts = CONNECT_ATTEMPTS
                else:
                    ports = sorted({p.device for p in serial.tools.list_ports.comports()}
                                   - AVOIDED_PORTS)
                    attempts = 1

                for attempt in range(attempts):
                    for port in ports:
                        if self._probe_port(port):
                            self._rhapi.ui.message_notify(
                                self._rhapi.__("Fusion connected at {}").format(port))
                            return
                    if attempt + 1 < attempts:
                        logger.info("Retrying Fusion at %s (attempt %s/%s)",
                                    configured_port, attempt + 2, attempts)
                        gevent.sleep(RETRY_DELAY)

                logger.warning("No Fusion comms module found after %s attempt(s)", attempts)
                self._rhapi.ui.message_notify(self._rhapi.__(
                    "Failed to connect to Fusion; check the device and use Run Port Assignment to retry"))
        except Exception:
            self._close_serial()
            logger.exception("Fusion port assignment failed")
            self._rhapi.ui.message_notify(self._rhapi.__("Failed to connect to Fusion; see server log"))
        finally:
            self._discovering = False
            self._discovery = None

    def onStartup(self, _args):
        self.discoverPort({})

    def onShutdown(self, _args):
        self._shutting_down = True
        if self._discovery is not None:
            self._discovery.kill()
        with self._serial_lock:
            self._close_serial()
        self._discovering = False
        self._discovery = None

    def onHeatSet(self, _args):
        if self.ready:
            seat_pilots = self._rhapi.race.pilots
            heat = self._rhapi.db.heat_by_id(self._rhapi.race.heat)
            for seat in seat_pilots:
                if seat_pilots[seat]:
                    pilot = self._rhapi.db.pilot_by_id(seat_pilots[seat])
                    address = self._rhapi.db.pilot_attribute_value(seat_pilots[seat], MAC_ADDR_OPT_NAME)
                    if address:
                        address = int(address.strip()[:12], 16)

                        if heat:
                            round_num = self._rhapi.db.heat_max_round(self._rhapi.race.heat) or 0
                            osdData = OSDData(0, 0, 
                                pilot.display_callsign,
                                '{} {}'.format(self._rhapi.__("Round"), round_num + 1),
                                heat.display_name
                            )

                        else:
                            osdData = OSDData(0, 0, 
                                pilot.display_callsign,
                                '',
                                self._rhapi.__("Ready"),
                            )

                        self.sendLapMessage(address, osdData)

    def onRaceStage(self, _args):
        if self.ready:
            seat_pilots = self._rhapi.race.pilots
            for seat in seat_pilots:
                if seat_pilots[seat]:
                    pilot = self._rhapi.db.pilot_by_id(seat_pilots[seat])
                    address = self._rhapi.db.pilot_attribute_value(seat_pilots[seat], MAC_ADDR_OPT_NAME)
                    if address:
                        address = int(address.strip()[:12], 16)

                        osdData = OSDData(0, 0,
                            pilot.display_callsign,
                            '', 
                            self._rhapi.__("Arm now"),
                        )
                        self.sendLapMessage(address, osdData)

    def onRaceStart(self, _args):
        #TODO: Schedule start message per race
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                '',
                self._rhapi.__("Go")
            )
            self.sendBroadcastMessage(osdData)

    def onRaceFinish(self, _args):
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                '',
                self._rhapi.__("Time Expired")
            )
            self.sendBroadcastMessage(osdData)

    def onRaceStop(self, _args):
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                self._rhapi.__("Race Stopped"),
                self._rhapi.__("Land Now")
            )
            self.sendBroadcastMessage(osdData)

    def onRaceLapRecorded(self, args):
        if self.ready:
            if 'node_index' not in args:
                logger.error('Failed to send results: Seat not specified')
                return False

            # Get relevant results
            if 'gap_info' in args:
                info = args['gap_info']
            else:
                info = Results.get_gap_info(self.racecontext, args['node_index'])

            # Set up output objects
            TIME_FORMAT = self._rhapi.db.option('timeFormat')
            LAP_HEADER = '{:<3}'.format(self._rhapi.db.option('osd_lapHeader', "LAP"))
            PREVIOUS_LAP_HEADER = '{:<3}'.format(self._rhapi.db.option('osd_previousLapHeader', "PRV"))
            POS_HEADER = '{:<1}'.format(self._rhapi.db.option('osd_positionHeader', "P"))
            BEST_LAP_TEXT = self._rhapi.__('Best Lap')
            HOLESHOT_TEXT = self._rhapi.__('HS')
            LEADER_TEXT = self._rhapi.__('Leader')

            if info.current.lap_number:
                lap_prefix = LAP_HEADER
            else:
                lap_prefix = HOLESHOT_TEXT

            if info.next_rank.lap_number:
                next_rank_lap_prefix = LAP_HEADER
            else:
                next_rank_lap_prefix = HOLESHOT_TEXT

            # Format and send messages

            # Pos X Lap X
            # LAP 0:00.000
            osdCrosserData = OSDData(
                info.current.position,
                info.current.lap_number,
                lap_prefix + ' ' + RHUtils.time_format(info.current.last_lap_time, TIME_FORMAT),
                '',
                '',
            )

            if info.race.win_condition == WinCondition.FASTEST_CONSECUTIVE:
                # Pos X Lap X
                # LAP 0:00.000
                if info.current.lap_number > 1:
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PRV 0:00.000
                    # X/  0:00.000
                    osdCrosserData.text2 = PREVIOUS_LAP_HEADER + ' ' + RHUtils.time_format(info.current.lap_list[-2]['lap_raw'], TIME_FORMAT)
                    osdCrosserData.text3 = str(info.current.consecutives_base) + '/  ' + RHUtils.time_format(info.current.consecutives, TIME_FORMAT)

            elif info.race.win_condition == WinCondition.FASTEST_LAP:
                # Pos X Lap X
                # LAP 0:00.000

                if info.next_rank.diff_time:
                    # pilot in 2nd or self has faster lap
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PX +0:00.000
                    #  Callsign
                    osdCrosserData.text2 = POS_HEADER + str(info.next_rank.position) + ' +' + RHUtils.time_format(info.next_rank.diff_time, TIME_FORMAT)
                    osdCrosserData.text3 = ' ' + info.next_rank.callsign
                elif info.current.is_best_lap and info.current.lap_number:
                    # pilot in 1st, is best lap, 
                    # Pos X Lap X
                    # LAP 0:00.000
                    # Best Lap
                    #
                    osdCrosserData.text2 = LEADER_TEXT
                    osdCrosserData.text3 = BEST_LAP_TEXT
            else:
                # WinCondition.MOST_LAPS
                # WinCondition.FIRST_TO_LAP_X
                # WinCondition.NONE

                # Pos X Lap X
                # LAP 0:00.000

                if info.next_rank.diff_time:
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PX +0:00.000
                    #  Callsign
                    osdCrosserData.text2 = POS_HEADER + str(info.next_rank.position) + ' +' + RHUtils.time_format(info.next_rank.diff_time, TIME_FORMAT)
                    osdCrosserData.text3 = ' ' + info.next_rank.callsign
                else:
                    # Pos X Lap X
                    # LAP 0:00.000
                    #  Leader
                    #
                    osdCrosserData.text2 = ' ' + LEADER_TEXT

            # send message to crosser
            address = self._rhapi.db.pilot_attribute_value(info.current.pilot_id, MAC_ADDR_OPT_NAME)
            if address:
                address = int(address.strip()[:12], 16)
                self.sendLapMessage(address, osdCrosserData)

            # show split when next pilot crosses
            if info.next_rank.diff_time:
                if info.race.win_condition == WinCondition.FASTEST_CONSECUTIVE or info.race.win_condition == WinCondition.FASTEST_LAP:
                    # don't update
                    pass

                else:
                    # WinCondition.MOST_LAPS
                    # WinCondition.FIRST_TO_LAP_X
                    # WinCondition.NONE

                    # update pilot ahead with split-behind
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PX -0:00.000
                    #  Callsign
                    osdSplitData = OSDData(
                        info.next_rank.position,
                        info.next_rank.lap_number,
                        next_rank_lap_prefix + ' ' + RHUtils.time_format(info.next_rank.last_lap_time),
                        POS_HEADER + str(info.current.position) + ' -' + RHUtils.time_format(info.next_rank.diff_time, TIME_FORMAT),
                        ' ' + info.current.callsign
                    )

                    address = self._rhapi.db.pilot_attribute_value(info.next_rank.pilot_id, MAC_ADDR_OPT_NAME)
                    if address:
                        address = int(address.strip()[:12], 16)
                        self.sendLapMessage(address, osdSplitData)

    def onLapsClear(self, _args):
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                '',
                ''
            )
            self.sendBroadcastMessage(osdData)

    def onSendMessage(self, args):
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                '',
                args['message']
            )
            self.sendBroadcastMessage(osdData)

    def sendBroadcastMessage(self, osdData):
        nodes = self._rhapi.race.pilots
        for node in nodes:
            if nodes[node]:
                address = self._rhapi.db.pilot_attribute_value(nodes[node], MAC_ADDR_OPT_NAME)
                if address:
                    address = int(address.strip()[:12], 16)
                    self.sendLapMessage(address, osdData)

    def sendLapMessage(self, address, osdData):
        if not self.ready or self._discovering or self._shutting_down:
            return
        addr = address.to_bytes(6, 'big')

        try:
            pos = int(osdData.pos)
        except ValueError:
            pos = 0

        try:
            lap = int(osdData.lap)
        except ValueError:
            lap = 0

        text1 = str.encode('{:<15}\0'.format(str(osdData.text1)[:15]))
        text2 = str.encode('{:<15}\0'.format(str(osdData.text2)[:15]))
        text3 = str.encode('{:<20}\0'.format(str(osdData.text3)[:20]))

        data = pack(">B 6s B B 16s 16s 21s", TBSCommand.DISPLAY_DATA, addr, pos, lap, text1, text2, text3 )

        payload = pack(">BB {}s B".format(len(data)), 0x00, len(data), data, 0xFF)

        with self._serial_lock:
            if not self.ready or self._discovering or self._shutting_down:
                return
            try:
                if self.ser.write(payload) != len(payload):
                    raise serial.SerialException("Incomplete Fusion message")
                logger.debug('VRxC Fusion message: {}\n{}'.format(hex(address), osdData))
            except (OSError, serial.SerialException) as ex:
                logger.warning("Unable to send Fusion data on %s: %s", self.ser.port, ex)
                self._close_serial()
                self._rhapi.ui.message_notify(self._rhapi.__(
                    "Fusion connection lost; use Run Port Assignment to reconnect"))


class TBSCommand():
    IDENTIFY = 0x01
    DISPLAY_DATA = 0x10

class OSDData():
    def __init__(self, pos, lap, text1, text2, text3):
        self.pos = pos
        self.lap = lap
        self.text1 = text1 #15
        self.text2 = text2 #15
        self.text3 = text3 #20

    def __repr__(self):
        return '<OSD> P{} L{}\n {}\n {}\n {}'.format(self.pos, self.lap, self.text1, self.text2, self.text3)
