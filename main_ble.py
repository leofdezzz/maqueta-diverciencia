"""
Aerogenerador flotante - control 4 cabrestantes via BLE.

Dispositivo BLE (Nordic UART Service):
    Nombre:    AeroBLE
    Servicio:  6E400001-B5A3-F393-E0A9-E50E24DCCA9E
    Char RX:   6E400002-B5A3-F393-E0A9-E50E24DCCA9E  (write)
    Char TX:   6E400003-B5A3-F393-E0A9-E50E24DCCA9E  (notify)

Protocolo JSON por linea ('\\n' termina mensaje):

  Web -> ESP32:
    {"cmd":"motor","name":"FL","action":"wind"}   (FL/FR/BL/BR/ALL, wind/release/stop)
    {"cmd":"move","x":50,"y":-30}                  mover a posicion (mm)
    {"cmd":"scan"}                                 lanza escaneo completo
    {"cmd":"zero"}                                 marca cero en posicion actual
    {"cmd":"stop"}                                 para todo y cancela movimiento
    {"cmd":"status"}                               pide estado inmediato
    {"cmd":"ping"}                                 keepalive

  ESP32 -> Web:
    {"ev":"ready"}
    {"ev":"pos","x":..,"y":..,"t":..,"c":{"FL":..,"FR":..,"BL":..,"BR":..},"tx":..,"ty":..}
    {"ev":"scan_start"} / {"ev":"scan_done","x":..,"y":..}
    {"ev":"zero"} / {"ev":"pong"} / {"ev":"error","msg":".."}

Seguridad:
  - Desconexion BLE -> parar todos los motores.
  - Cada comando motor tiene deadline 400ms; si no llega otro, se para solo.
  - Comando 'stop' cancela moves y scans en curso.
"""

from machine import Pin, PWM, ADC
import time
import math
import json
import bluetooth
import struct
from micropython import const

# ==================== CONFIG ====================
DEFAULT_CONFIG = {
    'box_x_mm': 400, 'box_y_mm': 200, 'box_z_mm': 300,
    'base_x_mm': 150, 'base_y_mm': 150,
    'margen_mm': 20,
    'diam_tambor_mm': 15.0, 'imanes_por_tambor': 2,
    'paso_scan_mm': 30, 'paso_joy_mm': 5,
    'pwm_duty': 700, 'pwm_duty_lento': 500,
    'ble_name': 'AeroBLE',
}


def load_config():
    try:
        with open('config.json') as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    except (OSError, ValueError):
        with open('config.json', 'w') as f:
            json.dump(DEFAULT_CONFIG, f)
        print('config.json creado por defecto.')
        return dict(DEFAULT_CONFIG)


CFG = load_config()

MM_POR_PULSO = math.pi * CFG['diam_tambor_mm'] / CFG['imanes_por_tambor']
TRAVEL_X_MAX = (CFG['box_x_mm'] - CFG['base_x_mm']) / 2 - CFG['margen_mm']
TRAVEL_Y_MAX = (CFG['box_y_mm'] - CFG['base_y_mm']) / 2 - CFG['margen_mm']

BOX_CORNERS = {
    'FL': (-CFG['box_x_mm']/2,  CFG['box_y_mm']/2, CFG['box_z_mm']),
    'FR': ( CFG['box_x_mm']/2,  CFG['box_y_mm']/2, CFG['box_z_mm']),
    'BL': (-CFG['box_x_mm']/2, -CFG['box_y_mm']/2, CFG['box_z_mm']),
    'BR': ( CFG['box_x_mm']/2, -CFG['box_y_mm']/2, CFG['box_z_mm']),
}
BASE_OFFSETS = {
    'FL': (-CFG['base_x_mm']/2,  CFG['base_y_mm']/2),
    'FR': ( CFG['base_x_mm']/2,  CFG['base_y_mm']/2),
    'BL': (-CFG['base_x_mm']/2, -CFG['base_y_mm']/2),
    'BR': ( CFG['base_x_mm']/2, -CFG['base_y_mm']/2),
}


def cable_length_mm(bx, by, corner):
    bc = BOX_CORNERS[corner]
    ox, oy = BASE_OFFSETS[corner]
    dx = (bx + ox) - bc[0]
    dy = (by + oy) - bc[1]
    dz = -bc[2]
    return math.sqrt(dx*dx + dy*dy + dz*dz)


