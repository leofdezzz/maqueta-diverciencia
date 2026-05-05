"""
Microbit A - Aerogenerador (version 2 motores diagonal)
Lee voltaje del aerogenerador, envia por radio al Microbit B.
Compatible con ventilador_2motores.py (2 motores FL+BR en diagonal).
"""

from microbit import (
    pin1,
    display, Image, sleep
)
import radio


VOLTAJE_MIN = 50
GRUPO_RADIO = 7
MEDIR_MS = 400


radio.on()
radio.config(group=GRUPO_RADIO, power=7)


def leer_voltaje():
    total = 0
    for _ in range(10):
        total += pin1.read_analog()
        sleep(5)
    return total // 10


def mostrar_nivel(raw):
    if raw < VOLTAJE_MIN:
        display.show(Image.DIAMOND)
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


while True:
    raw = leer_voltaje()
    mostrar_nivel(raw)
    radio.send("V:%d" % raw)
    sleep(MEDIR_MS)