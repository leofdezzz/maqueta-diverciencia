"""
Microbit B - Ventilador / Controlador (2 motores en diagonal)
Version con solo 2 motores: FL (-X, +Y) y BR (+X, -Y).

Recibe voltaje por radio del Microbit A.
Si voltaje bajo, mueve hacia la diagonal con mas espacio disponible.
Boton A = diagonal FL, Boton B = diagonal BR, A+B = tensar (wind ambos).

   Y
   ^
   |  FL ----- aerogenerador ----- BR
   |   \        (centro)          /
   |    \                      /
   +-----+---------------------> X
"""

from microbit import (
    display, Image,
    sleep, running_time, button_a, button_b,
    pin13, pin14, pin15, pin16
)
import radio
import math
import random


GRUPO_RADIO = 7
VOLTAJE_UMBRAL = 50
PASO_MS = 120

BOX_X_MM = 370
BOX_Y_MM = 315
BASE_X_MM = 85
BASE_Y_MM = 85
MARGEN_MM = 20

TRAVEL_X = (BOX_X_MM - BASE_X_MM) // 2 - MARGEN_MM
TRAVEL_Y = (BOX_Y_MM - BASE_Y_MM) // 2 - MARGEN_MM
DIST_MAX = math.sqrt(TRAVEL_X**2 + TRAVEL_Y**2)


pos_x = 0
pos_y = 0
motores_activos = True
voltaje_recibido = 100
voltaje_estable = False
ultimo_mensaje = running_time()


def fl_wind():
    pin13.write_digital(1)
    pin14.write_digital(0)

def fl_release():
    pin13.write_digital(0)
    pin14.write_digital(1)

def fl_stop():
    pin13.write_digital(0)
    pin14.write_digital(0)

def fl_brake():
    pin13.write_digital(1)
    pin14.write_digital(1)


def br_wind():
    pin15.write_digital(1)
    pin16.write_digital(0)

def br_release():
    pin15.write_digital(0)
    pin16.write_digital(1)

def br_stop():
    pin15.write_digital(0)
    pin16.write_digital(0)

def br_brake():
    pin15.write_digital(1)
    pin16.write_digital(1)


def parar_todos():
    fl_stop()
    br_stop()

def freno_total():
    fl_brake()
    br_brake()

def tensar():
    fl_wind()
    br_wind()


def puedo_mover_fl():
    provisional_x = pos_x - 1
    provisional_y = pos_y + 1
    provisional_dist = math.sqrt(provisional_x**2 + provisional_y**2)
    return provisional_dist <= DIST_MAX

def puedo_mover_br():
    provisional_x = pos_x + 1
    provisional_y = pos_y - 1
    provisional_dist = math.sqrt(provisional_x**2 + provisional_y**2)
    return provisional_dist <= DIST_MAX


def espacio_diagonal_fl():
    return DIST_MAX - math.sqrt((pos_x - 1)**2 + (pos_y + 1)**2)

def espacio_diagonal_br():
    return DIST_MAX - math.sqrt((pos_x + 1)**2 + (pos_y - 1)**2)


def mover_diagonal_fl():
    if puedo_mover_fl():
        fl_wind()
        br_release()
        return True
    return False

def mover_diagonal_br():
    if puedo_mover_br():
        br_wind()
        fl_release()
        return True
    return False


def mover_hay_viento():
    global pos_x, pos_y
    espacio_fl = espacio_diagonal_fl()
    espacio_br = espacio_diagonal_br()
    if espacio_br >= espacio_fl:
        if mover_diagonal_br():
            pos_x += 1
            pos_y -= 1
            return True
    else:
        if mover_diagonal_fl():
            pos_x -= 1
            pos_y += 1
            return True
    return False


radio.on()
radio.config(group=GRUPO_RADIO)


freno_total()
display.show(Image.SQUARE)
sleep(500)
display.show(Image.ARROW_N)
sleep(1000)


while True:
    a_pressed = button_a.is_pressed()
    b_pressed = button_b.is_pressed()

    if a_pressed and b_pressed:
        tensar()
        display.show(Image.ALL_CLOCKS)
        ultimo_mensaje = running_time()
    elif a_pressed:
        if mover_diagonal_fl():
            display.show(Image.ARROW_NW)
            sleep(PASO_MS)
            parar_todos()
            pos_x -= 1
            pos_y += 1
            ultimo_mensaje = running_time()
        else:
            display.show(Image.NO)
        sleep(PASO_MS)
    elif b_pressed:
        if mover_diagonal_br():
            display.show(Image.ARROW_SE)
            sleep(PASO_MS)
            parar_todos()
            pos_x += 1
            pos_y -= 1
            ultimo_mensaje = running_time()
        else:
            display.show(Image.NO)
        sleep(PASO_MS)
    else:
        incoming = radio.receive()
        if incoming:
            ultimo_mensaje = running_time()
            if incoming == "STOP":
                motores_activos = False
                freno_total()
                display.show(Image.SQUARE)
            elif incoming == "RESUME":
                motores_activos = True
                display.show(Image.ARROW_N)
            elif incoming.startswith("V:"):
                try:
                    voltaje_recibido = int(incoming[2:])
                except:
                    voltaje_recibido = 0

        if running_time() - ultimo_mensaje > 5000:
            motores_activos = False
            freno_total()
            display.show(Image.NO)
        elif motores_activos and voltaje_recibido < VOLTAJE_UMBRAL:
            if not voltaje_estable:
                lado = random.randint(0, 1)
                if lado == 0:
                    se_movio = mover_diagonal_fl()
                else:
                    se_movio = mover_diagonal_br()
                if se_movio:
                    if lado == 0:
                        pos_x -= 1
                        pos_y += 1
                    else:
                        pos_x += 1
                        pos_y -= 1
                    display.show(Image.ARROW_E)
                    sleep(PASO_MS)
                    parar_todos()
                else:
                    display.show(Image.ALL_CLOCKS)
                    voltaje_estable = True
            else:
                se_movio = mover_hay_viento()
                if se_movio:
                    display.show(Image.ARROW_E)
                    sleep(PASO_MS)
                    parar_todos()
                    ultimo_mensaje = running_time()
                else:
                    display.show(Image.ALL_CLOCKS)
            sleep(50)
        else:
            display.show(Image.HEART)
            freno_total()
            voltaje_estable = False
            sleep(50)