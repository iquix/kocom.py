#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
 python kocom script

 : forked from script written by 따분, Susu Daddy

 apt-get install mosquitto
 python3 -m pip install pyserial
 python3 -m pip install paho-mqtt
'''
import os
import time
import platform
import threading
import queue
import random
import json
import paho.mqtt.client as mqtt
import logging
import configparser


# define -------------------------------

CONFIG_FILE = 'kocom.conf'
BUF_SIZE = 100

read_write_gap = 0.03  # minimal time interval between last read to write
polling_interval = 300  # polling interval

header_h = 'aa55'
trailer_h = '0d0d'
packet_size = 21  # total 21bytes
chksum_position = 18  # 18th byte

type_t_dic = {'30b':'send', '30d':'ack'}
seq_t_dic = {'c':1, 'd':2, 'e':3, 'f':4}
device_t_dic = {'01':'wallpad', '0e':'light', '2c':'gas', '36':'thermo', '44':'elevator', '48':'fan'}
cmd_t_dic = {'00':'state', '01':'on', '02':'off', '3a':'query'}
room_t_dic = {'00':'livingroom', '01':'room1', '02':'room2', '03':'room3'}

type_h_dic = {v: k for k, v in type_t_dic.items()}
seq_h_dic = {v: k for k, v in seq_t_dic.items()}
device_h_dic = {v: k for k, v in device_t_dic.items()}
cmd_h_dic = {v: k for k, v in cmd_t_dic.items()}
room_h_dic = {'livingroom':'00', 'myhome':'00', 'room1':'01', 'room2':'02', 'room3':'03'}

# mqtt functions ----------------------------

def init_mqttc():
    mqttc = mqtt.Client()
    mqttc.on_message = mqtt_on_message
    mqttc.on_subscribe = mqtt_on_subscribe
    mqttc.on_connect = mqtt_on_connect
    mqttc.on_disconnect = mqtt_on_disconnect

    if config.get('MQTT','mqtt_allow_anonymous') != 'True':
        logging.info("[MQTT] connecting using username and password")
        mqttc.username_pw_set(username=config.get('MQTT','mqtt_username',fallback=''), password=config.get('MQTT','mqtt_password',fallback=''))
    mqtt_server = config.get('MQTT','mqtt_server')
    mqtt_port = int(config.get('MQTT','mqtt_port'))
    mqttc.connect(mqtt_server, mqtt_port, 60)
    mqttc.loop_start()
    return mqttc

def mqtt_on_subscribe(mqttc, obj, mid, granted_qos):
    logging.info("[MQTT] Subscribed: " + str(mid) + " " + str(granted_qos))

def mqtt_on_log(mqttc, obj, level, string):
    logging.info("[MQTT] on_log : "+string)

def mqtt_on_connect(mqttc, userdata, flags, rc):
    if rc == 0:
        logging.info("[MQTT] Connected - 0: OK")
        mqttc.subscribe('kocom/#', 0)
    else:
        logging.error("[MQTT] Connection error - {}: {}".format(rc, mqtt.connack_string(rc)))

def mqtt_on_disconnect(mqttc, userdata,rc=0):
    logging.error("[MQTT] Disconnected - "+str(rc))


# serial/socket communication class & functions--------------------

class RS485Wrapper:
    def __init__(self, serial_port=None, socket_server=None, socket_port=0):
        if socket_server == None:
            self.type = 'serial'
            self.serial_port = serial_port
        else:
            self.type = 'socket'
            self.socket_server = socket_server
            self.socket_port = socket_port
        self.last_read_time = 0
        self.conn = False

    def connect(self):
        self.close()
        self.last_read_time = 0
        if self.type=='serial':
            self.conn = self.connect_serial(self.serial_port)
        elif self.type=='socket':
            self.conn = self.connect_socket(self.socket_server, self.socket_port)
        return self.conn

    def connect_serial(self, SERIAL_PORT):
        if SERIAL_PORT==None:
            os_platfrom = platform.system()
            if os_platfrom == 'Linux':
                SERIAL_PORT = '/dev/ttyUSB0'
            else:
                SERIAL_PORT = 'com3'
        try:
            ser = serial.Serial(SERIAL_PORT, 9600, timeout=1)
            ser.bytesize = 8
            ser.stopbits = 1
            if ser.is_open == False:
                raise Exception('Not ready')
            logging.info('Serial connected : {}'.format(ser))
            return ser
        except Exception as e:
            logging.error('Serial open failure : {}'.format(e))
            return False

    def connect_socket(self, SOCKET_SERVER, SOCKET_PORT):
        sock = socket.socket()
        sock.settimeout(10)
        try:
            sock.connect((SOCKET_SERVER, SOCKET_PORT))
        except Exception as e:
            logging.error('Socket connection failure : {} | server {}, port {}'.format(e, SOCKET_SERVER, SOCKET_PORT))
            return False
        logging.info('socket connected | server {}, port {}'.format(SOCKET_SERVER, SOCKET_PORT))
        sock.settimeout(polling_interval+15)   # set read timeout a little bit more than polling interval
        return sock

    def read(self):
        if self.conn == False:
            return ''
        ret = ''
        if self.type=='serial':
            for i in range(polling_interval+15):
                try:
                    ret = self.conn.read()
                except AttributeError:
                    raise Exception('exception occured while reading serial')
                except TypeError:
                    raise Exception('exception occured while reading serial')
                if len(ret) != 0:
                    break
        elif self.type=='socket':
            ret = self.conn.recv(1)

        if len(ret) == 0:
            raise Exception('read byte errror')
        else:
            self.last_read_time = time.time()
        return ret

    def write(self, data):
        if self.conn == False:
            return False
        if self.last_read_time == 0:
            time.sleep(1)
        while time.time() - self.last_read_time < read_write_gap:
            #logging.debug('pending write : time too short after last read')
            time.sleep(max([0, read_write_gap - time.time() + self.last_read_time]))
        if self.type=='serial':
            return self.conn.write(data)
        elif self.type=='socket':
            return self.conn.send(data)
        else:
            return False

    def close(self):
        ret = False
        if self.conn != False:
            try:
                ret = self.conn.close()
                self.conn = False
            except:
                pass
        return ret

    def reconnect(self):
        self.close()
        while True: 
            logging.info('reconnecting to RS485...')
            if self.connect() != False:
                break
            time.sleep(10)



def send(dest, src, cmd, value, log=None, check_ack=True):
    send_lock.acquire()
    ack_data.clear()
    ret = False
    for seq_h in seq_t_dic.keys(): # if there's no ACK received, then repeat sending with next sequence code
        payload = type_h_dic['send'] + seq_h + '00' + dest + src + cmd + value
        send_data = header_h + payload + chksum(payload) + trailer_h 
        try:
            if rs485.write(bytearray.fromhex(send_data)) == False:
                raise Exception('Not ready')
        except Exception as ex:
            logging.error("*** Write error.[{}]".format(ex) )
            break
        if log != None:
            logging.info('[SEND|{}] {}'.format(log, send_data))
        if check_ack == False:
            time.sleep(1)
            ret = send_data
            break

        # wait and checking for ACK
        ack_data.append(type_h_dic['ack'] + seq_h + '00' +  src + dest + cmd + value)
        try:
            ack_q.get(True, 1.3+0.2*random.random()) # random wait between 1.3~1.5 seconds for ACK
            if config.get('Log', 'show_recv_hex') == 'True':
                logging.info ('[ACK] OK')
            ret = send_data
            break
        except queue.Empty:
            pass

    if ret == False:
        logging.info('send failed. closing RS485. it will try to reconnect to RS485 shortly.')
        rs485.close()
    ack_data.clear()
    send_lock.release()
    return ret


def chksum(data_h):
    sum_buf = sum(bytearray.fromhex(data_h))
    return '{0:02x}'.format((sum_buf)%256)  # return chksum hex value in text format


# hex parsing --------------------------------

def parse(hex_data):
    header_h = hex_data[:4]    # aa55
    type_h = hex_data[4:7]    # send/ack : 30b(send) 30d(ack)
    seq_h = hex_data[7:8]    # sequence : c(1st) d(2nd)
    dest_h = hex_data[10:14] # dest addr : 0100(wallpad0) 0e00(light0) 3600(thermo0) 3601(thermo1) 3602(thermo2) 3603(thermo3)
    src_h = hex_data[14:18]   # source addr  
    cmd_h = hex_data[18:20]   # command : 3e(query)
    value_h = hex_data[20:36]  # value
    chksum_h = hex_data[36:38]  # checksum
    trailer_h = hex_data[38:42]  # trailer

    data_h = hex_data[4:36]
    payload_h = hex_data[18:36]
    cmd = cmd_t_dic.get(cmd_h)

    ret = { 'header_h':header_h, 'type_h':type_h, 'seq_h':seq_h, 'dest_h':dest_h, 'src_h':src_h, 'cmd_h':cmd_h, 
            'value_h':value_h, 'chksum_h':chksum_h, 'trailer_h':trailer_h, 'data_h':data_h, 'payload_h':payload_h,
            'type':type_t_dic.get(type_h),
            'seq':seq_t_dic.get(seq_h), 
            'dest':device_t_dic.get(dest_h[:2]),
            'dest_subid':str(int(dest_h[2:4], 16)),
            'src':device_t_dic.get(src_h[:2]),
            'src_subid':str(int(src_h[2:4], 16)),
            'cmd':cmd if cmd!=None else cmd_h,
            'value':value_h,
            'time': time.time(),
            'flag':None}
    return ret


def thermo_parse(value):
    ret = { 'heat_mode': 'heat' if value[:2]=='11' else 'off',
            'away': 'true' if value[2:4]=='01' else 'false',
            'set_temp': int(value[4:6], 16),
            'cur_temp': int(value[8:10], 16)}
    return ret


def light_parse(value):
    ret = {}
    for i in range(1,9):
        ret['light_'+str(i)] = 'off' if value[i*2-2:i*2] == '00' else 'on'
    return ret


def fan_parse(value):
    level_dic = {'40':'1', '80':'2', 'c0':'3'}
    state = 'off' if value[:2] == '00' else 'on'
    level = '0' if state == 'off' else level_dic.get(value[4:6])
    return { 'state': state, 'level': level}


# query device --------------------------

def query(device_h, publish=False):
    # find from the cache first
    for c in cache_data:
        if time.time() - c['time'] > polling_interval:  # if there's no data within polling interval, then exit cache search
            break
        if c['type']=='ack' and c['src']=='wallpad' and c['dest_h']==device_h and c['cmd']!='query':
            if (config.get('Log', 'show_query_hex')=='True'):
                logging.info('[cache|{}{}] query cache {}'.format(c['dest'], c['dest_subid'], c['data_h']))
            return c  # return the value in the cache

    # if there's no cache data within polling inteval, then send query packet
    if (config.get('Log', 'show_query_hex')=='True'):
        log = 'query ' + device_t_dic.get(device_h[:2]) + str(int(device_h[2:4],16))
    else:
        log = None
    return send_wait_response(dest=device_h, cmd=cmd_h_dic['query'], log=log, publish=publish)


def send_wait_response(dest, src=device_h_dic['wallpad']+'00', cmd=cmd_h_dic['state'], value='0'*16, log=None, check_ack=True, publish=True):
    #logging.debug('waiting for send_wait_response :'+dest)
    wait_target.put(dest)
    #logging.debug('entered send_wait_response :'+dest)
    ret =  { 'value':'0'*16, 'flag':False }

    if send(dest, src, cmd, value, log, check_ack) != False:
        try:
            ret = wait_q.get(True, 2)
            if publish==True:
                publish_status(ret)
        except queue.Empty:
            pass
    wait_target.get()
    #logging.debug('exiting send_wait_response :'+dest)
    return ret


#===== elevator call via TCP/IP =====

def call_elevator_tcpip():
    import socket
    sock = socket.socket()
    sock.settimeout(10)

    APT_SERVER = config.get('Elevator', 'tcpip_apt_server')
    APT_PORT = int(config.get('Elevator', 'tcpip_apt_port'))

    try:
        sock.connect((APT_SERVER, APT_PORT))
    except Exception as e:
        logging.error('Apartment server socket connection failure : {} | server {}, port {}'.format(e, APT_SERVER, APT_PORT))
        return False
    logging.info('Apartment server socket connected | server {}, port {}'.format(APT_SERVER, APT_PORT))

    try:
        sock.send(bytearray.fromhex(config.get('Elevator', 'tcpip_packet1')))
        rcv = sock.recv(512)
        logging.info('recv from apt server: '+''.join("%02x" % i for i in rcv) )
        time.sleep(0.1)
        sock.send(bytearray.fromhex(config.get('Elevator', 'tcpip_packet2')))
        rcv = sock.recv(512)
        logging.info('recv from apt server: '+''.join("%02x" % i for i in rcv) )
        sock.send(bytearray.fromhex(config.get('Elevator', 'tcpip_packet3')))
        for itr in range(100):
            rcv = sock.recv(512)
            if len(rcv) == 0:
                logging.info('apt server connection closed by peer')
                sock.close()
                return True
            rcv_hex = ''.join("%02x" % i for i in rcv) 
            logging.info('recv from apt server: '+rcv_hex )
            if rcv_hex == config.get('Elevator', 'tcpip_packet4'):
                logging.info('elevator arrived. sending last heartbeat' )
                break
        sock.send(bytearray.fromhex(config.get('Elevator', 'tcpip_packet2')))
        rcv = sock.recv(512)
        logging.info('recv from apt server: '+''.join("%02x" % i for i in rcv) )
        sock.close()
    except Exception as e:
        logging.error('Apartment server socket communication failure : {}'.format(e))
        return False

    return True


#===== parse MQTT --> send hex packet =====

def mqtt_on_message(mqttc, obj, msg):
    command = msg.payload.decode('ascii')
    topic_d = msg.topic.split('/')

    # do not process other than command topic
    if topic_d[-1] != 'command':
        return

    logging.info("[MQTT RECV] " + msg.topic + " " + str(msg.qos) + " " + str(msg.payload))

    # thermo heat/off : kocom/room/thermo/3/heat_mode/command
    if 'thermo' in topic_d and 'heat_mode' in topic_d:
        heatmode_dic = {'heat': '11', 'off': '01'} 

        dev_id = device_h_dic['thermo']+'{0:02x}'.format(int(topic_d[3]))
        q = query(dev_id)
        settemp_hex = q['value'][4:6] if q['flag']!=False else '14'
        value = heatmode_dic.get(command) + '00' + settemp_hex + '0000000000' 
        send_wait_response(dest=dev_id, value=value, log='thermo heatmode')

    # thermo set temp : kocom/room/thermo/3/set_temp/command
    elif 'thermo' in topic_d and 'set_temp' in topic_d:
        dev_id = device_h_dic['thermo']+'{0:02x}'.format(int(topic_d[3]))
        settemp_hex = '{0:02x}'.format(int(float(command)))

        value = '1100' + settemp_hex + '0000000000'
        send_wait_response(dest=dev_id, value=value, log='thermo settemp')

    # light on/off : kocom/livingroom/light/1/command
    elif 'light' in topic_d:
        dev_id = device_h_dic['light'] + room_h_dic.get(topic_d[1])
        value = query(dev_id)['value']
        onoff_hex = 'ff' if command == 'on' else '00'
        light_id = int(topic_d[3])

        # turn on/off multiple lights at once : e.g) kocom/livingroom/light/12/command
        while light_id > 0:
            n = light_id % 10
            value = value[:n*2-2]+ onoff_hex + value[n*2:]
            light_id = int(light_id/10)

        send_wait_response(dest=dev_id, value=value, log='light')

    # gas off : kocom/livingroom/gas/command
    elif 'gas' in topic_d:
        dev_id = device_h_dic['gas'] + room_h_dic.get(topic_d[1])
        if command == 'off':
            send_wait_response(dest=dev_id, cmd=cmd_h_dic.get(command), log='gas')
        else:
            logging.info('You can only turn off gas.')

    # elevator on/off : kocom/myhome/elevator/command
    elif 'elevator' in topic_d:
        dev_id = device_h_dic['elevator'] + room_h_dic.get(topic_d[1])
        state_on = json.dumps({'state': 'on'})
        state_off = json.dumps({'state': 'off'})
        if command == 'on':
            ret_elevator = None
            if config.get('Elevator', 'type', fallback='rs485') == 'rs485':
                ret_elevator = send(dest=device_h_dic['wallpad']+'00', src=dev_id, cmd=cmd_h_dic['on'], value='0'*16, log='elevator', check_ack=False)
            elif config.get('Elevator', 'type', fallback='rs485') == 'tcpip':
                ret_elevator = call_elevator_tcpip()

            if ret_elevator == False:
                logging.debug('elevator send failed')
                return
       
            threading.Thread(target=mqttc.publish, args=("kocom/myhome/elevator/state", state_on)).start()
            if config.get('Elevator', 'rs485_floor', fallback=None) == None:
                threading.Timer(5, mqttc.publish, args=("kocom/myhome/elevator/state", state_off)).start()
 
        elif command == 'off':
            threading.Thread(target=mqttc.publish, args=("kocom/myhome/elevator/state", state_off)).start()

    # kocom/livingroom/fan/command
    elif 'fan' in topic_d:
        dev_id = device_h_dic['fan'] + room_h_dic.get(topic_d[1])
        onoff_dic = {'off':'0000', 'on':'1101'}
        speed_dic = {'1':'40', '2':'80', '3':'c0'}
        if command == '0':
            command = 'off'
        if command in onoff_dic.keys(): # fan on off with previous speed 
            value = query(dev_id)['value']
            onoff = onoff_dic.get(command)
            speed = value[4:6]
        elif command in speed_dic.keys(): # fan on with specified speed
            onoff = onoff_dic['on'] 
            speed = speed_dic.get(command)

        value = onoff + speed + '0'*10
        send_wait_response(dest=dev_id, value=value, log='fan')


#===== parse hex packet --> publish MQTT =====

def publish_status(p):
    threading.Thread(target=packet_processor, args=(p,)).start()

def packet_processor(p):
    logtxt = ""
    if p['type']=='ack' and p['src']=='wallpad':  # ack from wallpad
    #if p['type']=='send' and p['dest']=='wallpad':  # response packet to wallpad
        if p['dest'] == 'thermo' and p['cmd']=='state':
        #if p['src'] == 'thermo' and p['cmd']=='state':
            state = thermo_parse(p['value'])
            logtxt='[MQTT publish|thermo] room{} data[{}]'.format(p['dest_subid'], state)
            mqttc.publish("kocom/room/thermo/" + p['dest_subid'] + "/state", json.dumps(state))
        elif p['dest'] == 'light' and p['cmd']=='state':
        #elif p['src'] == 'light' and p['cmd']=='state':
            state = light_parse(p['value'])
            logtxt='[MQTT publish|light] data[{}]'.format(state)
            mqttc.publish("kocom/livingroom/light/state", json.dumps(state))
        elif p['dest'] == 'fan' and p['cmd']=='state':
        #elif p['src'] == 'fan' and p['cmd']=='state':
            state = fan_parse(p['value'])
            logtxt='[MQTT publish|fan] data[{}]'.format(state)
            mqttc.publish("kocom/livingroom/fan/state", json.dumps(state))    
        elif p['dest'] == 'gas':
        #elif p['src'] == 'gas':
            state = {'state': p['cmd']}
            logtxt='[MQTT publish|gas] data[{}]'.format(state)
            mqttc.publish("kocom/livingroom/gas/state", json.dumps(state))
    elif p['type']=='send' and p['dest']=='elevator':
        floor = int(p['value'][2:4],16)
        rs485_floor = int(config.get('Elevator','rs485_floor', fallback=0))
        if rs485_floor != 0 :
            state = {'state': 'off' if rs485_floor==floor else 'on', 'floor': floor}
        else:
            state = {'state': 'off'}
        logtxt='[MQTT publish|elevator] data[{}]'.format(state)
        mqttc.publish("kocom/myhome/elevator/state", json.dumps(state))
        # aa5530bc0044000100010300000000000000350d0d

    if logtxt != "" and config.get('Log', 'show_mqtt_publish') == 'True':
        logging.info(logtxt)


#===== thread functions ===== 

def poll_state():
    global poll_timer
    poll_timer.cancel()

    dev_list = [x.strip() for x in config.get('Device','enabled').split(',')]
    no_polling_list = ['wallpad', 'elevator']

    #thread health check
    for thread_instance in thread_list:
        if thread_instance.is_alive() == False:
            logging.error('[THREAD] {} is not active. starting.'.format( thread_instance.name))
            thread_instance.start()

    for t in dev_list:
        dev = t.split('_')
        if dev[0] in no_polling_list:
            continue

        dev_id = device_h_dic.get(dev[0])
        if len(dev) > 1:
            sub_id = room_h_dic.get(dev[1])
        else:
            sub_id = '00'

        if dev_id != None and sub_id != None:
            if query(dev_id + sub_id, publish=True)['flag'] == False:
                break
            time.sleep(1)

    poll_timer.cancel()
    poll_timer = threading.Timer(polling_interval, poll_state)
    poll_timer.start()


def read_serial():
    global poll_timer
    buf = ''
    not_parsed_buf = ''
    while True:
        try:
            d = rs485.read()
            hex_d = '{0:02x}'.format(ord(d))

            buf += hex_d
            if buf[:len(header_h)] != header_h[:len(buf)]:
                not_parsed_buf += buf
                buf=''
                frame_start = not_parsed_buf.find(header_h, len(header_h))
                if frame_start < 0:
                    continue
                else:
                    not_parsed_buf = not_parsed_buf[:frame_start]
                    buf = not_parsed_buf[frame_start:]
            
            if not_parsed_buf != '':
                logging.info('[comm] not parsed '+not_parsed_buf)
                not_parsed_buf = ''


            if len(buf) == packet_size*2:
                chksum_calc = chksum(buf[len(header_h):chksum_position*2])
                chksum_buf = buf[chksum_position*2:chksum_position*2+2]
                if chksum_calc == chksum_buf and buf[-len(trailer_h):] == trailer_h:
                    if msg_q.full():
                        logging.error('msg_q is full. probably error occured while running listen_hexdata thread. please manually restart the program.')
                    msg_q.put(buf)  # valid packet
                    buf=''
                else:
                    logging.info("[comm] invalid packet {} expected checksum {}".format(buf, chksum_calc))
                    frame_start = buf.find(header_h, len(header_h))
                    # if there's header packet in the middle of invalid packet, re-parse from that posistion
                    if frame_start < 0:
                        not_parsed_buf += buf
                        buf=''
                    else:
                        not_parsed_buf += buf[:frame_start]
                        buf = buf[frame_start:]
        except Exception as ex:
            logging.error("*** Read error.[{}]".format(ex) )
            poll_timer.cancel()
            del cache_data[:]
            rs485.reconnect()
            poll_timer = threading.Timer(2, poll_state)
            poll_timer.start()


def listen_hexdata():
    while True:
        d = msg_q.get()

        if config.get('Log', 'show_recv_hex') == 'True':
            logging.info("[recv] " + d)
 
        p_ret = parse(d)

        # store recent packets in cache
        cache_data.insert(0, p_ret)
        if len(cache_data) > BUF_SIZE:
            del cache_data[-1]

        if p_ret['data_h'] in ack_data:
            ack_q.put(d)
            continue
 
        if wait_target.empty() == False:
            if p_ret['dest_h'] == wait_target.queue[0] and p_ret['type'] == 'ack':
            #if p_ret['src_h'] == wait_target.queue[0] and p_ret['type'] == 'send':
                if len(ack_data) != 0:
                    logging.info("[ACK] No ack received, but responce packet received before ACK. Assuming ACK OK")
                    ack_q.put(d)
                    time.sleep(0.5)
                wait_q.put(p_ret)
                continue
        publish_status(p_ret)


#========== Main ==========

if __name__ == "__main__":
    logging.basicConfig(format='%(levelname)s[%(asctime)s]:%(message)s ', level=logging.DEBUG)

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    if config.get('RS485', 'type') == 'serial':
        import serial
        rs485 = RS485Wrapper(serial_port = config.get('RS485', 'serial_port', fallback=None))
    elif config.get('RS485', 'type') == 'socket':
        import socket
        rs485 = RS485Wrapper(socket_server = config.get('RS485', 'socket_server'), socket_port = int(config.get('RS485', 'socket_port')))
    else:
        logging.error('[CONFIG] invalid type value in [RS485]: only "serial" or "socket" is allowed')
        exit(1)
    if rs485.connect() == False:
        exit(1)

    mqttc = init_mqttc()

    msg_q = queue.Queue(BUF_SIZE)
    ack_q = queue.Queue(1)
    ack_data = []
    wait_q = queue.Queue(1)
    wait_target = queue.Queue(1)
    send_lock = threading.Lock()
    poll_timer = threading.Timer(1, poll_state)

    cache_data = []

    thread_list = []
    thread_list.append(threading.Thread(target=read_serial, name='read_serial'))
    thread_list.append(threading.Thread(target=listen_hexdata, name='listen_hexdata'))
    for thread_instance in thread_list:
        thread_instance.start()

    poll_timer.start()
