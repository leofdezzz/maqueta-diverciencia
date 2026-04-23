"""
Microbit B - Ventilador / Controlador
Recibe voltaje por radio del Microbit A.
Con brújula integrada decide hacia dónde mover.
Controla 4 motores via PCF8574 (expansor GPIO I2C).
Los ENA de los L298N van hardwireados a VCC (velocidad fija).
"""

from microbit import (
    compass, display, Image,
    sleep, radio, i2c
)


# ===== CONFIGURACIÓN (editar aquí) =====
GRUPO_RADIO = 7
VOLTAJE_UMBRAL = 50
TIEMPO_PASO_MS = 300
# PCF8574: ajusta la dirección según tu placa
PCF8574_ADDR = 0x20
# PCA9685: dirección del driver PWM (para futuras mejoras)
PCA9685_ADDR = 0x40

BOX_X_MM = 400
BOX_Y_MM = 200
BOX_Z_MM = 300
BASE_X_MM = 150
BASE_Y_MM = 150
MARGEN_MM = 20

TRAVEL_X = (BOX_X_MM - BASE_X_MM) // 2 - MARGEN_MM
TRAVEL_Y = (BOX_Y_MM - BASE_Y_MM) // 2 - MARGEN_MM


# ===== ESTADO =====
pos_x = 0
pos_y = 0
motores_activos = True
voltaje_recibido = 0
ultimo_mensaje = 0


# ===== PCF8574 - control motores =====
# Bits: P0=FL_IN1, P1=FL_IN2, P2=FR_IN1, P3=FR_IN2
#       P4=BL_IN1, P5=BL_IN2, P6=BR_IN1, P7=BR_IN2
def pcf8574_escribir(valor):
    data = bytes([valor & 0xFF])
    i2c.write(PCF8574_ADDR << 1, data)

def pcf8574_leer():
    i2c.write((PCF8574_ADDR << 1), b'\xFF')
    return i2c.read((PCF8574_ADDR << 1), 1)[0]


# Modos motor: wind=reducir cable, release=allargar cable
# stop = ambos bits a 0 (motor libre)
# brake = ambos bits a 1 (freno rápido)

def motor_stop(m):
    bits = {
        'FL': (0, 1),
        'FR': (2, 3),
        'BL': (4, 5),
        'BR': (6, 7),
    }
    p0, p1 = bits[m]
    estado = pcf8574_leer()
    estado &= ~(1 << p0)
    estado &= ~(1 << p1)
    pcf8574_escribir(estado)

def motor_wind(m):
    bits = {
        'FL': (0, 1),
        'FR': (2, 3),
        'BL': (4, 5),
        'BR': (6, 7),
    }
    p0, p1 = bits[m]
    estado = pcf8574_leer()
    estado |= (1 << p0)
    estado &= ~(1 << p1)
    pcf8574_escribir(estado)

def motor_release(m):
    bits = {
        'FL': (0, 1),
        'FR': (2, 3),
        'BL': (4, 5),
        'BR': (6, 7),
    }
    p0, p1 = bits[m]
    estado = pcf8574_leer()
    estado &= ~(1 << p0)
    estado |= (1 << p1)
    pcf8574_escribir(estado)

def motor_brake(m):
    bits = {
        'FL': (0, 1),
        'FR': (2, 3),
        'BL': (4, 5),
        'BR': (6, 7),
    }
    p0, p1 = bits[m]
    estado = pcf8574_leer()
    estado |= (1 << p0) | (1 << p1)
    pcf8574_escribir(estado)

def parar_todos():
    for m in ['FL', 'FR', 'BL', 'BR']:
        motor_stop(m)

def frenar_todos():
    for m in ['FL', 'FR', 'BL', 'BR']:
        motor_brake(m)


# ===== Cinemática inversa (simplificada) =====
# +X: FL+BL sueltan cable, FR+BR recogen
# -X: FL+BL recogen, FR+BR sueltan
# +Y: FL+FR sueltan, BL+BR recogen
# -Y: FL+FR recogen, BL+BR sueltan

def mover_x_plus():
    motor_release('FL')
    motor_release('BL')
    motor_wind('FR')
    motor_wind('BR')

def mover_x_minus():
    motor_wind('FL')
    motor_wind('BL')
    motor_release('FR')
    motor_release('BR')

def mover_y_plus():
    motor_release('FL')
    motor_release('FR')
    motor_wind('BL')
    motor_wind('BR')

def mover_y_minus():
    motor_wind('FL')
    motor_wind('FR')
    motor_release('BL')
    motor_release('BR')


def mover_segun_compass():
    global pos_x, pos_y
    heading = compass.heading()

    # Brújula: 0=Norte, 90=Este, 180=Sur, 270=Oeste
    # Si heading=Norte (0°), el aerogenerador apunta al Norte.
    # El viento viene del Norte (bloqueado de ahí).
    # → Mover perpendicular: Este (+X)
    #
    # Lógica: mover en eje perpendicular al viento.
    # Como no conocemos la dirección del viento, asumimos que el
    # viento viene de donde apunta el aerogenerador cuando no genera.
    # Si no genera, algo bloquea en esa dirección.
    # → MOVER PERPENDICULAR a la dirección que indica la brújula.
    #
    #   Heading 0-45°  o 315-360° (Norte): mover +X
    #   Heading 45-135° (Este):          mover -Y
    #   Heading 135-225° (Sur):          mover -X
    #   Heading 225-315° (Oeste):        mover +Y

    if (heading < 45) or (heading >= 315):
        if pos_x < TRAVEL_X:
            mover_x_plus()
            pos_x += 1
            return True
    elif heading < 135:
        if pos_y > -TRAVEL_Y:
            mover_y_minus()
            pos_y -= 1
            return True
    elif heading < 225:
        if pos_x > -TRAVEL_X:
            mover_x_minus()
            pos_x -= 1
            return True
    else:
        if pos_y < TRAVEL_Y:
            mover_y_plus()
            pos_y += 1
            return True
    return False


# ===== RADIO =====
radio.on()
radio.config(group=GRUPO_RADIO)


# ===== INICIALIZACIÓN =====
parar_todos()
display.show(Image.IRECT)
sleep(500)

# Calibrar brújula al inicio (mover en círculo si es necesario)
compass.clear_calibration()

print("Ventilador listo")
display.show(Image.ARROW_N)
sleep(1000)


# ===== MAIN LOOP =====
while True:
    incoming = radio.receive()
    if incoming:
        ultimo_mensaje = running_time()

        if incoming == "STOP":
            motores_activos = False
            parar_todos()
            display.show(Image.SQUARE)
            continue

        elif incoming == "RESUME":
            motores_activos = True
            display.show(Image.ARROW_N)
            continue

        elif incoming.startswith("V:"):
            try:
                voltaje_recibido = int(incoming[2:])
            except:
                voltaje_recibido = 0

    # Detectar desconexión (5s sin mensaje)
    if running_time() - ultimo_mensaje > 5000:
        motores_activos = False
        parar_todos()
        display.show(Image.NO)
        continue

    # Auto-mover si no hay voltaje y motores activos
    if motores_activos and voltaje_recibido < VOLTAJE_UMBRAL:
        se_movio = mover_segun_compass()
        display.show(Image.ARROW_E if se_movio else Image.X)
        sleep(TIEMPO_PASO_MS)
        parar_todos()
        sleep(50)
    else:
        display.show(Image.HEART)
        parar_todos()

    sleep(50)
