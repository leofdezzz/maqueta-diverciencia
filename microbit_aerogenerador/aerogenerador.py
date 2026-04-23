"""
Microbit A - Aerogenerador
Lee voltaje del aerogenerador, envía por radio al Microbit B.
Botón A: enviar STOP (parar motores)
Botón B: enviar RESUME (reanudar motores)
"""

from microbit import (
    pin0, button_a, button_b,
    display, Image, sleep, radio
)


VOLTAJE_MIN = 50
GRUPO_RADIO = 7
MEDIR_MS = 400


radio.on()
radio.config(group=GRUPO_RADIO, power=7)


def leer_voltaje():
    total = 0
    for _ in range(10):
        total += pin0.read_analog()
        sleep(5)
    return total // 10


def mostrar_nivel(raw):
    if raw < VOLTAJE_MIN:
        display.show(Image.BUTTERFLY)
        return
    nivel = min(4, raw // 200)
    iconos = [
        Image("00000:00000:00900:00000:00000"),
        Image("00000:09900:09900:00900:00000"),
        Image("00000:99900:99900:09900:00000"),
        Image("00000:99900:99900:99900:00000"),
        Image("99999:99999:99999:99999:99999"),
    ]
    display.show(iconos[nivel])


def enviar(mensaje):
    try:
        radio.send(mensaje)
    except Exception:
        pass


estado_motores = "resume"
ultimo_estado = None

while True:
    if button_a.was_pressed():
        estado_motores = "stop"
        enviar("STOP")
        display.show(Image.YES)
        sleep(600)
        ultimo_estado = None

    elif button_b.was_pressed():
        estado_motores = "resume"
        enviar("RESUME")
        display.show(Image.ARROW_N)
        sleep(600)
        ultimo_estado = None

    raw = leer_voltaje()
    mostrar_nivel(raw)

    msg = "V:%d" % raw
    enviar(msg)

    sleep(MEDIR_MS)
