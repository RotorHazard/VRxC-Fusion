# RotorHazard VRx Control for TBS Fusion

This system allows RotorHazard to communicate with TBS Fusion modules, sending race status messages, lap times, and split data in real time to the pilot's OSD.

## Installation and Setup

The system is composed of a RotorHazard plugin and a hardware communicator. Setup of both is required.

### RotorHazard Plugin

RotorHazard 4.0 or later is required.

Install through the "Community Plugins" area within RotorHazard. Alternately, or for earlier versions, copy the `vrx_tbs` directory from inside `custom_plugins` into the plugins directory of your RotorHazard data directory.

### Communicator

The communicator code should be installed on an ESP32. ESP32 development modules are widely available and include a USB interface.

Flash the code to the ESP32 using the Arduino IDE:

* Install [Arduino IDE](https://www.arduino.cc/en/software)
* Install [ESP32 board definitions for Arduino](https://espressif-docs.readthedocs-hosted.com/projects/arduino-esp32/en/latest/installing.html)
* Plug in the ESP32 module
* Load the code from `tbs-fusion-vrxc/tbs-fusion-vrxc.ino`
* Select the proper board and port from the dropdown in the toolbar (Try ESP32 Dev Module if not sure)
* Select "Upload" (right arrow button) in the toolbar

_The development code contains defines to enable an OLED display and serial debug monitoring. It is not recommended to install support for or enable these features unless you will be working on the code, as they considerably reduce performance of the communications module._

Plug the flashed module into the timer via any USB port and restart RotorHazard. The plugin will automatically detect the connected module on startup. If this step is successful, `Found Fusion comms module at [address]` will appear in the log.

## Usage

### For Pilots

Update the TBS Fusion module to at least v2.30 and the Fusion WiFi to at least v2.06.

Enable ESPNOW communication on the Fusion Wifi module.
* Open menu
* Select `Settings`
* Select `CRSF`
* Select `Fusion WiFi`
* Select `Pro`
* Change `ESP NOW` to `Enable`
* Exit the menu
* Restart the Fusion

Find your MAC address to give to the race director.
* Ensure WiFi is ON (`Menu` -> `Settings` -> `WiFi`)
* Using any WiFi-capable device, (phone, laptop,) view the available network list. Find the network name beginning with `tbs_fusion_`. 
* The 12-character code at the end of the network name is the MAC address.

For example, if the network name is `tbs_fusion_ABCDEF123456`, then your MAC Address is `ABCDEF123456`.

### For Race Directors

The Fusion plugin will add a `Fusion MAC Address` data field to each pilot in the `Pilots` panel of the `Format` page. For each pilot, fill this field with the 12-character MAC Address provided by the pilot. (Valid hex characters are digits 0–9 and letters a–f).

If you have trouble with automatic detection of the communicator module, enter a
**Manual Port Override** in the Fusion panel on the `Settings` page and click
**Run Port Assignment**. A restart is not required. For example, a Linux path
such as `/dev/serial/by-path/platform-3f980000.usb-usb-0:1.1.2:1.0-port0`
identifies a physical USB port; keep the Fusion communicator in that port.
Confirm the path belongs to Fusion, especially when an ELRS backpack is also
connected.

A configured path is used exclusively. Fusion opens it at 921600 baud and
checks for the communicator's identity response before reporting ready. If the
device is not available or does not respond, the plugin makes up to five
attempts with two seconds between failures. Each probe also allows two seconds
for device startup, with one-second read and write timeouts. Connection attempts
run in the background; repeated button clicks do not start overlapping scans.

Leave the override empty for one automatic scan. Automatic detection skips
`/dev/ttyAMA0`, `/dev/ttyAMA10`, and `COM1`; it does not repeatedly probe every
serial device. Use distinct explicit paths for Fusion and ELRS to avoid both
plugins scanning the same devices.

Startup and manual attempts show **Fusion connected at ...** or **Failed to
connect to Fusion ...** notifications. Individual retries are recorded in the
server log. A serial send failure clears the ready state, closes the port, and
shows **Fusion connection lost ...** once. After reconnecting the hardware,
click **Run Port Assignment** to reconnect; there is no continuous hotplug
monitor or automatic replay of missed OSD messages.

On RotorHazard versions supporting persistent settings, the port is stored in
`config.json` under `VRX_TBS.tbs_comms_port`. An existing value is preserved;
when the key is first created, an older database port setting supplies its
default. Older hosts retain database storage. Clearing a persistent override
selects automatic detection even if the old database value still exists.

## Development tests

With `pytest`, `gevent`, and `pyserial` installed, run:

```sh
python -m pytest tests
```

The tests simulate serial hardware and exercise actual background greenlets;
physical cold-start and OSD checks are still needed before deployment.