# ==================== PINES ====================
MOTOR_FL = (14, 27, 26)
MOTOR_FR = (32, 33, 25)
MOTOR_BL = (13, 12, 15)
MOTOR_BR = (4, 16, 17)

HALL_FL_PIN, HALL_FR_PIN, HALL_BL_PIN, HALL_BR_PIN = 18, 19, 21, 22
JOY_X_PIN, JOY_Y_PIN = 36, 39
BTN_SCAN_PIN, BTN_TENSAR_PIN, BTN_DESTENSAR_PIN = 5, 2, 35
TURBINA_PIN = 34

PWM_FREQ = 1000
ESPERA_MEDIR_MS = 500
MUESTRAS_ADC = 20
JOY_DEADZONE = 600
JOY_CENTER = 2048
JOY_LOOP_MS = 30
LONG_PRESS_MS = 2500
TIMEOUT_MOVE_MS = 8000
WEB_PULSE_MS = 400
STATUS_INTERVAL_MS = 500


# ==================== MOTOR + HALL ====================
class Motor:
    WIND, RELEASE, IDLE = 1, -1, 0

    def __init__(self, pins, name):
        self.in1 = Pin(pins[0], Pin.OUT)
        self.in2 = Pin(pins[1], Pin.OUT)
        self.pwm = PWM(Pin(pins[2]), freq=PWM_FREQ, duty=0)
        self.name = name
        self.dir = Motor.IDLE
        self.pulses_move = 0
        self.web_deadline = 0

    def wind(self, duty):
        self.dir = Motor.WIND
        self.in1.value(1); self.in2.value(0)
        self.pwm.duty(duty)

    def release(self, duty):
        self.dir = Motor.RELEASE
        self.in1.value(0); self.in2.value(1)
        self.pwm.duty(duty)

    def stop(self):
        self.dir = Motor.IDLE
        self.in1.value(0); self.in2.value(0)
        self.pwm.duty(0)
        self.web_deadline = 0

    def on_pulse(self, pin):
        if self.dir != Motor.IDLE:
            self.pulses_move += 1


fl = Motor(MOTOR_FL, 'FL')
fr = Motor(MOTOR_FR, 'FR')
bl = Motor(MOTOR_BL, 'BL')
br = Motor(MOTOR_BR, 'BR')
MOTORES_DICT = {'FL': fl, 'FR': fr, 'BL': bl, 'BR': br}
MOTORES = tuple(MOTORES_DICT.values())


def _wire_hall(pin_num, motor):
    p = Pin(pin_num, Pin.IN, Pin.PULL_UP)
    p.irq(trigger=Pin.IRQ_FALLING, handler=motor.on_pulse)
    return p


_wire_hall(HALL_FL_PIN, fl)
_wire_hall(HALL_FR_PIN, fr)
_wire_hall(HALL_BL_PIN, bl)
_wire_hall(HALL_BR_PIN, br)

btn_scan = Pin(BTN_SCAN_PIN, Pin.IN, Pin.PULL_UP)
btn_tensar = Pin(BTN_TENSAR_PIN, Pin.IN, Pin.PULL_UP)
btn_destensar = Pin(BTN_DESTENSAR_PIN, Pin.IN)

joy_x = ADC(Pin(JOY_X_PIN)); joy_x.atten(ADC.ATTN_11DB)
joy_y = ADC(Pin(JOY_Y_PIN)); joy_y.atten(ADC.ATTN_11DB)
turbina = ADC(Pin(TURBINA_PIN)); turbina.atten(ADC.ATTN_11DB)


# ==================== ESTADO ====================
base_pos = [0.0, 0.0]
cable_len = {k: cable_length_mm(0, 0, k) for k in MOTORES_DICT}
_cancel = False


def parar_todo():
    for m in MOTORES:
        m.stop()


def set_zero():
    base_pos[0] = 0.0
    base_pos[1] = 0.0
    for k in cable_len:
        cable_len[k] = cable_length_mm(0, 0, k)
    print('>>> CERO marcado.')


