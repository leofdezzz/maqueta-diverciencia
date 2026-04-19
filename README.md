# Aerogenerador flotante auto-orientable

> Una maqueta que descubre ella sola dónde captar más viento.

Imagina una caja llena de agua y, flotando dentro, un aerogenerador en miniatura. Un blower de 12 V sopla desde alguno de los cuatro lados — no sabes cuál, o cambia a menudo. ¿Cuál es la mejor posición para la turbina?

Este proyecto responde esa pregunta **en menos de un minuto**, automáticamente: cuatro cabrestantes tiran de unos cables finos atados a las esquinas de la base flotante. El ESP32 desplaza la base por el eje X buscando el pico de corriente, luego hace lo mismo por el eje Y, y aparca la turbina en el óptimo.

Todo configurable por milímetros reales. Todo en MicroPython. Menos de 30 € en componentes.

---

## Vista general

```
                           BLOWER
                             ║
                             ║  viento →
     ┌───────────────────────╨────────────────┐
     │ [FL]═════════════════════════════[FR]  │  ← 4 motores fijos en las
     │   ╲                             ╱      │    esquinas superiores
     │    ╲       ┌─────────────┐    ╱        │
     │     ╲      │  turbina    │   ╱         │  ← base flotante, 4 cables
     │      ╲     │  flotando   │  ╱          │    tiran desde arriba
     │       ╲    │  en el agua │ ╱           │
     │        ╲   └─────────────┘╱            │
     │ [BL]═══════════════════[BR]            │
     │           agua dentro ~~~~~~           │
     └────────────────────────────────────────┘
```

Cada motor controla la longitud de su cable. Los 4 cables juntos deciden la posición exacta de la base en el plano X-Y. La flotabilidad se encarga de la altura.

---

## El flujo, en 6 pasos

```
 1.  Enciendes. Base en cualquier punto.
 2.  Joystick → centras la base a ojo.
 3.  ¿Cable flojo?  TENSAR (los 4 motores recogen).
 4.  SCAN largo (3s) → marca cero.  "Aquí estamos en el centro."
 5.  SCAN corto → barre X, vuelve al mejor → barre Y, vuelve al mejor.
 6.  Listo. La turbina está donde más corriente genera.
```

---

## Hardware

| Pieza | Uso | Cantidad |
|---|---|---|
| ESP32 DevKit v1 | Cerebro (MicroPython) | 1 |
| JGB37-520 12V 22 RPM | Motor cabrestante | 4 |
| L298N | Driver motor | 2 (dual) o 4 |
| Hall A3144 | Cuenta pulsos de rotación | 4 |
| Imán neodimio 3×1 mm | 2 por tambor → media vuelta/pulso | 8 |
| Joystick KY-023 | Movimiento manual | 1 |
| Pulsadores 12 mm | SCAN / TENSAR / DESTENSAR | 3 |
| Mosquetón pesca con giratorio | Unión desmontable cable ↔ base | 4 |
| Armella M4 | Anclaje en la base | 4 |
| Sedal trenzado 50 lb | El cable | 5 m |
| Fuente 12 V / 3 A | Alimenta motores | 1 |

**Total aproximado:** 25-30 €.

---

## El truco: cinemática inversa

El código no mueve "un paso a la izquierda". Trabaja con **milímetros absolutos**.

Cuando le pides *"lleva la base a (+50 mm, -30 mm)"*:

1. Calcula la posición 3D de las 4 esquinas superiores de la caja.
2. Calcula dónde estará cada esquina de la base al llegar al destino.
3. Resuelve la distancia euclídea en 3D motor ↔ esquina de base, cable por cable.
4. Compara con la longitud **actual** → decide si cada cable debe acortarse o alargarse, y cuánto.
5. Convierte milímetros a pulsos Hall sabiendo el diámetro del tambor.
6. Cada motor va a por *sus* pulsos. El que llega primero se detiene solo. Cuando los 4 terminan, la base está exactamente donde pediste.

La fórmula clave, por cable:

```
L = √( (x_base + offset_x - corner_x)² + (y_base + offset_y - corner_y)² + altura² )
```

Esto hace que funcione **incluso si la caja es rectangular**: el motor FR no recoge lo mismo que el FL cuando mueves en diagonal, y eso el código lo calcula solo.

---

## `config.json` — toda tu caja en un archivo

