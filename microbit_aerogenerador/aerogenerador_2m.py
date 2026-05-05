from microbit import pin1, display, Image, sleep
import radio

GRUPO_RADIO = 7
MEDIR_MS = 400

RAW_MIN = 2          # casi cero, para no filtrar señal real
RAW_MAX = 80         # ajusta tras medir tu motor a viento máximo

radio.on()
radio.config(group=GRUPO_RADIO, power=7)

def leer_voltaje():
    total = 0
    muestras = 50      # más muestras = menos ruido
    for _ in range(muestras):
        total += pin1.read_analog()
        sleep(1)
    return round(total / muestras)

def mostrar_nivel(raw):
    if raw < RAW_MIN:
        display.show(Image.DIAMOND)
        return
    # Escala dinámica: mapea 0..RAW_MAX a 0..4
    nivel = min(4, (raw * 5) // RAW_MAX)
    iconos = [
        Image("00000:00000:00900:00000:00000"),
        Image("00000:00900:09900:00900:00000"),
        Image("00000:09900:99900:09900:00000"),
        Image("00900:09900:99900:09900:00900"),
        Image("99999:99999:99999:99999:99999"),
    ]
    display.show(iconos[nivel])

while True:
    raw = leer_voltaje()
    mostrar_nivel(raw)
    radio.send("V:%d" % raw)
    sleep(MEDIR_MS)