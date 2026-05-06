from microbit import (
    display, Image,
    sleep, button_a, button_b,
    pin13, pin14, pin15, pin16
)

PASO_MS = 120

def fl_wind():    pin13.write_digital(1); pin14.write_digital(0)
def fl_release(): pin13.write_digital(0); pin14.write_digital(1)
def fl_stop():    pin13.write_digital(0); pin14.write_digital(0)

def br_wind():    pin15.write_digital(1); pin16.write_digital(0)
def br_release(): pin15.write_digital(0); pin16.write_digital(1)
def br_stop():    pin15.write_digital(0); pin16.write_digital(0)

def parar_todos(): fl_stop(); br_stop()

display.show(Image.SQUARE)
sleep(500)
display.show(Image.ARROW_N)
sleep(1000)

while True:
    a_pressed = button_a.is_pressed()
    b_pressed = button_b.is_pressed()

    if a_pressed:
        fl_wind(); br_release()
        display.show(Image.ARROW_NW)
        sleep(PASO_MS)
        parar_todos()

    elif b_pressed:
        br_wind(); fl_release()
        display.show(Image.ARROW_SE)
        sleep(PASO_MS)
        parar_todos()

    else:
        display.show(Image.ARROW_N)
        sleep(50)