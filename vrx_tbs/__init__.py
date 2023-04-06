
import logging
import serial
import serial.tools.list_ports
import time
from struct import pack
from RHRace import WinCondition
import RHUtils
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
    if 'RHUI' in kwargs:
        kwargs['RHUI'].register_pilot_attribute("mac", "Fusion MAC Address", "text")

class FusionController(VRxController):
    def __init__(self, name, label):
        self.ser = serial.Serial()
        super().__init__(name, label)

    def discoverPort(self):
        # Find port for TBS comms device
        port = self.RHData.get_option('tbs_comms_port', None)
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
            nodes = self.RACE.node_pilots
            for node in nodes:
                if nodes[node]:
                    pilot = self.RHData.get_pilot(nodes[node])
                    address = self.RHData.get_pilot_attribute_value(nodes[node], 'mac')
                    if address:
                        address = int(address.strip()[:12], 16)

                        osdData = OSDData(0, 0, 
                            '',
                            self.Language.__("Ready"),
                            pilot.callsign
                        )
                        self.sendLapMessage(address, osdData)

    def onRaceStage(self, _args):
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                self.Language.__("Ready"),
                self.Language.__("Arm now")
            )
            self.sendBroadcastMessage(osdData)

    def onRaceStart(self, _args):
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                '',
                self.Language.__("Go")
            )
            self.sendBroadcastMessage(osdData)

    def onRaceFinish(self, _args):
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                '',
                self.Language.__("Finish")
            )
            self.sendBroadcastMessage(osdData)

    def onRaceStop(self, _args):
        if self.ready:
            osdData = OSDData(0, 0, 
                '',
                self.Language.__("Land Now"),
                self.Language.__("Race Stopped")
            )
            self.sendBroadcastMessage(osdData)

    def onRaceLapRecorded(self, args):
        if self.ready:
            if 'node_index' not in args:
                logger.error('Failed to send results: Seat not specified')
                return False

            # Get relevant results

            # select correct results
            # *** leaderboard = results[results['meta']['primary_leaderboard']]
            win_condition = self.RACE.format.win_condition
            laps = None

            if win_condition == WinCondition.FASTEST_3_CONSECUTIVE:
                leaderboard = args['results']['by_consecutives']
                laps = self.RACE.get_lap_results(self.RHData)['node_index'][args['node_index']]
            elif win_condition == WinCondition.FASTEST_LAP:
                leaderboard = args['results']['by_fastest_lap']
            else:
                # WinCondition.MOST_LAPS
                # WinCondition.FIRST_TO_LAP_X
                # WinCondition.NONE
                leaderboard = args['results']['by_race_time']

            # get this seat's results
            result = None
            for index, result in enumerate(leaderboard):
                if result['node'] == args['node_index']:
                    rank_index = index
                    break
            else:
                logger.error('Failed to find results: Node not in result list')
                return False

            # check for best lap
            is_best_lap = False
            if result['fastest_lap_raw'] == result['last_lap_raw']:
                is_best_lap = True

            # get the next faster results
            next_rank_split = None
            next_rank_split_result = None
            if isinstance(result['position'], int) and result['position'] > 1:
                next_rank_split_result = leaderboard[rank_index - 1]

                if next_rank_split_result['total_time_raw']:
                    if win_condition == WinCondition.FASTEST_3_CONSECUTIVE:
                        if next_rank_split_result['consecutives_raw'] and result['consecutives_raw']:
                            next_rank_split = result['consecutives_raw'] - next_rank_split_result['consecutives_raw']
                    elif win_condition == WinCondition.FASTEST_LAP:
                        if next_rank_split_result['fastest_lap_raw']:
                            next_rank_split = result['last_lap_raw'] - next_rank_split_result['fastest_lap_raw']
                    else:
                        # WinCondition.MOST_LAPS
                        # WinCondition.FIRST_TO_LAP_X
                        next_rank_split = result['total_time_raw'] - next_rank_split_result['total_time_raw']
                        next_rank_split_fastest = ''
            else:
                # check split to self
                next_rank_split_result = leaderboard[rank_index]

                if win_condition == WinCondition.FASTEST_3_CONSECUTIVE or win_condition == WinCondition.FASTEST_LAP:
                    if next_rank_split_result['fastest_lap_raw']:
                        if result['last_lap_raw'] > next_rank_split_result['fastest_lap_raw']:
                            next_rank_split = result['last_lap_raw'] - next_rank_split_result['fastest_lap_raw']

            # get the next slower results
            prev_rank_split = None
            prev_rank_split_result = None
            if rank_index + 1 in leaderboard:
                prev_rank_split_result = leaderboard[rank_index - 1]

                if prev_rank_split_result['total_time_raw']:
                    if win_condition == WinCondition.FASTEST_3_CONSECUTIVE:
                        if prev_rank_split_result['consecutives_raw']:
                            prev_rank_split = result['consecutives_raw'] - prev_rank_split_result['consecutives_raw']
                            prev_rank_split_fastest = prev_rank_split
                    elif win_condition == WinCondition.FASTEST_LAP:
                        if prev_rank_split_result['fastest_lap_raw']:
                            prev_rank_split = result['last_lap_raw'] - prev_rank_split_result['fastest_lap_raw']
                            prev_rank_split_fastest = result['fastest_lap_raw'] - prev_rank_split_result['fastest_lap_raw']
                    else:
                        # WinCondition.MOST_LAPS
                        # WinCondition.FIRST_TO_LAP_X
                        prev_rank_split = result['total_time_raw'] - prev_rank_split_result['total_time_raw']
                        prev_rank_split_fastest = ''

            # get the fastest result
            first_rank_split = None
            first_rank_split_result = None
            if result['position'] > 2:
                first_rank_split_result = leaderboard[0]

                if next_rank_split_result['total_time_raw']:
                    if win_condition == WinCondition.FASTEST_3_CONSECUTIVE:
                        if first_rank_split_result['consecutives_raw']:
                            first_rank_split = result['consecutives_raw'] - first_rank_split_result['consecutives_raw']
                    elif win_condition == WinCondition.FASTEST_LAP:
                        if first_rank_split_result['fastest_lap_raw']:
                            first_rank_split = result['last_lap_raw'] - first_rank_split_result['fastest_lap_raw']
                    else:
                        # WinCondition.MOST_LAPS
                        # WinCondition.FIRST_TO_LAP_X
                        first_rank_split = result['total_time_raw'] - first_rank_split_result['total_time_raw']

            # Set up output objects

            LAP_HEADER = '{:<3}'.format(self.RHData.get_option('osd_lapHeader', "LAP"))
            POS_HEADER = '{:<1}'.format(self.RHData.get_option('osd_positionHeader', "P"))

            osd = {
                'pilot_id': result['pilot_id'],
                'position_prefix': POS_HEADER,
                'position': str(result['position']),
                'callsign': result['callsign'],
                'lap_prefix': LAP_HEADER,
                'lap_number': '',
                'last_lap_time': '',
                'total_time': result['total_time'],
                'total_time_laps': result['total_time_laps'],
                'consecutives': result['consecutives'],
                'is_best_lap': is_best_lap,
            }

            if result['laps']:
                osd['lap_number'] = str(result['laps'])
                osd['last_lap_time'] = result['last_lap']
            else:
                osd['lap_prefix'] = '{:<3}'.format(self.Language.__('HS'))
                osd['lap_number'] = 0
                osd['last_lap_time'] = result['total_time']
                osd['is_best_lap'] = False

            if next_rank_split:
                osd_next_split = {
                    'position_prefix': POS_HEADER,
                    'position': str(next_rank_split_result['position']),
                    'callsign': next_rank_split_result['callsign'],
                    'split_time': RHUtils.time_format(next_rank_split, self.RHData.get_option('timeFormat')),
                }

                osd_next_rank = {
                    'pilot_id': next_rank_split_result['pilot_id'],
                    'position_prefix': POS_HEADER,
                    'position': str(next_rank_split_result['position']),
                    'callsign': next_rank_split_result['callsign'],
                    'lap_prefix': LAP_HEADER,
                    'lap_number': '',
                    'last_lap_time': '',
                    'total_time': result['total_time'],
                }

                if next_rank_split_result['laps']:
                    osd_next_rank['lap_number'] = str(next_rank_split_result['laps'])
                    osd_next_rank['last_lap_time'] = next_rank_split_result['last_lap']
                else:
                    osd_next_rank['lap_prefix'] = self.Language.__('HS')
                    osd_next_rank['lap_number'] = 0
                    osd_next_rank['last_lap_time'] = next_rank_split_result['total_time']

            if first_rank_split:
                osd_first_split = {
                    'position_prefix': POS_HEADER,
                    'position': str(first_rank_split_result['position']),
                    'callsign': first_rank_split_result['callsign'],
                    'split_time': RHUtils.time_format(first_rank_split, self.RHData.get_option('timeFormat')),
                }

            # Format and send messages

            # Pos X Lap X
            # LAP 0:00.000
            osdCrosserData = OSDData(
                osd['position'], 
                osd['lap_number'], 
                osd['lap_prefix'] + ' ' + osd['last_lap_time'],
                '',
                '',
            )

            if win_condition == WinCondition.FASTEST_3_CONSECUTIVE:
                # Pos X Lap X
                # LAP 0:00.000
                if result['laps'] >= 3:
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PRV 0:00.000
                    # 3/  0:00.000
                    osdCrosserData.text2 = 'PRV ' + RHUtils.time_format(laps['laps'][-2]['lap_raw'], self.RHData.get_option('timeFormat'))
                    osdCrosserData.text3 = '3/  ' + osd['consecutives']
                elif result['laps'] == 2:
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PRV 0:00.000
                    # 2/  0:00.000
                    osdCrosserData.text2 = 'PRV ' + RHUtils.time_format(laps['laps'][-2]['lap_raw'], self.RHData.get_option('timeFormat'))
                    osdCrosserData.text3 = '2/  ' + osd['total_time_laps']

            elif win_condition == WinCondition.FASTEST_LAP:
                # Pos X Lap X
                # LAP 0:00.000

                if next_rank_split:
                    # pilot in 2nd or lower
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PX +0:00.000
                    #  Callsign
                    osdCrosserData.text2 = osd['position_prefix'] + osd_next_split['position'] + ' +' + osd_next_split['split_time']
                    osdCrosserData.text3 = ' ' + osd_next_split['callsign']
                elif osd['is_best_lap']:
                    # pilot in 1st and is best lap
                    # Pos X Lap X
                    # LAP 0:00.000
                    # Best Lap
                    #
                    osdCrosserData.text2 = self.Language.__('Best Lap')
            else:
                # WinCondition.MOST_LAPS
                # WinCondition.FIRST_TO_LAP_X
                # WinCondition.NONE

                # Pos X Lap X
                # LAP 0:00.000

                if next_rank_split:
                    # Pos X Lap X
                    # LAP 0:00.000
                    # PX +0:00.000
                    #  Callsign
                    osdCrosserData.text2 = osd['position_prefix'] + osd_next_split['position'] + ' +' + osd_next_split['split_time']
                    osdCrosserData.text3 = ' ' + osd_next_split['callsign']
                else:
                    # Pos X Lap X
                    # LAP 0:00.000
                    #  Leader
                    #
                    osdCrosserData.text2 = ' ' + self.Language.__('Leader')

            # send message to crosser
            address = self.RHData.get_pilot_attribute_value(osd['pilot_id'], 'mac')
            if address:
                address = int(address.strip()[:12], 16)
                self.sendLapMessage(address, osdCrosserData)

            # show split when next pilot crosses
            if next_rank_split:
                if win_condition == WinCondition.FASTEST_3_CONSECUTIVE or win_condition == WinCondition.FASTEST_LAP:
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
                        osd_next_rank['position'], 
                        osd_next_rank['lap_number'], 
                        osd['lap_prefix'] + ' ' + osd_next_rank['last_lap_time'],
                        osd_next_rank['position_prefix'] + osd['position'] + ' -' + osd_next_split['split_time'],
                        ' ' + osd['callsign']
                    )

                    address = self.RHData.get_pilot_attribute_value(osd_next_rank['pilot_id'], 'mac')
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
        nodes = self.RACE.node_pilots
        for node in nodes:
            if nodes[node]:
                address = self.RHData.get_pilot_attribute_value(nodes[node], 'mac')
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

        data = pack(">B 6s B B 15s 15s 20s", TBSCommand.DISPLAY_DATA, addr, pos, lap, text1, text2, text3 )

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
