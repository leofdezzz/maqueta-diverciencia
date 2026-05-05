from microbit import (
    display, Image,
    sleep, running_time, button_a, button_b,
    pin13, pin14, pin15, pin16
)
import radio
import math

GRUPO_RADIO = 7
VOLTAJE_UMBRAL = 15
PASO_MS = 120
FILTRO = 0.7

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
voltaje_filtrado = 0
ultimo_mensaje = running_time()

# ===== CONTROL MOTORES =====

def fl_wind():  pin13.write_digital(1); pin14.write_digital(0)
def fl_release(): pin13.write_digital(0); pin14.write_digital(1)
def fl_stop():  pin13.write_digital(0); pin14.write_digital(0)
def fl_brake(): pin13.write_digital(1); pin14.write_digital(1)

def br_wind():  pin15.write_digital(1); pin16.write_digital(0)
def br_release(): pin15.write_digital(0); pin16.write_digital(1)
def br_stop():  pin15.write_digital(0); pin16.write_digital(0)
def br_brake(): pin15.write_digital(1); pin16.write_digital(1)

def parar_todos(): fl_stop(); br_stop()
def freno_total(): fl_brake(); br_brake()
def tensar():   fl_wind(); br_wind()

# ===== MOVIMIENTO =====

def espacio_diagonal_fl():
    return DIST_MAX - math.sqrt((pos_x - 1)**2 + (pos_y + 1)**2)

def espacio_diagonal_br():
    return DIST_MAX - math.sqrt((pos_x + 1)**2 + (pos_y - 1)**2)

def puedo_mover_fl():
    return espacio_diagonal_fl() >= 0

def puedo_mover_br():
    return espacio_diagonal_br() >= 0

def mover_hay_viento():
    global pos_x, pos_y
    if espacio_diagonal_br() >= espacio_diagonal_fl():
        if puedo_mover_br():
            br_wind(); fl_release()
            pos_x += 1; pos_y -= 1
            return True
    else:
        if puedo_mover_fl():
            fl_wind(); br_release()
            pos_x -= 1; pos_y += 1
            return True
    return False

# ===== RADIO =====

radio.on()
radio.config(group=GRUPO_RADIO)

freno_total()
display.show(Image.SQUARE)
sleep(500)
display.show(Image.ARROW_N)
sleep(1000)

# ===== LOOP PRINCIPAL =====

while True:
    a_pressed = button_a.is_pressed()
    b_pressed = button_b.is_pressed()

    if a_pressed and b_pressed:
        tensar()
        display.show(Image.ALL_CLOCKS)
        ultimo_mensaje = running_time()

    elif a_pressed:
        if puedo_mover_fl():
            fl_wind(); br_release()
            display.show(Image.ARROW_NW)
            sleep(PASO_MS)
            parar_todos()
            pos_x -= 1; pos_y += 1
            ultimo_mensaje = running_time()
        else:
            display.show(Image.NO)
        sleep(PASO_MS)

    elif b_pressed:
        if puedo_mover_br():
            br_wind(); fl_release()
            display.show(Image.ARROW_SE)
            sleep(PASO_MS)
            parar_todos()
            pos_x += 1; pos_y -= 1
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
                    nuevo = int(incoming[2:])
                    voltaje_filtrado = int(
                        FILTRO * voltaje_filtrado + (1 - FILTRO) * nuevo
                    )
                    voltaje_recibido = voltaje_filtrado
                except ValueError:
                    pass  # ignorar mensajes malformados

        if running_time() - ultimo_mensaje > 5000:
            motores_activos = False
            freno_total()
            display.show(Image.NO)

        elif motores_activos and voltaje_recibido < VOLTAJE_UMBRAL:
            if mover_hay_viento():
                display.show(Image.ARROW_E)
                sleep(PASO_MS)
                parar_todos()
                ultimo_mensaje = running_time()
            else:
                display.show(Image.ALL_CLOCKS)
                freno_total()
            sleep(50)

        else:
            display.show(Image.HEART)
            freno_total()
            sleep(50)