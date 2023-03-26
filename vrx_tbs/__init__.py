
import logging
import serial
from RHRace import WinCondition
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
        kwargs['Events'].on('VRxC_Initialize', 'VRx_register_tbs', registerHandlers, {}, 75, True)

class TBSController(VRxController):
    def __init__(self, name, label):
        self.ser = serial.Serial()
        super().__init__(name, label)

    def onStartup(self, _args):
        self.ser.baudrate = 115200
        self.ser.port = 'COM3'

    def onRaceLapRecorded(self, args):
        cmd = TBSCommand.LAP_DATA
        address = 0x483fda49a6b9

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

        osd = {
            'position': int(result['position'] or 0),
            'callsign': result['callsign'],
            'lap_number': 0,
            'last_lap_time': '',
            'last_lap_raw': 0,
            'total_time': result['total_time'],
            'total_time_laps': result['total_time_laps'],
            'total_time_laps_raw': int(result['total_time_laps_raw'] or 0),
            'consecutives_raw': int(result['consecutives_raw'] or 0),
            'is_best_lap': is_best_lap,
        }

        if result['laps']:
            osd['lap_number'] = int(result['laps'] or 0)
            osd['last_lap_raw'] = int(result['last_lap_raw'] or 0)
        else:
            osd['lap_number'] = 0 # HS
            osd['last_lap_raw'] = int(result['total_time_raw'] or 0)
            osd['is_best_lap'] = False

        if next_rank_split:
            osd_next_split = {
                'position': int(next_rank_split_result['position'] or 0),
                'callsign': next_rank_split_result['callsign'],
                'split_time_raw': int(next_rank_split),
            }

            osd_next_rank = {
                'position': int(next_rank_split_result['position'] or 0),
                'callsign': next_rank_split_result['callsign'],
                'lap_number': 0,
                'last_lap_raw': 0,
                'total_time': result['total_time'],
            }

            if next_rank_split_result['laps']:
                osd_next_rank['lap_number'] = int(next_rank_split_result['laps'] or 0)
                osd_next_rank['last_lap_raw'] = int(next_rank_split_result['last_lap_raw'] or 0)
            else:
                osd_next_rank['lap_number'] = 0 # HS
                osd_next_rank['last_lap_raw'] = int(next_rank_split_result['total_time_raw'] or 0)

        if first_rank_split:
            osd_first_split = {
                'position': int(first_rank_split_result['position'] or 0),
                'callsign': first_rank_split_result['callsign'],
                'split_time_raw': int(first_rank_split or 0)
            }

        '''
        Format and send messages
        '''

        osdCrosserData = OSDData(
            osd['position'], 
            osd['lap_number'], 
            osd['last_lap_raw'], 
            0,
            osd['callsign'][:10]
        )

        # "Pos-Callsign L[n]|0:00:00"
        #message = osd['position_prefix'] + osd['position'] + '-' + osd['callsign'][:10] + ' ' + osd['lap_prefix'] + osd['lap_number'] + '|' + osd['last_lap_time']

        if win_condition == WinCondition.FASTEST_3_CONSECUTIVE:
            # "Pos-Callsign L[n]|0:00:00 | #/0:00.000" (current | best consecutives)
            if result['laps'] >= 3:
                osdCrosserData.last_lap_ms = osd['consecutives_raw']
            elif result['laps'] == 2:
                osdCrosserData.last_lap_ms = osd['total_time_laps_raw']

        elif win_condition == WinCondition.FASTEST_LAP:
            if next_rank_split:
                # pilot in 2nd or lower
                # "Pos-Callsign L[n]|0:00:00 / +0:00.000 Callsign"
                osdCrosserData.last_lap_ms = osd_next_split['split_time_raw']
                osdCrosserData.freetext = '+' + osd_next_split['callsign'][:10]
            elif osd['is_best_lap']:
                # pilot in 1st and is best lap
                # "Pos:Callsign L[n]:0:00:00 / Best"
                osdCrosserData.freetext = self.Language.__('Best Lap')
        else:
            # WinCondition.MOST_LAPS
            # WinCondition.FIRST_TO_LAP_X
            # WinCondition.NONE

            # "Pos-Callsign L[n]|0:00:00 / +0:00.000 Callsign"
            if next_rank_split:
                osdCrosserData.last_lap_ms = osd_next_split['split_time_raw']
                osdCrosserData.freetext = '+' + osd_next_split['callsign'][:10]

        # send message to crosser
        seat_dest = seat_index
        # TODO: set address

        data = bytearray()
        data.extend(cmd.to_bytes(1, 'big'))
        data.extend(address.to_bytes(6, 'big'))
        data.extend(osdCrosserData.position.to_bytes(4, 'big'))
        data.extend(osdCrosserData.lap_number.to_bytes(4, 'big'))
        data.extend(osdCrosserData.current_lap_ms.to_bytes(4, 'big'))
        data.extend(osdCrosserData.last_lap_ms.to_bytes(4, 'big'))
        data.extend(str.encode(osdCrosserData.freetext[:32]))

        payload = bytearray()
        payload.extend(0x00.to_bytes(1, 'big'))
        payload.extend(len(data).to_bytes(1, 'big'))
        payload.extend(data)
        payload.extend(0xFF.to_bytes(1, 'big'))

        self.ser.open()
        self.ser.write(payload)
        self.ser.close()

        logger.debug('tbs n{1}: {0}'.format(data, seat_dest))

        '''
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
                    osd_next_rank['last_lap_raw'], 
                    osd_next_split['split_time_raw'],
                    '-' + osd_next_rank['callsign'][:10]
                )

                # "Pos-Callsign L[n]|0:00:00"
                # message = osd_next_rank['position_prefix'] + osd_next_rank['position'] + '-' + osd_next_rank['callsign'][:10] + ' ' + osd_next_rank['lap_prefix'] + osd_next_rank['lap_number'] + '|' + osd_next_rank['last_lap_time']

                # "Pos-Callsign L[n]|0:00:00 / -0:00.000 Callsign"
                # message += ' / -' + osd_next_split['split_time'] + ' ' + osd['callsign'][:10]

                seat_dest = leaderboard[rank_index - 1]['node']
                # TODO: set address

                data = bytearray()
                data.extend(cmd.to_bytes(1, 'big'))
                data.extend(address.to_bytes(6, 'big'))
                data.extend(osdSplitData.position.to_bytes(4, 'big'))
                data.extend(osdSplitData.lap_number.to_bytes(4, 'big'))
                data.extend(osdSplitData.current_lap_ms.to_bytes(4, 'big'))
                data.extend(osdSplitData.last_lap_ms.to_bytes(4, 'big'))
                data.extend(str.encode(osdSplitData.freetext[:32]))

                payload = bytearray()
                payload.extend(0x00.to_bytes(1, 'big'))
                payload.extend(len(data).to_bytes(1, 'big'))
                payload.extend(data)
                payload.extend(0xFF.to_bytes(1, 'big'))

                self.ser.open()
                self.ser.write(payload)
                self.ser.close()

                logger.debug('tbs n{1}: {0}'.format(data, seat_dest))
        '''

class TBSCommand():
    READY_HEAT = 0x00
    JOIN_ADDRESS = 0x01
    LAP_DATA = 0x10

class OSDData():
    def __init__(self, position, lap_number, current_lap_ms, last_lap_ms, freetext):
        self.position = position
        self.lap_number = lap_number
        self.current_lap_ms = current_lap_ms
        self.last_lap_ms = last_lap_ms
        self.freetext = freetext