No tocas código para adaptar el sistema a *tu* montaje. Editas esto:

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
| `box_x/y/z_mm` | Dimensiones internas de la caja. **Z** = distancia vertical del motor al nivel del agua. |
| `base_x/y_mm` | Dimensiones de la base flotante. |
| `margen_mm` | Seguridad al borde interno (el rango útil se reduce en este valor). |
| `diam_tambor_mm` | Diámetro del tambor con cable enrollado. Determina cuánto cable da cada vuelta. |
| `imanes_por_tambor` | 2 imanes = media vuelta por pulso Hall. 1 = vuelta entera. |
| `paso_scan_mm` | Resolución del barrido automático. |
| `paso_joy_mm` | Cuánto mueve cada tick de joystick. |
| `pwm_duty` / `pwm_duty_lento` | Velocidad motores (0-1023). Lento para joystick y tensar. |

El firmware recalcula automáticamente:
- Recorrido útil: `(box - base)/2 - margen` en cada eje.
- Milímetros por pulso: `π × diámetro / imanes`.

---

## Montaje mecánico

### Unión cable ↔ base (desmontable)

1. Atornillas una **armella M4** en cada esquina de la base flotante.
2. El extremo del cable termina con un lazo; al lazo le clipa un **mosquetón de pesca con giratorio**.
3. Para unir: abres el mosquetón, pasa por la armella, cierras. 2 segundos.
4. El giratorio evita que el cable se enrolle sobre sí mismo cuando el tambor gira.

### Tambores + sensores Hall

- Imprime o monta un tambor en el eje de cada motor (diámetro anotado en `config.json`).
- Pega 2 imanes neodimio pequeños a **180°**, **misma polaridad hacia fuera** (el A3144 es unipolar).
- Fija el A3144 al chasis del motor a 2-3 mm del imán cuando pasa.
- Cada media vuelta del tambor = un flanco detectado = `π × diámetro / 2` mm de cable.

---

## Pines ESP32

| Función | Pin |
|---|---|
| Motor FL (IN1 / IN2 / EN) | 14 / 27 / 26 |
| Motor FR | 32 / 33 / 25 |
| Motor BL | 13 / 12 / 15 |
| Motor BR | 4 / 16 / 17 |
| Hall FL / FR / BL / BR | 18 / 19 / 21 / 22 |
| Joystick X / Y (ADC) | 36 / 39 |
| Sensor turbina (ADC) | 34 |
| Botón SCAN | 5 |
| Botón TENSAR | 2 |
| Botón DESTENSAR | 35 *(pull-up externo 10 kΩ)* |

---

## Flashear

```bash
mpremote connect COMx cp main.py :main.py
mpremote connect COMx cp config.json :config.json
mpremote connect COMx reset
```

Abre la consola serie (115200 baud). Verás la config cargada, el recorrido útil calculado, y el prompt de botones.

---

## Controles

| Acción | Resultado |
|---|---|
| **Joystick** | Mueve la base manualmente por X-Y en pasos de `paso_joy_mm`. |
| **TENSAR (mantener)** | Los 4 motores recogen cable a la vez. Útil para quitar holgura. |
| **DESTENSAR (mantener)** | Los 4 motores sueltan cable a la vez. Para liberar tensión. |
| **SCAN pulsación corta** | Arranca el barrido automático X + Y. |
| **SCAN pulsación larga (3 s)** | Marca la posición actual como **cero** geométrico. |

---

## Arquitectura del código

Un único `main.py` (~300 líneas MicroPython):

```
config.json ─► CFG ─► geometría derivada (rangos, esquinas, mm/pulso)
                         │
                         ▼
Motor (class) ◄── IRQ Hall A3144 ─► pulses_move
    │
    ▼
mover_a(x_mm, y_mm)  [cinemática inversa]
    │
    ├── joystick_step()      → incremental, duty lento
    ├── rutina_escaneo()     → barrido X luego Y
    └── tensar/destensar     → los 4 a la vez, mantenido

Loop principal:
    TENSAR > DESTENSAR > SCAN > joystick
```

---

## Ideas para ampliar

- Pantalla OLED mostrando `(x, y)` en tiempo real y la lectura de la turbina.
- Guardar el último óptimo encontrado en el flash (`ujson`).
- Escaneo 2D en espiral en vez de X seguido de Y → más rápido cuando el viento no es perpendicular.
- Detección de atasco por current sensing en los motores (INA219).
- Control por Bluetooth/Wi-Fi desde el móvil (web dashboard).

---

## Licencia

MIT. Úsalo, copialo, mejóralo.
