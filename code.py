import os
import microcontroller
import socketpool
import wifi
import digitalio
import board
import adafruit_ccs811
import adafruit_dht
import busio
import time

from adafruit_httpserver import (
    Server,
    REQUEST_HANDLED_RESPONSE_SENT,
    Request,
    FileResponse,
    JSONResponse,
    Response,
)

class CO2Level():
    def __init__(self, level):
        self.level = level
        if self.level == 0:
            self.name = "green"
            self.lights = (False, False, True)
        elif self.level == 1:
            self.name = "yellow"
            self.lights = (False, True, False)
        elif self.level == 2:
            self.name = "red"
            self.lights = (True, False, False)

class PlotData():
    data = []

    def add_data(self, index, co2):
        if co2 is None:
            return
        if len(self.data) > 120:
            self.data.pop(0)
        self.data.append([index, co2, 1000, 2000])

    @property
    def data_str(self):
        return ',\n\t\t'.join(str(x) for x in self.data)


def get_co2_level(co2):
    if co2 < 1000:
        return CO2Level(0)
    elif co2 < 2000:
        return CO2Level(1)    
    else:
        return CO2Level(2)    


def render_html(
    led,
    ccs811,
    dht,
    plot_data,
):
    state = "ON" if led.value else "OFF"
    nstate = "off" if led.value else "on"
    co2=ccs811.eco2
    co2_level=get_co2_level(co2)
    with open("static/index.html", "r") as f:
        html = f.read().format(
            state=state,
            nstate=nstate,
            cpu_temperature=microcontroller.cpu.temperature,
            co2=co2,
            tvoc=ccs811.tvoc,
            co2_level=co2_level.name,
            temperature=dht.temperature,
            humidity=dht.humidity,
            plot_data=plot_data.data_str,
        )
    return html

def i2c_setup():
    i2c = busio.I2C(scl=board.GP1, sda=board.GP0)
    ccs811 = adafruit_ccs811.CCS811(i2c)
    return ccs811

def traffic_light_setup():
    lights = [digitalio.DigitalInOut(board.GP13), 
              digitalio.DigitalInOut(board.GP12), 
              digitalio.DigitalInOut(board.GP11)]
    for light in lights:
        light.direction = digitalio.Direction.OUTPUT
    return lights

def connect(ccs811, dht, led, plot_data):
    pool = socketpool.SocketPool(wifi.radio)
    server = Server(pool, "static", debug=True)

    def render_response(request):
        return Response(request, render_html(led, ccs811, dht, plot_data), content_type="text/html")

    @server.route("/")
    def base(request: Request):
        """
        Serve the default index.html file.
        """
        return render_response(request)

    @server.route("/lighton")
    def lighton(request: Request):
        """
        Serve the default index.html file.
        """
        led.value = True
        return render_response(request)

    @server.route("/lightoff")
    def lightoff(request: Request):
        """
        Serve the default index.html file.
        """
        led.value = False
        return render_response(request)

    @server.route("/cpu-information", append_slash=True)
    def cpu_information(request: Request):
        """
        Serve the default index.html file.
        """
        data = {
            'temperature': microcontroller.cpu.temperature,
            'frequency': microcontroller.cpu.frequency,
            'voltage': microcontroller.cpu.voltage,
        }
        return JSONResponse(request, data)

    # Start the server.
    wifi.radio.connect(os.getenv("WIFI_SSID"), os.getenv("WIFI_PASSWORD"))
    server.start(str(wifi.radio.ipv4_address))
    return server


def serve(server, ccs811, lights, led, plot_data):
    MEASUREMENT_INTERVAL = 2.0
    DATA_SNAPSHOT_INTERVAL = 60.0
    LAST_MEASUREMENT = -1
    LAST_SNAPSHOT_DATA = -1
    RELOADER = 0
    co2 = ccs811.eco2
    now = time.monotonic()
    while not ccs811.data_ready:
        pass
    plot_data.add_data(now, co2)
    while True:
        try:
            # Do something useful in this section,
            # for example read a sensor and capture an average,
            # or a running total of the last 10 samples

            # Process any waiting requests
            now = time.monotonic()
            if now >= LAST_MEASUREMENT + MEASUREMENT_INTERVAL:
                co2 = ccs811.eco2
                co2_level = get_co2_level(co2)
                for i in range(3):
                    if led.value:
                        lights[i].value = co2_level.lights[i]
                    else:
                        lights[i].value = False
                LAST_MEASUREMENT = now
            if now >= LAST_SNAPSHOT_DATA + DATA_SNAPSHOT_INTERVAL:
                plot_data.add_data(now, co2)
                LAST_SNAPSHOT_DATA = now
            pool_result = server.poll()
            if pool_result == REQUEST_HANDLED_RESPONSE_SENT:
                pass
                # Do something only after handling a request
            # If you want you can stop the server by calling server.stop() anywhere in your code
        except OSError as error:
            print(error)
            continue

if __name__ == '__main__':
    ccs811 = i2c_setup()
    dht = adafruit_dht.DHT22(board.GP15)
    led = digitalio.DigitalInOut(board.LED)
    led.direction = digitalio.Direction.OUTPUT
    led.value = True
    plot_data = PlotData()
    server = connect(ccs811, dht, led, plot_data)
    lights = traffic_light_setup()
    try:
        serve(server, ccs811, lights, led, plot_data)
    except KeyboardInterrupt:
        server.stop()