# ==================== MOVIMIENTO IK ====================
def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def mover_a(target_x, target_y, duty=None):
    global _cancel
    _cancel = False
    if duty is None:
        duty = CFG['pwm_duty']
    tx = clamp(target_x, -TRAVEL_X_MAX, TRAVEL_X_MAX)
    ty = clamp(target_y, -TRAVEL_Y_MAX, TRAVEL_Y_MAX)
    new_len = {k: cable_length_mm(tx, ty, k) for k in MOTORES_DICT}
    delta_mm = {k: new_len[k] - cable_len[k] for k in MOTORES_DICT}
    target_pulsos = {k: int(round(abs(delta_mm[k]) / MM_POR_PULSO)) for k in MOTORES_DICT}
    if all(v == 0 for v in target_pulsos.values()):
        base_pos[0] = tx; base_pos[1] = ty
        return
    for k, m in MOTORES_DICT.items():
        m.pulses_move = 0
        if target_pulsos[k] == 0:
            m.stop()
        elif delta_mm[k] > 0:
            m.release(duty)
        else:
            m.wind(duty)
    t0 = time.ticks_ms()
    while True:
        if _cancel:
            parar_todo()
            return
        listos = True
        for k, m in MOTORES_DICT.items():
            if target_pulsos[k] == 0:
                continue
            if m.pulses_move >= target_pulsos[k]:
                if m.dir != Motor.IDLE:
                    m.stop()
            else:
                listos = False
        if listos:
            break
        if time.ticks_diff(time.ticks_ms(), t0) > TIMEOUT_MOVE_MS:
            print('!! timeout mover_a')
            parar_todo()
            break
        time.sleep_ms(2)
    for k in cable_len:
        cable_len[k] = new_len[k]
    base_pos[0] = tx
    base_pos[1] = ty


def tensar_todos_mantenido(boton):
    for m in MOTORES: m.wind(CFG['pwm_duty_lento'])
    while boton.value() == 0:
        time.sleep_ms(20)
    parar_todo()


def destensar_todos_mantenido(boton):
    for m in MOTORES: m.release(CFG['pwm_duty_lento'])
    while boton.value() == 0:
        time.sleep_ms(20)
    parar_todo()


# ==================== JOYSTICK ====================
def joystick_step():
    x = joy_x.read() - JOY_CENTER
    y = joy_y.read() - JOY_CENTER
    dx_mm = 0.0; dy_mm = 0.0
    paso = CFG['paso_joy_mm']
    if abs(x) > abs(y):
        if abs(x) > JOY_DEADZONE:
            dx_mm = paso if x > 0 else -paso
    else:
        if abs(y) > JOY_DEADZONE:
            dy_mm = paso if y > 0 else -paso
    if dx_mm or dy_mm:
        mover_a(base_pos[0] + dx_mm, base_pos[1] + dy_mm,
                duty=CFG['pwm_duty_lento'])


# ==================== TURBINA / ESCANEO ====================
def leer_turbina():
    time.sleep_ms(ESPERA_MEDIR_MS)
    total = 0
    for _ in range(MUESTRAS_ADC):
        total += turbina.read()
        time.sleep_ms(5)
    return total / MUESTRAS_ADC


def escanear_eje(eje):
    paso = CFG['paso_scan_mm']
    rango_max = TRAVEL_X_MAX if eje == 'x' else TRAVEL_Y_MAX
    n_pasos = int(rango_max / paso)
    if eje == 'x':
        mover_a(-n_pasos * paso, base_pos[1])
    else:
        mover_a(base_pos[0], -n_pasos * paso)
    if _cancel: return None, 0
    mejor = (base_pos[0], base_pos[1])
    mejor_v = leer_turbina()
    for i in range(1, 2 * n_pasos + 1):
        if _cancel: return None, 0
        if eje == 'x':
            mover_a(-n_pasos * paso + i * paso, base_pos[1])
        else:
            mover_a(base_pos[0], -n_pasos * paso + i * paso)
        v = leer_turbina()
        if v > mejor_v:
            mejor_v = v; mejor = (base_pos[0], base_pos[1])
    mover_a(mejor[0], mejor[1])
    return mejor, mejor_v


def rutina_escaneo():
    escanear_eje('x')
    if _cancel: return
    escanear_eje('y')


