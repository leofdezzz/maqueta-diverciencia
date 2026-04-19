"""
Aerogenerador flotante - control 4 cabrestantes con joystick + escaneo.

Dimensiones se configuran en config.json (se crea al primer arranque).
Movimiento por cinematica inversa: cada motor calcula su longitud de cable
segun la geometria real caja/base -> adaptado a cajas rectangulares.

Flujo:
    1. Edita config.json con las medidas reales de tu caja y base.
    2. Enciende. Centra la base a mano con joystick + TENSAR/DESTENSAR.
    3. BTN_SCAN largo (3s) -> marca cero (centro geometrico).
    4. BTN_SCAN corto -> escaneo X+Y, se queda en optimo.
"""

from machine import Pin, PWM, ADC
import time
import math
import json

# ==================== CONFIG ====================
DEFAULT_CONFIG = {
    # --- Dimensiones fisicas (mm) ---
    'box_x_mm': 400,          # largo caja (eje X, el mas grande)
    'box_y_mm': 200,          # ancho caja (eje Y)
    'box_z_mm': 300,          # altura: distancia vertical motor <-> agua
    'base_x_mm': 150,         # largo base aerogenerador
    'base_y_mm': 150,         # ancho base
    'margen_mm': 20,          # margen de seguridad al borde interior
    # --- Cabrestante / Hall ---
    'diam_tambor_mm': 15.0,   # diametro del tambor con cable enrollado
    'imanes_por_tambor': 2,   # numero de imanes => pulsos por vuelta
    # --- Movimiento ---
    'paso_scan_mm': 30,       # paso del barrido automatico
    'paso_joy_mm': 5,         # paso por tick de joystick
    'pwm_duty': 700,          # 0-1023 velocidad motores
    'pwm_duty_lento': 500,    # duty para joystick y tensar/destensar
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
        print('config.json creado con valores por defecto. Editalo y reinicia.')
        return dict(DEFAULT_CONFIG)


CFG = load_config()

# ==================== DERIVADAS ====================
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


def cable_length_mm(base_x, base_y, corner):
    """Distancia desde esquina superior de caja a esquina correspondiente de la base."""
    bc = BOX_CORNERS[corner]
    ox, oy = BASE_OFFSETS[corner]
    dx = (base_x + ox) - bc[0]
    dy = (base_y + oy) - bc[1]
    dz = 0 - bc[2]
    return math.sqrt(dx*dx + dy*dy + dz*dz)


# ==================== PINES ====================
MOTOR_FL = (14, 27, 26)
MOTOR_FR = (32, 33, 25)
MOTOR_BL = (13, 12, 15)
MOTOR_BR = (4, 16, 17)

HALL_FL_PIN = 18
HALL_FR_PIN = 19
HALL_BL_PIN = 21
HALL_BR_PIN = 22

JOY_X_PIN = 36
JOY_Y_PIN = 39

BTN_SCAN_PIN = 5
BTN_TENSAR_PIN = 2
BTN_DESTENSAR_PIN = 35   # pull-up externo 10k

TURBINA_PIN = 34

PWM_FREQ = 1000
ESPERA_MEDIR_MS = 500
MUESTRAS_ADC = 20
JOY_DEADZONE = 600
JOY_CENTER = 2048
JOY_LOOP_MS = 40
LONG_PRESS_MS = 2500
TIMEOUT_MOVE_MS = 8000


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


hall_fl = _wire_hall(HALL_FL_PIN, fl)
hall_fr = _wire_hall(HALL_FR_PIN, fr)
hall_bl = _wire_hall(HALL_BL_PIN, bl)
hall_br = _wire_hall(HALL_BR_PIN, br)

# ==================== ENTRADAS ====================
btn_scan = Pin(BTN_SCAN_PIN, Pin.IN, Pin.PULL_UP)
btn_tensar = Pin(BTN_TENSAR_PIN, Pin.IN, Pin.PULL_UP)
btn_destensar = Pin(BTN_DESTENSAR_PIN, Pin.IN)

joy_x = ADC(Pin(JOY_X_PIN)); joy_x.atten(ADC.ATTN_11DB)
joy_y = ADC(Pin(JOY_Y_PIN)); joy_y.atten(ADC.ATTN_11DB)
turbina = ADC(Pin(TURBINA_PIN)); turbina.atten(ADC.ATTN_11DB)


# ==================== ESTADO ====================
# Posicion absoluta de la base (mm desde cero manual = centro geometrico).
base_pos = [0.0, 0.0]

# Longitudes de cable actuales (se inicializan al marcar cero).
cable_len = {k: cable_length_mm(0, 0, k) for k in MOTORES_DICT}


def parar_todo():
    for m in MOTORES:
        m.stop()


def set_zero():
    base_pos[0] = 0.0
    base_pos[1] = 0.0
    for k in cable_len:
        cable_len[k] = cable_length_mm(0, 0, k)
    print('>>> CERO marcado (centro geometrico).')
    print('    cables: ' + ', '.join('%s=%.1f' % (k, v) for k, v in cable_len.items()))


def estado():
    print('pos=(%.1f, %.1f) mm  cables: %s  turbina=%d' %
          (base_pos[0], base_pos[1],
           ' '.join('%s=%.0f' % (k, v) for k, v in cable_len.items()),
           turbina.read()))


# ==================== MOVIMIENTO IK ====================
def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def mover_a(target_x, target_y, duty=None):
    """
    Cinematica inversa: lleva la base a (target_x, target_y) mm.
    Cada motor ajusta su cable segun longitud geometrica calculada.
    """
    if duty is None:
        duty = CFG['pwm_duty']

    tx = clamp(target_x, -TRAVEL_X_MAX, TRAVEL_X_MAX)
    ty = clamp(target_y, -TRAVEL_Y_MAX, TRAVEL_Y_MAX)

    new_len = {k: cable_length_mm(tx, ty, k) for k in MOTORES_DICT}
    delta_mm = {k: new_len[k] - cable_len[k] for k in MOTORES_DICT}
    target_pulsos = {k: int(round(abs(delta_mm[k]) / MM_POR_PULSO)) for k in MOTORES_DICT}

    # si ningun motor necesita moverse, salir
    if all(v == 0 for v in target_pulsos.values()):
        base_pos[0] = tx; base_pos[1] = ty
        return

    # arrancar motores con direccion adecuada
    for k, m in MOTORES_DICT.items():
        m.pulses_move = 0
        if target_pulsos[k] == 0:
            m.stop()
        elif delta_mm[k] > 0:
            m.release(duty)    # cable debe alargarse
        else:
            m.wind(duty)       # cable debe acortarse

    # parar cada motor en cuanto alcance su objetivo
    t0 = time.ticks_ms()
    while True:
        todos_listos = True
        for k, m in MOTORES_DICT.items():
            if target_pulsos[k] == 0:
                continue
            if m.pulses_move >= target_pulsos[k]:
                if m.dir != Motor.IDLE:
                    m.stop()
            else:
                todos_listos = False
        if todos_listos:
            break
        if time.ticks_diff(time.ticks_ms(), t0) > TIMEOUT_MOVE_MS:
            print('!! timeout en mover_a(%.1f, %.1f)' % (tx, ty))
            parar_todo()
            break
        time.sleep_ms(2)

    # actualizar estado
    for k in cable_len:
        cable_len[k] = new_len[k]
    base_pos[0] = tx
    base_pos[1] = ty


def tensar_mantenido(boton):
    for m in MOTORES: m.wind(CFG['pwm_duty_lento'])
    while boton.value() == 0:
        time.sleep_ms(20)
    parar_todo()
    # tras tensar manualmente, las longitudes calculadas estan desfasadas.
    # mejor marcar cero de nuevo si se usa para calibrar.


def destensar_mantenido(boton):
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
        estado()


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
    print('--- escaneo %s: +-%d pasos de %.1f mm (rango +-%.1f mm) ---' %
          (eje.upper(), n_pasos, paso, rango_max))

    # ir al extremo negativo
    if eje == 'x':
        mover_a(-n_pasos * paso, base_pos[1])
    else:
        mover_a(base_pos[0], -n_pasos * paso)

    mejor_pos = (base_pos[0], base_pos[1])
    mejor_val = leer_turbina()
    print('  (%.1f, %.1f) -> %.1f' % (mejor_pos[0], mejor_pos[1], mejor_val))

    for i in range(1, 2 * n_pasos + 1):
        if eje == 'x':
            mover_a(-n_pasos * paso + i * paso, base_pos[1])
        else:
            mover_a(base_pos[0], -n_pasos * paso + i * paso)
        v = leer_turbina()
        print('  (%.1f, %.1f) -> %.1f' % (base_pos[0], base_pos[1], v))
        if v > mejor_val:
            mejor_val = v
            mejor_pos = (base_pos[0], base_pos[1])

    mover_a(mejor_pos[0], mejor_pos[1])
    print('optimo eje %s: %.1f mm (valor %.1f)' %
          (eje.upper(), mejor_pos[0] if eje == 'x' else mejor_pos[1], mejor_val))
    return mejor_pos, mejor_val


def rutina_escaneo():
    print('======= INICIO ESCANEO =======')
    estado()
    escanear_eje('x')
    escanear_eje('y')
    print('======= POSICION OPTIMA (%.1f, %.1f) =======' %
          (base_pos[0], base_pos[1]))
    estado()


# ==================== BOTON ====================
def leer_pulsacion(boton):
    t0 = time.ticks_ms()
    es_largo = False
    while boton.value() == 0:
        if not es_largo and time.ticks_diff(time.ticks_ms(), t0) > LONG_PRESS_MS:
            es_largo = True
            print('  (largo detectado, suelta)')
        time.sleep_ms(20)
    return 'long' if es_largo else 'short'


# ==================== MAIN ====================
def imprimir_config():
    print('=== CONFIG ===')
    print('  caja: %d x %d x %d mm' %
          (CFG['box_x_mm'], CFG['box_y_mm'], CFG['box_z_mm']))
    print('  base: %d x %d mm' % (CFG['base_x_mm'], CFG['base_y_mm']))
    print('  recorrido util: +-%.1f mm (X), +-%.1f mm (Y)' %
          (TRAVEL_X_MAX, TRAVEL_Y_MAX))
    print('  mm por pulso Hall: %.2f' % MM_POR_PULSO)
    print('  paso scan / joy: %.1f / %.1f mm' %
          (CFG['paso_scan_mm'], CFG['paso_joy_mm']))


def main():
    parar_todo()
    time.sleep_ms(100)
    print('=== Aerogenerador flotante ===')
    imprimir_config()
    print('Joystick mueve. TENSAR/DESTENSAR mantenido. SCAN corto=escaneo, largo=cero.')

    while True:
        if btn_tensar.value() == 0:
            print('TENSANDO'); tensar_mantenido(btn_tensar); print('stop'); continue
        if btn_destensar.value() == 0:
            print('DESTENSANDO'); destensar_mantenido(btn_destensar); print('stop'); continue
        if btn_scan.value() == 0:
            ev = leer_pulsacion(btn_scan)
            if ev == 'long':
                set_zero()
            else:
                try: rutina_escaneo()
                except Exception as e:
                    print('!! error:', e); parar_todo()
            continue
        joystick_step()
        time.sleep_ms(JOY_LOOP_MS)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        parar_todo(); print('parado por usuario')
    except Exception as e:
        parar_todo(); print('error fatal:', e); raise
