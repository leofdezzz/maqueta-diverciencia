"""
Microbit B - Ventilador / Controlador (2 motores en diagonal)
Versión con solo 2 motores: FL (-X, +Y) y BR (+X, -Y).
Los cables tiran en diagonal. Moviendo uno o ambos se cubre todo el plano XY.

Recibe voltaje por radio del Microbit A.
Con brújula decide hacia dónde mover.
Controla 2 motores directamente (sin PCF8574).

  Y
  ^
  |  FL ----- aerogenerador ----- BR
  |   \        (centro)          /
  |    \                      /
  +-----+---------------------> X
"""

from microbit import (
    compass, display, Image,
    sleep, radio, pin0, pin1, pin2, pin8
)


# ===== CONFIGURACIÓN =====
GRUPO_RADIO = 7
VOLTAJE_UMBRAL = 50
TIEMPO_PASO_MS = 300

# Dimensiones caja (para límites)
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


# ===== MOTORES (2 motores: FL y BR) =====
# FL (Front-Left):  pin0 = IN1, pin1 = IN2
# BR (Back-Right):  pin2 = IN1, pin8 = IN2
# ENA va hardwireado a VCC en el L298N

# FL motor
def fl_wind():
    pin0.write_digital(1)
    pin1.write_digital(0)

def fl_release():
    pin0.write_digital(0)
    pin1.write_digital(1)

def fl_stop():
    pin0.write_digital(0)
    pin1.write_digital(0)

def fl_brake():
    pin0.write_digital(1)
    pin1.write_digital(1)

# BR motor
def br_wind():
    pin2.write_digital(1)
    pin8.write_digital(0)

def br_release():
    pin2.write_digital(0)
    pin8.write_digital(1)

def br_stop():
    pin2.write_digital(0)
    pin8.write_digital(0)

def br_brake():
    pin2.write_digital(1)
    pin8.write_digital(1)

def parar_todos():
    fl_stop()
    br_stop()

def frenar_todos():
    fl_brake()
    br_brake()


# ===== GEOMETRÍA: 2 cables en diagonal =====
# Motor FL (-X, +Y) → plataforma ← Motor BR (+X, -Y)
#
# Trayectoria del cable desde esquina de caja hasta esquina de base:
#   FL → (x, y): acorta al moverse hacia +X o -Y
#   BR → (x, y): acorta al moverse hacia -X o +Y
#
# Movimientos:
#   wind FL + release BR → mueve hacia FL (-X, +Y)
#   release FL + wind BR → mueve hacia BR (+X, -Y)
#   wind FL + release BR  (BR más lento) → más -X, algo de +Y
#   wind BR + release FL  (FL más lento) → más +X, algo de -Y
#
# Para cubrir todo el plano XY:
#   Eje X+: BR.wind() dominante, algo de FL.release()
#   Eje X-: FL.wind() dominante, algo de BR.release()
#   Eje Y+: FL.release() + BR.wind() (diagonal)
#   Eje Y-: FL.wind() + BR.release() (diagonal)
#
# Implementación: diferencia de velocidad (duty simulado con tiempo activo)
#   paso_rapido_ms: tiempo que el motor dominante está activo
#   paso_lento_ms:  tiempo que el motor secundario está activo
#  Ambos motores NUNCA paran al mismo tiempo → el aerogenerador flota

PASO_X_MS = 250
PASO_Y_MS = 250
TIEMPO_CICLO_MS = 400  # un motor activo, el otro en opposed


def mover_x_plus():
    """BR.wind + FL.release → +X"""
    br_wind()
    fl_release()
    sleep(PASO_X_MS)
    return True

def mover_x_minus():
    """FL.wind + BR.release → -X"""
    fl_wind()
    br_release()
    sleep(PASO_X_MS)
    return True

def mover_y_plus():
    """FL.release + BR.wind → +Y (diagonal)"""
    fl_release()
    br_wind()
    sleep(PASO_Y_MS)
    return True

def mover_y_minus():
    """FL.wind + BR.release → -Y (diagonal)"""
    fl_wind()
    br_release()
    sleep(PASO_Y_MS)
    return True


def mover_segun_compass():
    global pos_x, pos_y
    heading = compass.heading()

    # Brújula: 0=Norte, 90=Este, 180=Sur, 270=Oeste
    # Si heading=Norte: el aero apunta al Norte
    # → obstáculo está al Norte → mover perpendicular: +X ( Este)
    # Si heading=Este: obstáculo al Este → mover -Y
    # Si heading=Sur: obstáculo al Sur → mover -X
    # Si heading=Oeste: obstáculo al Oeste → mover +Y

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
print("2 motores diagonal listo")
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

    if running_time() - ultimo_mensaje > 5000:
        motores_activos = False
        parar_todos()
        display.show(Image.NO)
        continue

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
