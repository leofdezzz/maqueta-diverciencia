# maqueta-diverciencia

Aerogenerador flotante auto-orientable. **ESP32 + MicroPython + 4 cabrestantes con cinemática inversa.**

Un blower sopla viento desde algún lado de una caja con agua. Dentro flota una base con un aerogenerador en miniatura. El sistema mueve la base por X e Y hasta la posición que genera **más corriente**, y se queda allí.

---

## Cómo trabaja

```
                          BLOWER
                            ║  →
     ┌──────────────────────╨────────────┐
     │ [FL]═════════════════════[FR]     │  4 motores fijos en las
     │   ╲                      ╱        │  esquinas superiores
     │    ╲    ┌───────────┐   ╱         │
     │     ╲   │  turbina  │  ╱          │  base flotante, tirada
     │      ╲  │  flotando │ ╱           │  por 4 cables
     │       ╲ └───────────┘╱            │
     │ [BL]═════════════[BR]             │
     │       agua dentro  ~~~~           │
     └───────────────────────────────────┘
```

Secuencia:

1. Centrar base con joystick.
2. Pulsación larga `SCAN` (3 s) → marca cero.
3. Pulsación corta `SCAN` → barre X, vuelve al máximo. Barre Y, vuelve al máximo.
4. Base parada en el óptimo.

---

## Hardware

| Pieza | Cantidad |
|---|---|
| ESP32 DevKit v1 | 1 |
| Motor JGB37-520 12 V 22 RPM | 4 |
| Driver L298N | 2 (dual) o 4 |
| Sensor Hall A3144 | 4 |
| Imán neodimio 3×1 mm | 8 (2 por tambor) |
| Joystick KY-023 | 1 |
| Pulsadores 12 mm | 3 |
| Mosquetón pesca con giratorio | 4 |
| Armella M4 | 4 |
| Sedal trenzado 50 lb | 5 m |
| Fuente 12 V / 3 A | 1 |

Coste aproximado: 25-30 €.

---

## Cinemática inversa

Movimiento en milímetros absolutos, no en pasos ciegos. Para llevar la base a `(x, y)`:

```
L_cable = √( (x + offset_x − corner_x)² + (y + offset_y − corner_y)² + altura² )
```

- 4 longitudes calculadas por geometría 3D.
- Cada motor recibe su delta en pulsos Hall.
- El motor que llega antes a su objetivo para solo; los otros siguen.
- Funciona igual en cajas cuadradas o rectangulares — las asimetrías se resuelven solas.

---

## `config.json`

Todas las medidas en un archivo. No se toca código para adaptar el sistema.

```json
{
  "box_x_mm": 400,
  "box_y_mm": 200,
  "box_z_mm": 300,
  "base_x_mm": 150,
  "base_y_mm": 150,
  "margen_mm": 20,
  "diam_tambor_mm": 15.0,
  "imanes_por_tambor": 2,
  "paso_scan_mm": 30,
  "paso_joy_mm": 5,
  "pwm_duty": 700,
  "pwm_duty_lento": 500
}
```

| Clave | Significado |
|---|---|
| `box_x/y/z_mm` | Dimensiones internas de la caja. `Z` = altura del motor sobre el agua. |
| `base_x/y_mm` | Dimensiones de la base flotante. |
| `margen_mm` | Margen de seguridad al borde. |
| `diam_tambor_mm` | Diámetro del tambor con cable enrollado. |
| `imanes_por_tambor` | 2 imanes = media vuelta/pulso. |
| `paso_scan_mm` / `paso_joy_mm` | Resolución del barrido y del joystick. |
| `pwm_duty` / `pwm_duty_lento` | Velocidad motores (0-1023). |

Cálculos automáticos al arrancar:
- Recorrido útil: `(box − base)/2 − margen` por eje.
- mm por pulso: `π × diámetro / imanes`.

---

## Controles

| Acción | Resultado |
|---|---|
| Joystick | Mueve la base por X-Y en pasos de `paso_joy_mm`. |
| `TENSAR` mantenido | Los 4 motores recogen a la vez. |
| `DESTENSAR` mantenido | Los 4 motores sueltan a la vez. |
| `SCAN` corto | Barrido automático X + Y. |
| `SCAN` largo (3 s) | Marca posición actual como cero. |

---

## Pines ESP32

| Función | Pin |
|---|---|
| Motor FL (IN1/IN2/EN) | 14 / 27 / 26 |
| Motor FR | 32 / 33 / 25 |
| Motor BL | 13 / 12 / 15 |
| Motor BR | 4 / 16 / 17 |
| Hall FL/FR/BL/BR | 18 / 19 / 21 / 22 |
| Joystick X/Y | 36 / 39 (ADC) |
| Sensor turbina | 34 (ADC) |
| Botón SCAN | 5 |
| Botón TENSAR | 2 |
| Botón DESTENSAR | 35 *(pull-up externo 10 kΩ)* |

---

## Montaje mecánico

**Unión cable ↔ base:** armella M4 en cada esquina de la base + mosquetón de pesca con giratorio en el extremo del cable. Clipa/desclipa en 2 segundos. El giratorio evita que el cable se enrolle sobre sí mismo.

**Tambor:** pieza cilíndrica al eje del motor, 2 imanes neodimio pegados a 180° con la **misma polaridad hacia fuera**. A3144 fijado al chasis a 2-3 mm del imán.

**Anclaje motor al tambor:** nudo pasando por un agujero del tambor + gota de cianoacrilato.

---

## Flashear

```bash
mpremote connect COMx cp main.py :main.py
mpremote connect COMx cp config.json :config.json
mpremote connect COMx reset
```

Consola serie a 115200 baud. Al arrancar imprime la config cargada y el recorrido útil calculado.

---

## Estructura del código

`main.py`, ~300 líneas.

```
CFG  ← config.json
 │
 ├─ derivadas: TRAVEL_MAX, BOX_CORNERS, MM_POR_PULSO
 │
 ├─ Motor (class) ── IRQ Hall ──► pulses_move
 │
 ├─ mover_a(x_mm, y_mm)           cinemática inversa
 ├─ joystick_step()                incremental
 ├─ rutina_escaneo()               X luego Y
 └─ tensar/destensar_mantenido     los 4 a la vez

Loop: TENSAR > DESTENSAR > SCAN > joystick
```

---

## Ampliaciones

- OLED con `(x, y)` y lectura turbina en tiempo real.
- Guardar óptimo en flash (`ujson`).
- Barrido 2D en espiral.
- Current sensing para detectar atascos (INA219).
- Control Bluetooth/Wi-Fi.

---

## Licencia

MIT.
