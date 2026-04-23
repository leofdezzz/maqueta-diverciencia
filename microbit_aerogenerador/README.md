# Microbit A — Aerogenerador

Código que va en el Microbit situado en el aerogenerador flotante.

## Funciones

- Lee voltaje del aerogenerador por ADC (pin0)
- Envía el valor por radio al Microbit B cada ~400ms
- Botón A → envía `STOP` (para motores)
- Botón B → envía `RESUME` (reanuda motores)
- LEDs muestran nivel de viento (0-4 barras)

## Archivos

| Archivo | Descripción |
|---|---|
| `aerogenerador.py` | Versión 4 motores (para `ventilador.py`) |
| `aerogenerador_2m.py` | Versión 2 motores (para `ventilador_2motores.py`) |

## Conexiones

| Pin | Función |
|---|---|
| pin0 | ADC — lectura voltaje aerogenerador (via divisor resistivo) |
| pin1, pin2 | Libres |
| Botón A/B | Integrados en placa |

## Divisor resistivo (importante)

El aerogenerador puede generar más de 3.3V. Usar un divisor:

```
  aero (+) ──[ 10kΩ ]──┬──[ 4.7kΩ ]── GND
                        │
                       pin0 (ADC)
```

Ajustar según voltaje máximo del aerogenerador.

## Flashear

1. Conectar Microbit al ordenador
2. Abrir [Python Editor](https://python.microbit.org/)
3. Copiar y pegar el contenido de `aerogenerador_2m.py`
4. Descargar y arrastrar al Microbit

## Radio

- Grupo: 7
- Potencia: máxima
- Formato mensaje: `V:xxx` (voltaje integer)