# ==================== DEADLINES motor web ====================
def web_pulse_motor(name, action):
    name = name.upper()
    if name not in MOTORES_DICT:
        return False
    m = MOTORES_DICT[name]
    if action == 'wind':
        m.wind(CFG['pwm_duty_lento'])
        m.web_deadline = time.ticks_add(time.ticks_ms(), WEB_PULSE_MS)
    elif action == 'release':
        m.release(CFG['pwm_duty_lento'])
        m.web_deadline = time.ticks_add(time.ticks_ms(), WEB_PULSE_MS)
    elif action == 'stop':
        m.stop()
    else:
        return False
    return True


def check_web_deadlines():
    now = time.ticks_ms()
    for m in MOTORES:
        if m.web_deadline != 0 and time.ticks_diff(now, m.web_deadline) >= 0:
            m.stop()


# ==================== BLE (Nordic UART Service) ====================
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_MTU_EXCHANGED = const(21)

_UART_UUID = bluetooth.UUID('6E400001-B5A3-F393-E0A9-E50E24DCCA9E')
_UART_TX = (bluetooth.UUID('6E400003-B5A3-F393-E0A9-E50E24DCCA9E'),
            bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY,)
_UART_RX = (bluetooth.UUID('6E400002-B5A3-F393-E0A9-E50E24DCCA9E'),
            bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE,)
_UART_SERVICE = (_UART_UUID, (_UART_TX, _UART_RX),)

_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)
_ADV_TYPE_UUID128_COMPLETE = const(0x07)


def _adv_payload(name, services):
    payload = bytearray()
    def _add(t, v):
        payload.extend(struct.pack('BB', len(v) + 1, t))
        payload.extend(v)
    _add(_ADV_TYPE_FLAGS, struct.pack('B', 0x06))
    if name:
        _add(_ADV_TYPE_NAME, name.encode())
    for u in services:
        b = bytes(u)
        if len(b) == 16:
            _add(_ADV_TYPE_UUID128_COMPLETE, b)
    return payload


class BLEUart:
    def __init__(self, name):
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        try: self._ble.config(gap_name=name)
        except Exception: pass
        try: self._ble.config(mtu=200)
        except Exception: pass
        self._ble.irq(self._irq)
        ((self._tx_h, self._rx_h),) = self._ble.gatts_register_services((_UART_SERVICE,))
        try: self._ble.gatts_set_buffer(self._rx_h, 256, True)
        except Exception: pass
        self._connections = set()
        self._mtu = 23
        self._on_rx = None
        self._payload = _adv_payload(name, [_UART_UUID])
        self._advertise()
        print('BLE advertising como %s' % name)

    def _advertise(self, interval_us=500000):
        try:
            self._ble.gap_advertise(interval_us, adv_data=self._payload)
        except Exception as e:
            print('adv err:', e)

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn, _, _ = data
            self._connections.add(conn)
            print('BLE conectado', conn)
        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn, _, _ = data
            self._connections.discard(conn)
            print('BLE desconectado', conn)
            parar_todo()
            self._advertise()
        elif event == _IRQ_GATTS_WRITE:
            conn, vh = data
            if vh == self._rx_h:
                buf = self._ble.gatts_read(self._rx_h)
                if self._on_rx:
                    self._on_rx(buf)
        elif event == _IRQ_MTU_EXCHANGED:
            conn, mtu = data
            self._mtu = mtu
            print('MTU=%d' % mtu)

    def on_rx(self, cb):
        self._on_rx = cb

    def is_connected(self):
        return len(self._connections) > 0

    def send(self, data):
        if not self._connections:
            return
        if isinstance(data, str):
            data = data.encode()
        if not data.endswith(b'\n'):
            data = data + b'\n'
        chunk = max(20, self._mtu - 3)
        for i in range(0, len(data), chunk):
            part = data[i:i+chunk]
            for c in list(self._connections):
                try:
                    self._ble.gatts_notify(c, self._tx_h, part)
                except Exception as e:
                    print('notify err:', e)


# ==================== COMANDOS BLE ====================
_rx_buffer = bytearray()
_ble = None


def ble_send(obj):
    if _ble is None:
        return
    try:
        _ble.send(json.dumps(obj))
    except Exception as e:
        print('send err:', e)


def status_dict():
    return {
        'ev':'pos',
        'x': round(base_pos[0], 1),
        'y': round(base_pos[1], 1),
        't': turbina.read(),
        'c': {k: int(v) for k, v in cable_len.items()},
        'tx': round(TRAVEL_X_MAX, 0),
        'ty': round(TRAVEL_Y_MAX, 0),
    }


