"""
Aerogenerador flotante - control 4 cabrestantes.

Controles:
    - Joystick + botones fisicos (TENSAR, DESTENSAR, SCAN)
    - Interfaz web: WiFi AP propio en 'AeroFlotante' / '12345678'
                    abrir http://192.168.4.1 desde movil/PC

Web permite tensar/destensar cada motor por separado, mover a posicion,
escanear y marcar cero.
"""

from machine import Pin, PWM, ADC
import time
import math
import json
import network
import socket
import gc

# ==================== CONFIG ====================
DEFAULT_CONFIG = {
    'box_x_mm': 400, 'box_y_mm': 200, 'box_z_mm': 300,
    'base_x_mm': 150, 'base_y_mm': 150,
    'margen_mm': 20,
    'diam_tambor_mm': 15.0, 'imanes_por_tambor': 2,
    'paso_scan_mm': 30, 'paso_joy_mm': 5,
    'pwm_duty': 700, 'pwm_duty_lento': 500,
    'wifi_ssid': 'AeroFlotante', 'wifi_pass': '12345678',
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
WEB_PULSE_MS = 400          # cada pulso web mantiene motor activo este tiempo


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
        self.web_deadline = 0   # ticks_ms hasta el que debe seguir activo via web

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


def parar_todo():
    for m in MOTORES:
        m.stop()


def set_zero():
    base_pos[0] = 0.0
    base_pos[1] = 0.0
    for k in cable_len:
        cable_len[k] = cable_length_mm(0, 0, k)
    print('>>> CERO marcado.')


def estado():
    print('pos=(%.1f, %.1f) cables=%s turb=%d' %
          (base_pos[0], base_pos[1],
           ' '.join('%s=%.0f' % (k, v) for k, v in cable_len.items()),
           turbina.read()))


# ==================== MOVIMIENTO IK ====================
def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def mover_a(target_x, target_y, duty=None):
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
    print('--- scan %s: +-%d pasos %.1fmm ---' % (eje, n_pasos, paso))
    if eje == 'x':
        mover_a(-n_pasos * paso, base_pos[1])
    else:
        mover_a(base_pos[0], -n_pasos * paso)
    mejor = (base_pos[0], base_pos[1])
    mejor_v = leer_turbina()
    for i in range(1, 2 * n_pasos + 1):
        if eje == 'x':
            mover_a(-n_pasos * paso + i * paso, base_pos[1])
        else:
            mover_a(base_pos[0], -n_pasos * paso + i * paso)
        v = leer_turbina()
        print('  (%.1f, %.1f) -> %.1f' % (base_pos[0], base_pos[1], v))
        if v > mejor_v:
            mejor_v = v; mejor = (base_pos[0], base_pos[1])
    mover_a(mejor[0], mejor[1])
    return mejor, mejor_v


def rutina_escaneo():
    print('==== INICIO SCAN ====')
    escanear_eje('x')
    escanear_eje('y')
    print('==== OPTIMO (%.1f, %.1f) ====' % (base_pos[0], base_pos[1]))


# ==================== WEB: deadlines de motor ====================
def web_pulse_motor(name, action):
    """Activa motor 'name' en direccion 'action' (wind/release/stop) con deadline."""
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
    """En cada iteracion del main loop, parar motores cuyo deadline expiro."""
    now = time.ticks_ms()
    for m in MOTORES:
        if m.web_deadline != 0 and time.ticks_diff(now, m.web_deadline) >= 0:
            m.stop()


# ==================== WIFI + WEB SERVER ====================
INDEX_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Aerogenerador</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{font-family:-apple-system,system-ui,sans-serif;background:#0e1116;color:#e6edf3;padding:14px;max-width:540px;margin:0 auto;font-size:15px}
h1{font-size:20px;margin-bottom:4px}
.sub{color:#8b949e;font-size:13px;margin-bottom:14px}
.stat{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:12px;margin-bottom:14px;font-family:ui-monospace,monospace;font-size:13px;line-height:1.6}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
.motor{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:10px}
.motor h3{font-size:14px;margin-bottom:8px;color:#7ee787}
.row{display:flex;gap:6px}
button{flex:1;padding:14px 8px;border:none;border-radius:8px;background:#21262d;color:#e6edf3;font-size:14px;font-weight:600;cursor:pointer;touch-action:manipulation;user-select:none}
button:active{background:#388bfd}
button.w{background:#196c2e;color:#fff}
button.w:active{background:#2ea043}
button.r{background:#7d2828;color:#fff}
button.r:active{background:#da3633}
button.s{background:#30363d}
.full{margin-bottom:14px}
.full button{padding:18px}
.move{display:grid;grid-template-columns:1fr 1fr auto;gap:8px;background:#161b22;border:1px solid #30363d;border-radius:10px;padding:10px;margin-bottom:14px}
input{padding:12px;border-radius:8px;border:1px solid #30363d;background:#0e1116;color:#e6edf3;font-size:14px;width:100%}
.danger button{background:#7d2828}
.danger button:active{background:#da3633}
</style></head><body>
<h1>Aerogenerador flotante</h1>
<div class="sub">control remoto - mantener pulsado para mover</div>
<div class="stat" id="stat">cargando...</div>

<div class="grid">
  <div class="motor"><h3>FL (frente-izq)</h3><div class="row">
    <button class="w" data-m="fl" data-a="wind">Tensar</button>
    <button class="r" data-m="fl" data-a="release">Soltar</button>
  </div></div>
  <div class="motor"><h3>FR (frente-der)</h3><div class="row">
    <button class="w" data-m="fr" data-a="wind">Tensar</button>
    <button class="r" data-m="fr" data-a="release">Soltar</button>
  </div></div>
  <div class="motor"><h3>BL (atras-izq)</h3><div class="row">
    <button class="w" data-m="bl" data-a="wind">Tensar</button>
    <button class="r" data-m="bl" data-a="release">Soltar</button>
  </div></div>
  <div class="motor"><h3>BR (atras-der)</h3><div class="row">
    <button class="w" data-m="br" data-a="wind">Tensar</button>
    <button class="r" data-m="br" data-a="release">Soltar</button>
  </div></div>
</div>

<div class="row full">
  <button class="w" data-m="all" data-a="wind">Tensar TODOS</button>
  <button class="r" data-m="all" data-a="release">Soltar TODOS</button>
</div>

<div class="move">
  <input id="x" type="number" step="5" placeholder="x mm" value="0">
  <input id="y" type="number" step="5" placeholder="y mm" value="0">
  <button onclick="moveTo()" style="background:#388bfd">Ir</button>
</div>

<div class="row full">
  <button onclick="api('/scan',{method:'POST'})" style="background:#388bfd">Escanear</button>
  <button onclick="api('/zero',{method:'POST'})" class="s">Marcar cero</button>
</div>

<div class="row full danger">
  <button onclick="api('/stop',{method:'POST'})">STOP TODO</button>
</div>

<script>
const HOLD_MS = 200;
function api(p, opts){return fetch(p, opts || {})}

document.querySelectorAll('button[data-m]').forEach(b => {
  let timer = null;
  const motor = b.dataset.m;
  const action = b.dataset.a;
  const start = e => {
    e.preventDefault();
    api('/motor/'+motor+'/'+action, {method:'POST'});
    timer = setInterval(() => api('/motor/'+motor+'/'+action, {method:'POST'}), HOLD_MS);
  };
  const stop = () => {
    if(timer){clearInterval(timer); timer=null}
    api('/motor/'+motor+'/stop', {method:'POST'});
  };
  b.addEventListener('mousedown', start);
  b.addEventListener('touchstart', start, {passive:false});
  b.addEventListener('mouseup', stop);
  b.addEventListener('mouseleave', stop);
  b.addEventListener('touchend', stop);
  b.addEventListener('touchcancel', stop);
});

function moveTo(){
  const x = document.getElementById('x').value;
  const y = document.getElementById('y').value;
  api('/move?x='+x+'&y='+y, {method:'POST'});
}

setInterval(() => {
  fetch('/status').then(r => r.json()).then(s => {
    document.getElementById('stat').innerHTML =
      'pos: ('+s.pos[0].toFixed(1)+', '+s.pos[1].toFixed(1)+') mm<br>' +
      'cables: FL='+s.cables.FL.toFixed(0)+' FR='+s.cables.FR.toFixed(0)+
      ' BL='+s.cables.BL.toFixed(0)+' BR='+s.cables.BR.toFixed(0)+' mm<br>' +
      'turbina ADC: '+s.turbina;
  }).catch(()=>{});
}, 600);
</script>
</body></html>"""


def start_wifi():
    sta = network.WLAN(network.STA_IF)
    sta.active(False)
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    try:
        ap.config(essid=CFG['wifi_ssid'], password=CFG['wifi_pass'],
                  authmode=network.AUTH_WPA_WPA2_PSK)
    except Exception:
        ap.config(essid=CFG['wifi_ssid'], password=CFG['wifi_pass'])
    ip = ap.ifconfig()[0]
    print('WiFi AP listo. SSID=%s pass=%s' % (CFG['wifi_ssid'], CFG['wifi_pass']))
    print('   abre http://%s en tu navegador' % ip)
    return ap


def start_server():
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(2)
    s.setblocking(False)
    return s


def http_send(conn, status, ctype, body):
    try:
        if isinstance(body, str):
            body = body.encode('utf-8')
        hdr = 'HTTP/1.0 %d OK\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n' % (
            status, ctype, len(body))
        conn.send(hdr.encode('utf-8'))
        conn.send(body)
    except OSError:
        pass


def http_json(conn, status, obj):
    http_send(conn, status, 'application/json', json.dumps(obj))


def parse_qs(qs):
    out = {}
    for p in qs.split('&'):
        if '=' in p:
            k, v = p.split('=', 1)
            out[k] = v
    return out


def handle_request(conn):
    try:
        conn.settimeout(0.5)
        raw = conn.recv(1024)
        if not raw:
            return
        req = raw.decode('utf-8', 'ignore')
        line = req.split('\r\n', 1)[0]
        method, path, _ = line.split(' ', 2)
    except Exception:
        try: http_send(conn, 400, 'text/plain', 'bad')
        except: pass
        return

    if path == '/' or path == '/index.html':
        http_send(conn, 200, 'text/html', INDEX_HTML)
        return

    if path == '/status':
        http_json(conn, 200, {
            'pos': [base_pos[0], base_pos[1]],
            'cables': {k: cable_len[k] for k in cable_len},
            'turbina': turbina.read(),
            'travel': [TRAVEL_X_MAX, TRAVEL_Y_MAX],
        })
        return

    if path.startswith('/motor/'):
        parts = path.split('/')
        if len(parts) >= 4:
            name = parts[2].upper()
            action = parts[3]
            if name == 'ALL':
                if action in ('wind', 'release', 'stop'):
                    for k in MOTORES_DICT:
                        web_pulse_motor(k, action)
                    http_send(conn, 200, 'text/plain', 'ok')
                    return
            elif web_pulse_motor(name, action):
                http_send(conn, 200, 'text/plain', 'ok')
                return
        http_send(conn, 404, 'text/plain', 'nope')
        return

    if path.startswith('/move'):
        try:
            qs = path.split('?', 1)[1] if '?' in path else ''
            p = parse_qs(qs)
            x = float(p.get('x', base_pos[0]))
            y = float(p.get('y', base_pos[1]))
            http_send(conn, 200, 'text/plain', 'moviendo')
            mover_a(x, y)
        except Exception as e:
            http_send(conn, 400, 'text/plain', 'err: %s' % e)
        return

    if path == '/scan':
        http_send(conn, 200, 'text/plain', 'scan en curso')
        try: rutina_escaneo()
        except Exception as e:
            print('err scan:', e); parar_todo()
        return

    if path == '/zero':
        set_zero()
        http_send(conn, 200, 'text/plain', 'cero')
        return

    if path == '/stop':
        parar_todo()
        http_send(conn, 200, 'text/plain', 'stop')
        return

    http_send(conn, 404, 'text/plain', 'not found')


def poll_web(server):
    try:
        conn, _ = server.accept()
    except OSError:
        return
    try:
        handle_request(conn)
    finally:
        try: conn.close()
        except: pass
        gc.collect()


# ==================== BOTONES ====================
def leer_pulsacion(boton):
    t0 = time.ticks_ms()
    es_largo = False
    while boton.value() == 0:
        if not es_largo and time.ticks_diff(time.ticks_ms(), t0) > LONG_PRESS_MS:
            es_largo = True
            print('  (largo, suelta)')
        time.sleep_ms(20)
    return 'long' if es_largo else 'short'


# ==================== MAIN ====================
def imprimir_config():
    print('=== CONFIG ===')
    print('  caja %dx%dx%d  base %dx%d' %
          (CFG['box_x_mm'], CFG['box_y_mm'], CFG['box_z_mm'],
           CFG['base_x_mm'], CFG['base_y_mm']))
    print('  recorrido +-%.1fmm X / +-%.1fmm Y' % (TRAVEL_X_MAX, TRAVEL_Y_MAX))
    print('  mm/pulso %.2f' % MM_POR_PULSO)


def main():
    parar_todo()
    time.sleep_ms(100)
    print('=== Aerogenerador flotante ===')
    imprimir_config()
    try:
        start_wifi()
        server = start_server()
        print('servidor HTTP listo')
    except Exception as e:
        print('!! WiFi/server fallo:', e)
        server = None
    print('joystick + botones fisicos activos.')

    while True:
        # web (no bloqueante)
        if server is not None:
            poll_web(server)
        check_web_deadlines()

        # botones fisicos (bloqueantes mientras pulsados)
        if btn_tensar.value() == 0:
            print('TENSAR'); tensar_todos_mantenido(btn_tensar); continue
        if btn_destensar.value() == 0:
            print('DESTENSAR'); destensar_todos_mantenido(btn_destensar); continue
        if btn_scan.value() == 0:
            ev = leer_pulsacion(btn_scan)
            if ev == 'long':
                set_zero()
            else:
                try: rutina_escaneo()
                except Exception as e:
                    print('!! err:', e); parar_todo()
            continue

        # joystick solo si ningun motor en deadline web (evita conflicto)
        if all(m.web_deadline == 0 for m in MOTORES):
            joystick_step()

        time.sleep_ms(JOY_LOOP_MS)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        parar_todo(); print('parado')
    except Exception as e:
        parar_todo(); print('FATAL:', e); raise
