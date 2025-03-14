# RotorHazard VRx Control for TBS Fusion

This system allows RotorHazard to communicate with TBS Fusion modules, sending race status messages, lap times, and split data in real time to the pilot's OSD.

## Installation and Setup

The system is composed of a RotorHazard plugin and a hardware communicator. Setup of both is required.

### RotorHazard Plugin

RotorHazard 4.0 or later is required.

Install through the "Community Plugins" area within RotorHazard. Alternately, copy the `vrx_tbs` plugin into the plugins directory of your RotorHazard data directory.

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

If you have trouble with automatic detection of the communicator module, you may retry or specify a manual port override in the corresponding panel on the `Settings` page. A restart is not required when setting a manual port.