def on_ble_data(data):
    _rx_buffer.extend(data)
    while True:
        nl = _rx_buffer.find(b'\n')
        if nl < 0:
            if len(_rx_buffer) > 0 and _rx_buffer.endswith(b'}'):
                line = bytes(_rx_buffer)
                del _rx_buffer[:]
                procesar_comando(line)
            break
        line = bytes(_rx_buffer[:nl])
        del _rx_buffer[:nl+1]
        procesar_comando(line)


def procesar_comando(line):
    global _cancel
    line = line.strip()
    if not line:
        return
    try:
        obj = json.loads(line)
    except Exception:
        ble_send({'ev':'error','msg':'json'})
        return
    cmd = obj.get('cmd')
    try:
        if cmd == 'motor':
            name = obj.get('name','').upper()
            action = obj.get('action','')
            if name == 'ALL':
                for k in MOTORES_DICT:
                    web_pulse_motor(k, action)
            else:
                web_pulse_motor(name, action)
        elif cmd == 'move':
            x = float(obj.get('x', base_pos[0]))
            y = float(obj.get('y', base_pos[1]))
            mover_a(x, y)
            ble_send(status_dict())
        elif cmd == 'scan':
            ble_send({'ev':'scan_start'})
            rutina_escaneo()
            if _cancel:
                ble_send({'ev':'error','msg':'cancelado'})
            else:
                ble_send({'ev':'scan_done','x':base_pos[0],'y':base_pos[1]})
        elif cmd == 'zero':
            set_zero()
            ble_send({'ev':'zero'})
            ble_send(status_dict())
        elif cmd == 'stop':
            _cancel = True
            parar_todo()
        elif cmd == 'status':
            ble_send(status_dict())
        elif cmd == 'ping':
            ble_send({'ev':'pong'})
        else:
            ble_send({'ev':'error','msg':'cmd desconocido'})
    except Exception as e:
        print('cmd err:', e)
        parar_todo()
        ble_send({'ev':'error','msg':str(e)})


# ==================== BOTONES ====================
def leer_pulsacion(boton):
    t0 = time.ticks_ms()
    es_largo = False
    while boton.value() == 0:
        if not es_largo and time.ticks_diff(time.ticks_ms(), t0) > LONG_PRESS_MS:
            es_largo = True
        time.sleep_ms(20)
    return 'long' if es_largo else 'short'


# ==================== MAIN ====================
def imprimir_config():
    print('=== CONFIG ===')
    print('  caja %dx%dx%d  base %dx%d' %
          (CFG['box_x_mm'], CFG['box_y_mm'], CFG['box_z_mm'],
           CFG['base_x_mm'], CFG['base_y_mm']))
    print('  recorrido +-%.1fmm X / +-%.1fmm Y' % (TRAVEL_X_MAX, TRAVEL_Y_MAX))


def main():
    global _ble
    parar_todo()
    time.sleep_ms(100)
    print('=== Aerogenerador flotante (BLE) ===')
    imprimir_config()
    _ble = BLEUart(CFG['ble_name'])
    _ble.on_rx(on_ble_data)
    ble_send({'ev':'ready'})
    print('joystick + botones fisicos activos.')

    last_status = time.ticks_ms()

    while True:
        check_web_deadlines()

        if btn_tensar.value() == 0:
            tensar_todos_mantenido(btn_tensar); continue
        if btn_destensar.value() == 0:
            destensar_todos_mantenido(btn_destensar); continue
        if btn_scan.value() == 0:
            ev = leer_pulsacion(btn_scan)
            if ev == 'long':
                set_zero()
                ble_send({'ev':'zero'})
            else:
                try:
                    ble_send({'ev':'scan_start'})
                    rutina_escaneo()
                    ble_send({'ev':'scan_done','x':base_pos[0],'y':base_pos[1]})
                except Exception as e:
                    print('!! err:', e); parar_todo()
            continue

        if all(m.web_deadline == 0 for m in MOTORES):
            joystick_step()

        now = time.ticks_ms()
        if time.ticks_diff(now, last_status) >= STATUS_INTERVAL_MS:
            last_status = now
            if _ble.is_connected():
                ble_send(status_dict())

        time.sleep_ms(JOY_LOOP_MS)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        parar_todo(); print('parado')
    except Exception as e:
        parar_todo(); print('FATAL:', e); raise
