# TDM Edge SFDS Station Handler
In [TDM Edge Gateway Reference Architecture](http://www.tdm-project.it/en/) the handler of the remote weather station is named ***Feinstaub Publisher*** after the name of the weather and air quality station adopted. 

Since this station sends its data via WiFi in a format and protocol suitable for ingestion in an InfluxDB database, the handler simulates a listening InfluxDB server and intercepts the incoming data. 

These data are then entered into the local InfluxDB database for subsequent consultation by the other microservices and at the same time converted into a standard message that is sent to the local MQTT broker for event management or forwarding to the outside.

## Configurations
Settings are retrieved from both configuration file and command line.
Values are applied in the following order, the last overwriting the previous:

1. configuration file section '***GENERAL***' for the common options (logging, local MQTT broker...);
2. configuration file section '***FEINSTAUB\_publisher***' for both common and specific options;
3. command line options.

### Configuration file

###  The options *mqtt\_host* and *mqtt\_port* now are deprecated and no longer recognized. *mqtt\_local\_host* and *mqtt\_local\_port* must be used instead.

* **mqtt\_local\_host**

	hostname or address of the local broker (default: *localhost*) 

* **mqtt\_local\_port**

	port of the local broker (default: *1883*)

* **logging\_level**

   threshold level for log messages (default: *20*)
* **influxdb\_host**

   hostname or address of the influx database (default: *localhost*)
* **influxdb\_port**

   port of the influx database (default: *8086*)
* **influxdb\_db**

   the name of the influx database to use (default: *luftdaten*)
* **gps\_location**

   GPS coordinates of the sensor as latitude,longitude (default: *0.0,0.0*)

When a settings is present both in the *GENERAL* and *application specific*  section, the application specific is applied to the specific handler.

#### Options accepted in GENERAL section
* **mqtt\_local\_host**
* **mqtt\_local\_port**
* **influxdb\_host**
* **influxdb\_port**
* **logging\_level**
* **gps\_location**

In this example, the *logging\_level* settings is overwritten to *1* only for this handler, while other handlers use *0* from the section *GENERAL*:

```ini
[GENERAL]
mqtt_local_host = mosquitto
mqtt_local_port = 1883
influxdb_host = influxdb
influxdb_port = 8086
gps_location=0.0,0.0
logging_level = 0

[FEINSTAUB_publisher]
logging_level = 1
```

### Command line
*  **-h, --help**

   show this help message and exit
*  **-c FILE, --config-file FILE**

   specify the config file
*  **-l LOGGING\_LEVEL, --logging-level LOGGING\_LEVEL**

   threshold level for log messages (default: *20*)
*  **--mqtt-host MQTT\_HOST**

   hostname or address of the local broker (default: *localhost*)
*  **--mqtt-port MQTT\_PORT**

   port of the local broker (default: *1883*)
*  **--i2c-bus I2C\_BUS**

   I2C bus number to which the sensor is attached (default: *1*)
*  **--interval INTERVAL**

   interval in seconds for data acquisition and publication (default: *60 secs*)
*  **--influxdb-host INFLUXDB\_HOST**

   hostname or address of the influx database (default: *localhost*)
*  **--influxdb-port INFLUXDB\_PORT**

   port of the influx database (default: *8086*)
*  **--influxdb-db INFLUXDB\_DB**

   name of the database to use (default: *luftdaten*)
*  **--gps-location GPS\_LOCATION**

   GPS coordinates of the sensor as latitude,longitude (default: *0.0,0.0*)
