# Control BLE del aerogenerador flotante

Guía completa de la variante con Bluetooth Low Energy: ESP32 + MicroPython `ubluetooth` + navegador con Web Bluetooth.

## Qué es esto

Una alternativa al servidor WiFi de `main.py`. En lugar de montar un AP y servir HTML desde el ESP32, la placa **solo expone un servicio BLE**, y el navegador se conecta directamente a ella con la API Web Bluetooth. La web vive en un archivo HTML cualquiera (local o remoto), no en el ESP32.

Ventajas frente a WiFi AP:
- Nada de redes ni IPs. Emparejas y listo.
- Menor consumo y menos RAM en el ESP32.
- El HTML puede actualizarse sin reflashear el ESP32.
- Alcance ~10 m, suficiente para la maqueta.

Limitaciones:
- **Web Bluetooth solo funciona en Chrome / Edge / Opera (desktop) y Chrome en Android.** Safari/iOS y Firefox no lo soportan.
- Un solo cliente a la vez.

## Archivos

| Archivo | Rol |
|---|---|
| `main_ble.py` | Firmware ESP32. Reemplaza el WiFi + servidor HTTP de `main.py` por BLE. |
| `web/index.html` | Cliente Web Bluetooth. Abre en navegador, conecta, controla. |
| `config.json` | Mismo formato que la versión WiFi. Añade `"ble_name": "AeroBLE"` (opcional). |
| `main.py` | Versión WiFi original. Intacta. Elige una u otra al flashear. |

## Hardware

Idéntico a `main.py`. No cambian pines, motores, sensores ni drivers. El ESP32 ya tiene BLE integrado, así que no hace falta ningún módulo extra.

## Flashear y arrancar

