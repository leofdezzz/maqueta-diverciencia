"""
main_microbit.py - Adaptacion para BBC micro:bit v2 (MicroPython).

    ESTE ARCHIVO ES UN PUERTO LIMITADO DE main.py (ESP32).
    Se recomienda FUERTEMENTE usar el ESP32 original: mas rapido,
    mas RAM, soporte BLE nativo, y todas las features funcionan sin
    sacrificios. Ver INFORME_MICROBIT.md para detalles.

===========================================================================
ARQUITECTURA
===========================================================================

Protocolo JSON por linea sobre UART. La web (alojada en GitHub Pages o
similar) se conecta por UNO de estos transportes:

    [A] USB serial  -> Web Serial API   (Chrome/Edge, PC tethered)
    [B] IoTBit BLE  -> Web Bluetooth    (modulo AI-WB2 en P8/P12, via
                                         AT commands; requiere setup extra)

El host envia comandos como:
    {"cmd":"motor","name":"FL","action":"wind"}
    {"cmd":"move","x":50,"y":-30}
    {"cmd":"scan"} / {"cmd":"zero"} / {"cmd":"stop"}

El micro:bit responde periodicamente:
    {"pos":[x,y],"turbina":n}
    {"event":"ready","travel":[x_max,y_max]}
    {"event":"scan_done","pos":[x,y]}

===========================================================================
LIMITACIONES RESPECTO AL ESP32
===========================================================================

1. SIN PWM. Los L298N llevan EN puenteado a HIGH con el jumper del
   modulo -> los 4 motores solo van a velocidad maxima. No hay duty lento
   para joystick/tensar.

2. SIN joystick, sin botones fisicos. Todo se controla via protocolo JSON
   desde el host (web).

3. Hall sensors por POLLING en el main loop (MicroPython en micro:bit tiene
   soporte IRQ GPIO muy limitado). A 22 RPM con 2 imanes = ~44 pulsos/min
   por motor = 0.7 pulsos/seg -> el polling a 200 Hz los captura sin
   problema. Si subes mucho la velocidad, puede perder pulsos.

4. Sin `config.json` en flash (micro:bit MicroPython no tiene filesystem
   para escritura facil). Toda la config va hardcoded aqui abajo.

5. Pines P3-P10 comparten con matriz LED -> `display.off()` obligatorio.
===========================================================================
"""

from microbit import *
import utime
import math

try:
    import json
except ImportError:
    import ujson as json

display.off()   # libera P3-P10 como GPIO

# ==================== CONFIG HARDCODED ====================
CFG = {
    'box_x_mm': 400, 'box_y_mm': 200, 'box_z_mm': 300,
    'base_x_mm': 150, 'base_y_mm': 150,
    'margen_mm': 20,
    'diam_tambor_mm': 15.0, 'imanes_por_tambor': 2,
    'paso_scan_mm': 30,
}

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


# ==================== PINADO micro:bit v2 ====================
# L298N con EN puenteado a HIGH (jumper del modulo). Cada motor = 2 pines.
# Motor FL: P8, P12     (libres)
# Motor FR: P13, P14    (libres)
# Motor BL: P15, P16    (libres)
# Motor BR: P3, P4      (requieren display.off())
# Hall FL/FR/BL/BR: P6, P7, P9, P10  (requieren display.off())
# Turbina ADC: P2

MOTOR_PINS = {
    'FL': (pin8,  pin12),
    'FR': (pin13, pin14),
    'BL': (pin15, pin16),
    'BR': (pin3,  pin4),
}
HALL_PINS = {
    'FL': pin6,
    'FR': pin7,
    'BL': pin9,
    'BR': pin10,
}
TURBINA_PIN = pin2

# UART:
#   [A] USB serial (por defecto): uart.init(115200) y ya.
#   [B] IoTBit BLE: uart.init(115200, tx=pin8, rx=pin12) -> pero P8/P12
#       YA ESTAN OCUPADOS POR MOTOR FL en este mapeo. Si quieres IoTBit,
#       reasigna Motor FL a otros pines libres (P1 y pin0 por ejemplo)
#       y descomenta la linea de init con pines. Ademas tendras que
#       enviar los AT+BLE* de configuracion antes del main loop.
uart.init(baudrate=115200)


