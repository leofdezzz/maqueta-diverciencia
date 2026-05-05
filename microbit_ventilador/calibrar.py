from microbit import pin1, display, sleep

while True:
    raw = pin1.read_analog()
    display.scroll(str(raw))
    sleep(500)