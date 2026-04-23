# Microbit B — Ventilador / Controlador

Código que va en el Microbit situado fuera de la caja, junto al blower. Recibe datos del Microbit A y controla los motores.

## Funciones

- Recibe voltaje por radio del Microbit A
- Lee brújula integrada para saber hacia dónde apunta
- Decide dirección de movimiento cuando voltaje < umbral
- Controla motores directamente (2 motores) o via PCF8574 (4 motores)

## Archivos

| Archivo | Motores | Hardware necesario |
|---|---|---|
| `ventilador.py` | 4 (FL, FR, BL, BR) | PCF8574 + PCA9685 (opcional) |
| `ventilador_2motores.py` | 2 (FL, BR) | Sin expansor |

## Versión 2 motores (recomendada)

Solo 4 pines usados — sin expansor GPIO.

```
  Y
  ^
  |  FL ─────── BR
  |   \        /
  |    \      /
  +-----+────> X
```

| Pin Microbit | → L298N | Función |
|---|---|---|
| pin0 | IN1 FL | Motor FL dirección |
| pin1 | IN2 FL | Motor FL dirección |
| pin2 | IN1 BR | Motor BR dirección |
| pin8 | IN2 BR | Motor BR dirección |

**ENA de cada L298N hardwireado a VCC (12V).**

## Lógica de movimiento

Cuando el voltaje cae bajo el umbral:
1. Leer brújula → sabe hacia dónde apunta el aerogenerador
2. Mover perpendicular a esa dirección

| Heading brújula | Obstáculo está al... | Mover... |
|---|---|---|
| 0°-45° / 315°-360° (Norte) | Norte | +X |
| 45°-135° (Este) | Este | -Y |
| 135°-225° (Sur) | Sur | -X |
| 225°-315° (Oeste) | Oeste | +Y |

## Configuración

Editar las constantes al inicio del archivo:

```python
GRUPO_RADIO = 7
VOLTAJE_UMBRAL = 50      # por debajo → mover
TIEMPO_PASO_MS = 300     # duración de cada paso

BOX_X_MM = 400            # dimensiones caja
BOX_Y_MM = 200
BOX_Z_MM = 300
BASE_X_MM = 150
BASE_Y_MM = 150
MARGEN_MM = 20
```

## Flashear

1. Conectar Microbit al ordenador
2. Abrir [Python Editor](https://python.microbit.org/)
3. Copiar y pegar el contenido de `ventilador_2motores.py`
4. Descargar y arrastrar al Microbit

## Requisitos

- Microbit v2 (la brújula solo está en v2)
- Calibrar brújula: al encender mantener el Microbit en forma de 8 durante 2-3 segundos