# ==================== MOTOR (sin PWM, solo direccion) ====================
class Motor:
    IDLE, WIND, RELEASE = 0, 1, -1

    def __init__(self, in1, in2, name):
        self.in1 = in1
        self.in2 = in2
        self.name = name
        self.dir = Motor.IDLE
        self.pulses_move = 0
        self.deadline = 0
        in1.write_digital(0)
        in2.write_digital(0)

    def wind(self):
        self.dir = Motor.WIND
        self.in1.write_digital(1)
        self.in2.write_digital(0)

    def release(self):
        self.dir = Motor.RELEASE
        self.in1.write_digital(0)
        self.in2.write_digital(1)

    def stop(self):
        self.dir = Motor.IDLE
        self.in1.write_digital(0)
        self.in2.write_digital(0)
        self.deadline = 0


MOTORES = {}
for _n, (_a, _b) in MOTOR_PINS.items():
    MOTORES[_n] = Motor(_a, _b, _n)

# Hall: estado previo para detectar flanco descendente por polling
_hall_prev = {k: 1 for k in HALL_PINS}


# ==================== ESTADO ====================
base_pos = [0.0, 0.0]
cable_len = {k: cable_length_mm(0, 0, k) for k in MOTORES}


def parar_todo():
    for m in MOTORES.values():
        m.stop()


def set_zero():
    base_pos[0] = 0.0
    base_pos[1] = 0.0
    for k in cable_len:
        cable_len[k] = cable_length_mm(0, 0, k)


def leer_turbina():
    # promediado corto para reducir ruido
    s = 0
    for _ in range(12):
        s += TURBINA_PIN.read_analog()
        utime.sleep_ms(4)
    return s // 12


def poll_halls():
    """Detecta flancos descendentes en los 4 Hall y acumula pulsos."""
    for k, p in HALL_PINS.items():
        cur = p.read_digital()
        if _hall_prev[k] == 1 and cur == 0:
            m = MOTORES[k]
            if m.dir != Motor.IDLE:
                m.pulses_move += 1
        _hall_prev[k] = cur


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ==================== MOVIMIENTO IK ====================
MOVE_TIMEOUT_MS = 15000


def mover_a(tx, ty):
    tx = clamp(tx, -TRAVEL_X_MAX, TRAVEL_X_MAX)
    ty = clamp(ty, -TRAVEL_Y_MAX, TRAVEL_Y_MAX)
    new_len = {k: cable_length_mm(tx, ty, k) for k in MOTORES}
    delta = {k: new_len[k] - cable_len[k] for k in MOTORES}
    target_p = {k: int(round(abs(delta[k]) / MM_POR_PULSO)) for k in MOTORES}

    if all(v == 0 for v in target_p.values()):
        base_pos[0] = tx; base_pos[1] = ty
        return

    for k, m in MOTORES.items():
        m.pulses_move = 0
        if target_p[k] == 0:
            m.stop()
        elif delta[k] > 0:
            m.release()
        else:
            m.wind()

    t0 = utime.ticks_ms()
    while True:
        poll_halls()
        listos = True
        for k, m in MOTORES.items():
            if target_p[k] == 0:
                continue
            if m.pulses_move >= target_p[k]:
                if m.dir != Motor.IDLE:
                    m.stop()
            else:
                listos = False
        if listos:
            break
        if utime.ticks_diff(utime.ticks_ms(), t0) > MOVE_TIMEOUT_MS:
            parar_todo()
            enviar({'event': 'log', 'msg': 'timeout move'})
            break
        utime.sleep_ms(2)

    for k in cable_len:
        cable_len[k] = new_len[k]
    base_pos[0] = tx
    base_pos[1] = ty