Requisitos previos: ESP32 con [MicroPython 1.20+](https://micropython.org/download/ESP32_GENERIC/). El firmware estándar de ESP32 incluye `ubluetooth`.

```bash
mpremote connect COMx cp config.json :config.json
mpremote connect COMx cp main_ble.py :main.py
mpremote connect COMx reset
```

Al arrancar verás en el log serie:

```
=== Aerogenerador flotante (BLE) ===
  caja 400x200x300  base 150x150
  recorrido +-105.0mm X / +-5.0mm Y
BLE advertising como AeroBLE
joystick + botones fisicos activos.
```

> Nota: si quieres mantener `main.py` (WiFi) en el flash y arrancar la versión BLE bajo demanda, sube `main_ble.py` con su nombre y ejecútalo manualmente: `mpremote connect COMx run main_ble.py`.

## Abrir la web

Dos formas:

**Opción 1 — archivo local.** Abre `web/index.html` con doble clic. Web Bluetooth funciona desde `file://` sin servidor.

**Opción 2 — servir por HTTP(S).** Cualquier hosting estático (GitHub Pages, Netlify, Vercel, un `python -m http.server` local). Importante: **en red, la página debe servirse por HTTPS o desde `localhost`**. Web Bluetooth no funciona en HTTP remoto.

En la web:
1. Pulsa **Conectar BLE**.
2. El navegador muestra la lista de dispositivos BLE cercanos. Elige `AeroBLE`.
3. Al conectar, el log muestra `conectado` y `ESP32 listo`, y los controles se habilitan.

## Interfaz

- **4 paneles de motor** (FL, FR, BL, BR). Cada panel tiene Tensar / Soltar. Mantener pulsado mueve el motor; soltar para inmediatamente. Si el navegador se desconecta o cuelga, el motor se para solo a los 400 ms (deadline en firmware).
- **Tensar/Soltar TODOS** — accionan los 4 motores a la vez.
- **Ir a (x, y)** — mueve a coordenadas absolutas desde el cero. Saturado a los límites de la caja.
- **Escanear** — lanza el barrido automático X+Y buscando máxima corriente en turbina.
- **Marcar cero** — la posición actual queda como origen.
- **STOP TODO** — para motores y cancela movimiento/scan en curso.

## Protocolo BLE

Servicio **Nordic UART** (NUS), estándar de facto para BLE-sobre-UART:

| UUID | Dirección | Uso |
|---|---|---|
| `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` | — | Servicio |
| `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` | Cliente → ESP32 | Write (comandos) |
| `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` | ESP32 → Cliente | Notify (estado/eventos) |

Los mensajes son **JSON en una línea**, terminados en `\n`. Si el mensaje supera el MTU se parte en varias notificaciones; el cliente reensambla por `\n`.

### Comandos (web → ESP32)

| JSON | Efecto |
|---|---|
| `{"cmd":"motor","name":"FL","action":"wind"}` | Tensa motor FL. Vale FR/BL/BR/ALL. Acciones: `wind`, `release`, `stop`. Deadline 400 ms. |
| `{"cmd":"move","x":50,"y":-30}` | Mueve a posición en mm. Bloqueante hasta completar. |
| `{"cmd":"scan"}` | Escaneo automático X+Y. Bloqueante (varios segundos). |
| `{"cmd":"zero"}` | Marca la posición actual como cero. |
| `{"cmd":"stop"}` | Para motores y cancela cualquier move/scan en curso. |
| `{"cmd":"status"}` | Devuelve `pos` inmediatamente. |
| `{"cmd":"ping"}` | Responde `pong`. Keepalive. |

### Eventos (ESP32 → web)

| JSON | Cuándo |
|---|---|
| `{"ev":"ready"}` | Al arrancar tras conectar. |
| `{"ev":"pos","x":..,"y":..,"t":..,"c":{...},"tx":..,"ty":..}` | Cada 500 ms y tras move/zero. `t` = ADC turbina, `c` = longitudes de cable (mm), `tx/ty` = recorrido máximo. |
| `{"ev":"scan_start"}` / `{"ev":"scan_done","x":..,"y":..}` | Inicio y fin de escaneo. |
| `{"ev":"zero"}` | Cero marcado. |
| `{"ev":"pong"}` | Respuesta a `ping`. |
| `{"ev":"error","msg":"..."}` | Error (JSON malformado, comando inválido, excepción). |

## Seguridad y fail-safe

Tres capas:

1. **Deadline por motor (400 ms).** Cada pulso de tensar/soltar desde la web refresca el deadline del motor. Si el navegador deja de enviar pulsos (pestaña cerrada, WiFi caída, móvil bloqueado), el motor se para en < 400 ms.
2. **Desconexión BLE.** El firmware capta el evento `_IRQ_CENTRAL_DISCONNECT` y llama a `parar_todo()` inmediatamente.
3. **Flag `_cancel`.** El comando `stop` lo activa, y los bucles de `mover_a` y `escanear_eje` lo comprueban en cada iteración. Esto permite abortar un `scan` largo desde la web.

Los botones físicos (SCAN, TENSAR, DESTENSAR) y el joystick siguen funcionando en paralelo a la conexión BLE.

## Ajustes de config.json

Añadir opcionalmente:

```json
{
  "ble_name": "AeroBLE"
}
```

Sin ese campo el firmware usa `AeroBLE` por defecto. Si hay varios ESP32 cerca, cambia el nombre para distinguirlos.

Todos los demás campos (`box_*`, `base_*`, `pwm_duty`, etc.) funcionan igual que en la versión WiFi.

## Troubleshooting

**La web dice "tu navegador no soporta Web Bluetooth".**
Usa Chrome, Edge u Opera en Windows/Mac/Linux, o Chrome en Android. Safari/iOS/Firefox no valen.

**Pulso "Conectar" y no aparece `AeroBLE` en la lista.**
- Verifica en el serie del ESP32 que salió `BLE advertising como AeroBLE`.
- En Android, activa permiso de ubicación para el navegador (requisito de escaneo BLE).
- En Windows, asegúrate de que el adaptador Bluetooth está encendido y no hay otra app acaparando la conexión (p. ej. app móvil emparejada).

**Se conecta pero no llegan actualizaciones de posición.**
Mira el log serie. Si el ESP32 no está imprimiendo errores, prueba a pulsar "Marcar cero" — fuerza un `status`. Si el navegador muestra `write err` con `disconnected`, la conexión está caída: reconéctala.

**Los motores se paran solos a cada rato mientras los mantienes pulsados.**
El pulso web se refresca cada 200 ms desde el navegador (ver `HOLD_MS` en `web/index.html`). Si la latencia BLE supera los 400 ms del deadline, el motor se detiene. Causas habituales: distancia excesiva o interferencia 2.4 GHz. Acércate al ESP32.

**`scan` no termina nunca.**
Manda `{"cmd":"stop"}` (botón STOP TODO). El flag `_cancel` aborta el bucle del escaneo.

**Quiero cambiar a la versión WiFi.**
Resube `main.py` al flash en lugar de `main_ble.py`:
```bash
mpremote connect COMx cp main.py :main.py
mpremote connect COMx reset
```

## Cómo extenderlo

Añadir un comando nuevo:

1. **ESP32** — en `procesar_comando()` de `main_ble.py`, añade un `elif cmd == 'foo':` con la lógica y un `ble_send({'ev':'foo_done', ...})`.
2. **Web** — en `web/index.html`, añade un botón y `cmd({cmd:'foo', ...})`, y extiende `handleEvent()` con el nuevo `ev`.

Añadir telemetría adicional: amplía `status_dict()` en `main_ble.py` con las claves nuevas y renderízalas en `handleEvent(o.ev === 'pos')`.
