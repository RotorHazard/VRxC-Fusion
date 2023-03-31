
import logging
import serial
import serial.tools.list_ports
from RHRace import WinCondition
import RHUtils
from VRxControl import VRxController, VRxDevice, VRxDeviceMethod

logger = logging.getLogger(__name__)

def registerHandlers(args):
    if 'registerFn' in args:
        args['registerFn'](TBSController(
            'tbs',
            'TBS'
        ))

def initialize(**kwargs):
    if 'Events' in kwargs:
        kwargs['Events'].on('VRxC_Initialize', 'VRx_register_tbs', registerHandlers, {}, 75)
    if 'RHUI' in kwargs:
        kwargs['RHUI'].register_pilot_attribute("mac", "Fusion MAC Address", "text")

class TBSController(VRxController):
    def __init__(self, name, label):
        self.ser = serial.Serial()
        super().__init__(name, label)

    def onStartup(self, _args):
        self.ser.baudrate = 115200

        # Find port for TBS comms device
        port = self.RHData.get_option('tbs_comms_port', None)
        if port:
            self.ser.port = port
        else:
            # Automatic port discovery
            logger.debug("Finding serial port for TBS comms device")

            payload = bytearray()
            payload.extend(0x00.to_bytes(1, 'big')) # Packet start
            payload.extend(0x01.to_bytes(1, 'big')) # Packet length
            payload.extend(TBSCommand.IDENTIFY.to_bytes(1, 'big')) # Packet data
            payload.extend(0xFF.to_bytes(1, 'big')) # Packet terminate

            ports = list(serial.tools.list_ports.comports())
            self.ser.timeout = 1

            for p in ports:
                self.ser.port = p.device
                self.ser.open()
                self.ser.write(payload)
                response = self.ser.read(10)
                if response.decode()[:10] == "Fusion ESP":
                    logger.info("Found Fusion comms module at {}".format(p.device))
                    self.ser.port = p.device
                    self.ser.close()
                    return
                else:
                    logger.debug("No Fusion comms module at {} (got {})".format(p.device, response))
                self.ser.close()

        logger.warning("No Fusion comms module discovered")

    def onRaceLapRecorded(self, args):
        if 'node_index' in args:
            seat_index = args['node_index']
        else:
            logger.warning('Failed to send results: Seat not specified')
            return False

        '''
        Get relevant results
        '''

        results = self.RACE.get_results(self.RHData)

        # select correct results
        # *** leaderboard = results[results['meta']['primary_leaderboard']]
        win_condition = self.RACE.format.win_condition

        if win_condition == WinCondition.FASTEST_3_CONSECUTIVE:
            leaderboard = results['by_consecutives']
        elif win_condition == WinCondition.FASTEST_LAP:
            leaderboard = results['by_fastest_lap']
        else:
            # WinCondition.MOST_LAPS
            # WinCondition.FIRST_TO_LAP_X
            # WinCondition.NONE
            leaderboard = results['by_race_time']

        # get this seat's results
        for index, result in enumerate(leaderboard):
            if result['node'] == seat_index: #TODO issue408
                rank_index = index
                break

        # check for best lap
        is_best_lap = False
        if result['fastest_lap_raw'] == result['last_lap_raw']:
            is_best_lap = True

        # get the next faster results
        next_rank_split = None
        next_rank_split_result = None
        if result['position'] > 1:
            next_rank_split_result = leaderboard[rank_index - 1]

            if next_rank_split_result['total_time_raw']:
                if win_condition == WinCondition.FASTEST_3_CONSECUTIVE:
                    if next_rank_split_result['consecutives_raw']:
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

        '''
        Set up output objects
        '''

        LAP_HEADER = self.RHData.get_option('osd_lapHeader')
        POS_HEADER = self.RHData.get_option('osd_positionHeader')
        
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
            osd['lap_prefix'] = ''
            osd['lap_number'] = 0 #self.Language.__('HS')
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
                osd_next_rank['lap_prefix'] = ''
                osd_next_rank['lap_number'] = 0 #self.Language.__('HS')
                osd_next_rank['last_lap_time'] = next_rank_split_result['total_time']

        if first_rank_split:
            osd_first_split = {
                'position_prefix': POS_HEADER,
                'position': str(first_rank_split_result['position']),
                'callsign': first_rank_split_result['callsign'],
                'split_time': RHUtils.time_format(first_rank_split, self.RHData.get_option('timeFormat')),
            }

        '''
        Format and send messages
        '''

        osdCrosserData = OSDData(
            int(str(osd['position'])), 
            int(str(osd['lap_number'])), 
            'LAP ' + osd['last_lap_time'],
            '',
            '',
        )

        # "Pos-Callsign L[n]|0:00:00"
        #message = osd['position_prefix'] + osd['position'] + '-' + osd['callsign'][:10] + ' ' + osd['lap_prefix'] + osd['lap_number'] + '|' + osd['last_lap_time']

        if win_condition == WinCondition.FASTEST_3_CONSECUTIVE:
            # "Pos-Callsign L[n]|0:00:00 | #/0:00.000" (current | best consecutives)
            if result['laps'] >= 3:
                osdCrosserData.text1 = '3/' + osd['consecutives']
                osdCrosserData.text2 = osd['last_lap_time']
            elif result['laps'] == 2:
                osdCrosserData.text1 = '2/' + osd['total_time_laps']
                osdCrosserData.text2 = osd['last_lap_time']

        elif win_condition == WinCondition.FASTEST_LAP:
            if next_rank_split:
                # pilot in 2nd or lower
                # "Pos-Callsign L[n]|0:00:00 / +0:00.000 Callsign"
                osdCrosserData.text3 = 'P' + osd_next_split['position'] + ' +' + osd_next_split['split_time']
                osdCrosserData.text3 = '  ' + osd_next_split['callsign']
            elif osd['is_best_lap']:
                # pilot in 1st and is best lap
                # "Pos:Callsign L[n]:0:00:00 / Best"
                osdCrosserData.text3 = self.Language.__('Best Lap')
        else:
            # WinCondition.MOST_LAPS
            # WinCondition.FIRST_TO_LAP_X
            # WinCondition.NONE

            # "Pos-Callsign L[n]|0:00:00 / +0:00.000 Callsign"
            if next_rank_split:
                osdCrosserData.text2 = 'P' + osd_next_split['position'] + ' +' + osd_next_split['split_time']
                osdCrosserData.text3 = '  ' + osd_next_split['callsign']

        # send message to crosser
        address = self.RHData.get_pilot_attribute_value(osd['pilot_id'], 'mac')
        if address:
            address = int(address, 16)
            self.sendLapMessage(address, osdCrosserData)
            logger.debug('VRxC Fusion: Lap/Pilot {}/Mac {}'.format(osd['pilot_id'], hex(address)))

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

                osdSplitData = OSDData(
                    osd_next_rank['position'], 
                    osd_next_rank['lap_number'], 
                    'LAP ' + osd_next_rank['last_lap_time'],
                    'P' + osd_next_rank['position'] + ' -' + osd_next_split['split_time'],
                    '-' + osd_next_rank['callsign']
                )

                # "Pos-Callsign L[n]|0:00:00"
                # message = osd_next_rank['position_prefix'] + osd_next_rank['position'] + '-' + osd_next_rank['callsign'][:10] + ' ' + osd_next_rank['lap_prefix'] + osd_next_rank['lap_number'] + '|' + osd_next_rank['last_lap_time']

                # "Pos-Callsign L[n]|0:00:00 / -0:00.000 Callsign"
                # message += ' / -' + osd_next_split['split_time'] + ' ' + osd['callsign'][:10]

                address = self.RHData.get_pilot_attribute_value(osd_next_rank['pilot_id'], 'mac')
                if address:
                    address = int(address, 16)
                    self.sendLapMessage(address, osdCrosserData)
                    logger.debug('VRxC Fusion: Split/Pilot {}/Mac {}'.format(osd_next_rank['pilot_id'], hex(address)))

    def sendLapMessage(self, address, osdData):
        data = bytearray()
        data.extend(TBSCommand.DISPLAY_DATA.to_bytes(1, 'big'))
        data.extend(address.to_bytes(6, 'big'))
        data.extend(osdData.pos.to_bytes(1, 'big'))
        data.extend(osdData.lap.to_bytes(1, 'big'))
        data.extend(str.encode('{:<15}'.format(str(osdData.text1)[:15])))
        data.extend(str.encode('{:<15}'.format(str(osdData.text2)[:15])))
        data.extend(str.encode('{:<20}'.format(str(osdData.text3)[:20])))

        payload = bytearray()
        payload.extend(0x00.to_bytes(1, 'big')) # Packet start
        payload.extend(len(data).to_bytes(1, 'big')) # Packet length
        payload.extend(data) # Packet data
        payload.extend(0xFF.to_bytes(1, 'big')) # Packet terminate

        self.ser.open()
        self.ser.write(payload)
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