def escanear_eje(eje):
    paso = CFG['paso_scan_mm']
    rmax = TRAVEL_X_MAX if eje == 'x' else TRAVEL_Y_MAX
    n = int(rmax / paso)

    if eje == 'x':
        mover_a(-n * paso, base_pos[1])
    else:
        mover_a(base_pos[0], -n * paso)

    mejor = (base_pos[0], base_pos[1])
    mejor_v = leer_turbina()

    for i in range(1, 2 * n + 1):
        if eje == 'x':
            mover_a(-n * paso + i * paso, base_pos[1])
        else:
            mover_a(base_pos[0], -n * paso + i * paso)
        v = leer_turbina()
        enviar({'event': 'sample', 'pos': [round(base_pos[0], 1),
                                           round(base_pos[1], 1)], 'v': v})
        if v > mejor_v:
            mejor_v = v
            mejor = (base_pos[0], base_pos[1])

    mover_a(mejor[0], mejor[1])
    return mejor, mejor_v


def rutina_escaneo():
    enviar({'event': 'log', 'msg': 'scan X'})
    escanear_eje('x')
    enviar({'event': 'log', 'msg': 'scan Y'})
    escanear_eje('y')
    enviar({'event': 'scan_done',
            'pos': [round(base_pos[0], 1), round(base_pos[1], 1)]})


# ==================== PROTOCOLO UART / JSON ====================
PULSE_MS = 400       # cada comando motor mantiene activo este tiempo
STATUS_MS = 500      # frecuencia de envio de estado


def enviar(obj):
    try:
        uart.write(json.dumps(obj) + '\n')
    except Exception:
        pass


def pulse_motor(name, action):
    if name == 'ALL':
        keys = list(MOTORES.keys())
    elif name in MOTORES:
        keys = [name]
    else:
        return False
    for k in keys:
        m = MOTORES[k]
        if action == 'wind':
            m.wind()
            m.deadline = utime.ticks_add(utime.ticks_ms(), PULSE_MS)
        elif action == 'release':
            m.release()
            m.deadline = utime.ticks_add(utime.ticks_ms(), PULSE_MS)
        elif action == 'stop':
            m.stop()
        else:
            return False
    return True


def check_deadlines():
    now = utime.ticks_ms()
    for m in MOTORES.values():
        if m.deadline != 0 and utime.ticks_diff(now, m.deadline) >= 0:
            m.stop()


def procesar_comando(line):
    try:
        obj = json.loads(line)
    except Exception:
        return
    cmd = obj.get('cmd', '')
    if cmd == 'motor':
        pulse_motor(str(obj.get('name', '')).upper(), obj.get('action', ''))
    elif cmd == 'move':
        try:
            x = float(obj.get('x', base_pos[0]))
            y = float(obj.get('y', base_pos[1]))
            mover_a(x, y)
        except Exception:
            pass
    elif cmd == 'scan':
        rutina_escaneo()
    elif cmd == 'zero':
        set_zero()
        enviar({'event': 'zero'})
    elif cmd == 'stop':
        parar_todo()


# ==================== MAIN LOOP ====================
_rx_buf = b''
_last_status = 0


def main():
    global _rx_buf, _last_status
    parar_todo()
    enviar({'event': 'ready',
            'travel': [round(TRAVEL_X_MAX, 1), round(TRAVEL_Y_MAX, 1)]})

    while True:
        poll_halls()
        check_deadlines()

        # leer UART no-bloqueante
        n = uart.any()
        if n:
            chunk = uart.read(n)
            if chunk:
                _rx_buf += chunk
                while b'\n' in _rx_buf:
                    line, _rx_buf = _rx_buf.split(b'\n', 1)
                    try:
                        procesar_comando(line.decode('utf-8').strip())
                    except Exception:
                        pass
                # proteccion: no dejar el buffer creciendo sin limite
                if len(_rx_buf) > 512:
                    _rx_buf = b''

        # status periodico
        now = utime.ticks_ms()
        if utime.ticks_diff(now, _last_status) >= STATUS_MS:
            _last_status = now
            enviar({
                'pos': [round(base_pos[0], 1), round(base_pos[1], 1)],
                'turbina': TURBINA_PIN.read_analog(),
            })

        utime.sleep_ms(5)


try:
    main()
except Exception as e:
    parar_todo()
    enviar({'event': 'fatal', 'err': str(e)})
    raise
