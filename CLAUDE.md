# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Proyecto

Maqueta de aerogenerador flotante posicionado por 4 cabrestantes. ESP32 + MicroPython. Un blower sopla viento; el sistema busca automáticamente la posición XY que maximiza la corriente generada.

## Hardware

| Componente | Detalle |
|---|---|
| MCU | ESP32 DevKit (MicroPython) |
| Motores | 4× JGB37-520 22RPM 12V — uno por esquina de la caja |
| Drivers | 4× L298N (IN1/IN2/EN) |
| Posición | 4× Hall A3144 + 2 imanes/tambor → media vuelta por pulso |
| Mando | Joystick analógico KY-023 (ADC1 GPIO 36/39) |
| Sensor viento | ADC GPIO 34 — corriente rectificada del aerogenerador |
| Botones | SCAN (5), TENSAR (2), DESTENSAR (35 — pull-up externo 10kΩ) |

## Despliegue

No hay build. Flash directo con `mpremote` o Thonny:

```bash
mpremote connect COMx cp main.py :main.py
mpremote connect COMx cp config.json :config.json
mpremote connect COMx run main.py
```

`config.json` se crea con valores por defecto en el primer arranque si no existe en el flash. Editar esos valores ajusta todo el comportamiento del sistema sin tocar el código.

## Arquitectura de `main.py`

```
Config (config.json → CFG dict)
  └─ Dimensiones caja (X, Y, Z) y base (X, Y). Alimenta IK.
  └─ Derivadas: TRAVEL_X_MAX/Y_MAX, BOX_CORNERS, BASE_OFFSETS, MM_POR_PULSO.

Cinemática inversa
  └─ cable_length_mm(base_x, base_y, corner)
       = √((Δx + offset_x)² + (Δy + offset_y)² + box_z²)
       Distancia euclídea 3D desde esquina superior de caja a esquina de la base.

Motor (class)
  └─ wind/release/stop + IRQ on_pulse (incrementa pulses_move)

Movimiento
  └─ mover_a(x_mm, y_mm)
       1. Clamp a TRAVEL_X_MAX / TRAVEL_Y_MAX.
       2. Calcula 4 nuevas longitudes de cable via IK.
       3. Δ por motor → pulsos objetivo (+ = release, − = wind).
       4. Arranca los 4; cada motor PARA individualmente al alcanzar su objetivo.
       5. Actualiza cable_len[k] y base_pos[x,y].
  └─ tensar/destensar_mantenido → los 4 a la vez mientras botón pulsado.

Estado
  └─ base_pos = [x_mm, y_mm]  (desde cero geométrico)
  └─ cable_len = {FL, FR, BL, BR}  (longitudes actuales en mm)
  └─ set_zero() resetea a centro geométrico ideal (según CFG).

Escaneo
  └─ escanear_eje('x'|'y')
       Rango = TRAVEL_MAX del eje. Pasos de CFG['paso_scan_mm'].
       Va al extremo negativo, barre, vuelve al máximo.

Loop principal
  Prioridad: TENSAR > DESTENSAR > BTN_SCAN > joystick
  BTN_SCAN corto → escaneo. Largo (3s) → set_zero.
```

## Configuración (`config.json`)

Todos los parámetros físicos se editan aquí, no en código:

| Clave | Uso |
|---|---|
| `box_x_mm`, `box_y_mm`, `box_z_mm` | Dimensiones internas de la caja. Z = distancia vertical motor ↔ agua. |
| `base_x_mm`, `base_y_mm` | Dimensiones de la base flotante. |
| `margen_mm` | Margen de seguridad desde pared interna. |
| `diam_tambor_mm` | Diámetro del tambor con cable enrollado (medir con calibre). |
| `imanes_por_tambor` | Resolución Hall. 2 imanes = media vuelta/pulso. |
| `paso_scan_mm`, `paso_joy_mm` | Resolución espacial del barrido y del joystick. |
| `pwm_duty`, `pwm_duty_lento` | Velocidad motores (0-1023). Lento para joystick/tensar. |

Derivadas automáticas:
- `TRAVEL_X_MAX = (box_x - base_x)/2 - margen`
- `MM_POR_PULSO = π·diam_tambor / imanes_por_tambor`

## Convención de ejes

Vista desde arriba, motores en esquinas de la caja:

```
        +Y (frente)
    FL ──────── FR
    │            │
  −X            +X
    │            │
    BL ──────── BR
        −Y (atrás)
```

Movimiento +X: FR+BR recogen, FL+BL sueltan. Siempre los 4 activos.

## Notas de IRQ

`on_pulse` se ejecuta en contexto de interrupción — no hacer allocations ni I/O. Solo incrementar enteros.  
GPIO 34-39 son input-only; no tienen pull-up interno hardware en algunos módulos ESP32 → usar pull-up externo 10kΩ si el Hall no responde.
