
import logging
import serial
import serial.tools.list_ports
import time
from struct import pack
from RHRace import WinCondition
import RHUtils
import Results
from VRxControl import VRxController, VRxDevice, VRxDeviceMethod

logger = logging.getLogger(__name__)

def registerHandlers(args):
    if 'registerFn' in args:
        args['registerFn'](FusionController(
            'tbs',
            'TBS'
        ))

def initialize(**kwargs):
    if 'Events' in kwargs:
        kwargs['Events'].on('VRxC_Initialize', 'VRx_register_tbs', registerHandlers, {}, 75)
    if 'RHAPI' in kwargs:
        kwargs['RHAPI'].register_pilot_attribute("mac", "Fusion MAC Address", "text")

class FusionController(VRxController):
    def __init__(self, name, label):
        self.ser = serial.Serial()
        super().__init__(name, label)

    def discoverPort(self):
        # Find port for TBS comms device
        port = self.racecontext.rhdata.get_option('tbs_comms_port', None)
        if port:
            self.ser.port = port
            logger.info("Using port {} from config for Fusion comms module".format(port))
            return
        else:
            # Automatic port discovery
            logger.debug("Finding serial port for TBS comms device")

            payload = pack(">BBBB", 0x00, 0x01, TBSCommand.IDENTIFY, 0xFF)

            ports = list(serial.tools.list_ports.comports())
            self.ser.timeout = 1

            for p in ports:
                try:
                    response = None
                    self.ser.port = p.device
                    self.ser.open()
                    time.sleep(2)
                    self.ser.reset_input_buffer()
                    self.ser.write(payload)
                    response = self.ser.read(10)
                    try:
                        if response.decode()[:10] == "Fusion ESP":
                            logger.info("Found Fusion comms module at {}".format(p.device))
                            self.ready = True
                            return
                    except:
                        pass
                except serial.serialutil.SerialException:
                    pass

                logger.debug("No Fusion comms module at {} (got {})".format(p.device, response))

                self.ser.close()

            logger.warning("No Fusion comms module discovered or configured")
            self.ready = False

    def onStartup(self, _args):
        self.ser.baudrate = 921600
        self.discoverPort()

    def onHeatSet(self, _args):
        if self.ready:
            seat_pilots = self.racecontext.race.node_pilots
            heat = self.racecontext.rhdata.get_heat(self.racecontext.race.current_heat)
            for seat in seat_pilots:
                if seat_pilots[seat]:
                    pilot = self.racecontext.rhdata.get_pilot(seat_pilots[seat])
                    address = self.racecontext.rhdata.get_pilot_attribute_value(seat_pilots[seat], 'mac')
                    if address:
                        address = int(address.strip()[:12], 16)

                        if heat:
                            round_num = self.racecontext.rhdata.get_max_round(self.racecontext.race.current_heat) or 0
                            osdData = OSDData(0, 0, 
                                pilot.callsign,
                                '{} {}'.format(self.racecontext.language.__("Round"), round_num + 1),
                                heat.displayname()
                            )

                        else:
                            osdData = OSDData(0, 0, 
                                pilot.callsign,
                                '',
                                self.racecontext.language.__("Ready"),
                            )

                        self.sendLapMessage(address, osdData)

    def onRaceStage(self, _args):
        if self.ready:
            seat_pilots = self.racecontext.race.node_pilots
            for seat in seat_pilots:
                if seat_pilots[seat]:
                    pilot = self.racecontext.rhdata.get_pilot(seat_pilots[seat])
                    address = self.racecontext.rhdata.get_pilot_attribute_value(seat_pilots[seat], 'mac')
                    if address:
                        address = int(address.strip()[:12], 16)

                        osdData = OSDData(0, 0,
                            pilot.callsign,
                            '', 
                            self.racecontext.language.__("Arm now"),
                        )
                        self.sendLapMessage(address, osdData)

    def onRaceStart(self, _args):
        #TODO: Schedule start message per race
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                '',
                self.racecontext.language.__("Go")
            )
            self.sendBroadcastMessage(osdData)

    def onRaceFinish(self, _args):
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                '',
                self.racecontext.language.__("Time Expired")
            )
            self.sendBroadcastMessage(osdData)

    def onRaceStop(self, _args):
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                self.racecontext.language.__("Race Stopped"),
                self.racecontext.language.__("Land Now")
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
            TIME_FORMAT = self.racecontext.rhdata.get_option('timeFormat')
            LAP_HEADER = '{:<3}'.format(self.racecontext.rhdata.get_option('osd_lapHeader', "LAP"))
            PREVIOUS_LAP_HEADER = '{:<3}'.format(self.racecontext.rhdata.get_option('osd_previousLapHeader', "PRV"))
            POS_HEADER = '{:<1}'.format(self.racecontext.rhdata.get_option('osd_positionHeader', "P"))
            BEST_LAP_TEXT = self.racecontext.language.__('Best Lap')
            HOLESHOT_TEXT = self.racecontext.language.__('HS')
            LEADER_TEXT = self.racecontext.language.__('Leader')

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

            if info.race.win_condition == WinCondition.FASTEST_3_CONSECUTIVE:
                # Pos X Lap X
                # LAP 0:00.000
                if info.current.lap_number >= 3:
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PRV 0:00.000
                    # 3/  0:00.000
                    osdCrosserData.text2 = PREVIOUS_LAP_HEADER + ' ' + RHUtils.time_format(info.current.lap_list[-2]['lap_raw'], TIME_FORMAT)
                    osdCrosserData.text3 = '3/  ' + RHUtils.time_format(info.current.consecutives, TIME_FORMAT)
                elif info.current.lap_number == 2:
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PRV 0:00.000
                    # 2/  0:00.000
                    osdCrosserData.text2 = PREVIOUS_LAP_HEADER + ' ' + RHUtils.time_format(info.current.lap_list[-2]['lap_raw'], TIME_FORMAT)
                    osdCrosserData.text3 = '2/  ' + RHUtils.time_format(info.current.total_time_laps, TIME_FORMAT)

            elif info.race.win_condition == WinCondition.FASTEST_LAP:
                # Pos X Lap X
                # LAP 0:00.000

                if info.next_rank.split_time:
                    # pilot in 2nd or self has faster lap
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PX +0:00.000
                    #  Callsign
                    osdCrosserData.text2 = POS_HEADER + str(info.next_rank.position) + ' +' + RHUtils.time_format(info.next_rank.split_time, TIME_FORMAT)
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

                if info.next_rank.split_time:
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PX +0:00.000
                    #  Callsign
                    osdCrosserData.text2 = POS_HEADER + str(info.next_rank.position) + ' +' + RHUtils.time_format(info.next_rank.split_time, TIME_FORMAT)
                    osdCrosserData.text3 = ' ' + info.next_rank.callsign
                else:
                    # Pos X Lap X
                    # LAP 0:00.000
                    #  Leader
                    #
                    osdCrosserData.text2 = ' ' + LEADER_TEXT

            # send message to crosser
            address = self.racecontext.rhdata.get_pilot_attribute_value(info.current.pilot_id, 'mac')
            if address:
                address = int(address.strip()[:12], 16)
                self.sendLapMessage(address, osdCrosserData)

            # show split when next pilot crosses
            if info.next_rank.split_time:
                if info.race.win_condition == WinCondition.FASTEST_3_CONSECUTIVE or info.race.win_condition == WinCondition.FASTEST_LAP:
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
                        POS_HEADER + str(info.current.position) + ' -' + RHUtils.time_format(info.next_rank.split_time, TIME_FORMAT),
                        ' ' + info.current.callsign
                    )

                    address = self.racecontext.rhdata.get_pilot_attribute_value(info.next_rank.pilot_id, 'mac')
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
        nodes = self.racecontext.race.node_pilots
        for node in nodes:
            if nodes[node]:
                address = self.racecontext.rhdata.get_pilot_attribute_value(nodes[node], 'mac')
                if address:
                    address = int(address.strip()[:12], 16)
                    self.sendLapMessage(address, osdData)

    def sendLapMessage(self, address, osdData):
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

        try:
            if(self.ser.isOpen() == False):
                self.ser.open()
            self.ser.write(payload)
            logger.debug('VRxC Fusion message: {}\n{}'.format(hex(address), osdData))
        except Exception as ex:
            logger.info("Unable to send Fusion data: {}".format(ex))
            self.ser.close()


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
