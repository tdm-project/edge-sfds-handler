Build docker image with:
```
docker build . -f docker/Dockerfile -t tdm/feinstaub_publisher
```

Config file example:

```
[FEINSTAUB_publisher]
mqtt_host = mosquitto
mqtt_port = 1883
logging_level = 0
influxdb_host = influxdb
influxdb_port = 8086
```
