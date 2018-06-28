#!/usr/bin/env python

import sys
import json
import flask
import signal
import socket
import logging
import influxdb
import argparse
import datetime
import configparser
import paho.mqtt.publish as publish
from werkzeug.utils import cached_property
from werkzeug.wrappers import Request


MQTT_HOST     = "localhost"     # MQTT Broker address
MQTT_PORT     = 1883            # MQTT Broker port
INFLUXDB_HOST = "localhost"     # INFLUXDB address
INFLUXDB_PORT = 8086            # INFLUXDB port
LOCATION      = "0.0,0.0"       # DEFAULT location


APPLICATION_NAME = 'FEINSTAUB_publisher'

app = flask.Flask(__name__)


class INFLUXDBRequest(flask.Request):
    # accept up to 1kB of transmitted data.
    max_content_length = 1024

    @cached_property
    def get_payload(self):
        if self.headers.get('content-type') == 'application/x-www-form-urlencoded':
            l_points = []
            v_payload = self.get_data()
            v_points = v_payload.splitlines()
            for _point in v_points:
                l_points.append(
                    dict(
                        zip(
                            ['tag_set', 'field_set', 'timestamp'], 
                            _point.decode().split()
                            )
                        )
                    )

            return (l_points)

PARAMETERS_MAP = {
        'windSpeed':   'windSpeed',
        'windDir':     'windDirection',
        'rain':        'precipitation',
        'temperature': 'temperature',
        'humidity':    'relativeHumidity',
        'pressure':    'barometricPressure',
        'light':       'illuminance',
        'lat':         'latitude',
        'lon':         'longitude',
        'height':      'altitude',
        'CO':  'CO',
        'NO':  'NO',
        'NO2': 'NO2',
        'NOx': 'NOx',
        'SO2': 'SO2',
        'P1':  'PM10',
        'P2':  'PM2.5'
}

MESSAGE_PARAMETERS = PARAMETERS_MAP.keys()

@app.route("/write", methods=['POST'])
def publish_data():
    v_logger = app.config['LOGGER']

    v_mqtt_host  = app.config['MQTT_HOST']
    v_mqtt_port  = app.config['MQTT_PORT']
    v_topic = app.config['MQTT_TOPIC']
    v_influxdb_host = app.config['INFLUXDB_HOST']
    v_influxdb_port = app.config['INFLUXDB_PORT']

    v_latitude  = app.config['LATITUDE']
    v_longitude = app.config['LONGITUDE']

    _data = flask.request.get_data()
    _args = flask.request.args.to_dict()
    _db = _args.get('db')

    _client = influxdb.InfluxDBClient(
            host=v_influxdb_host,
            port=v_influxdb_port,
            username='root',
            password='root',
            database=_db
            )

    _dbs = _client.get_list_database()
    if _db not in [_d['name'] for _d in _dbs]:
        v_logger.info("InfluxDB database '{:s}' not found. Creating a new one.".format(_db))
        _client.create_database(_db)

    try:
        _result = _client.request(
                'write',
                'POST',
                params=_args,
                data=_data,
                expected_response_code=204)
        v_logger.debug("Insert data into InfluxDB: {:s}".format(str(_data)))
    except Exception as ex:
        v_logger.error(ex)
    finally:
        _client.close()

    _response = flask.make_response(_result.text, _result.status_code)

    v_messages = []

    try:

        v_payload = flask.request.get_payload


        # Creates a dictionary with the sensor data
        for v_measure in v_payload:
            _sensor_tree = dict()

            _tags   = v_measure['tag_set']
            _station_type, _tag = _tags.split(',')
            _, _station_id = _tag.split('=')

            try:
                v_timestamp    = v_measure['timestamp']
            except KeyError as kex:
                t_now = datetime.datetime.now().timestamp()
                v_timestamp = int(t_now)

            v_dateObserved = datetime.datetime.fromtimestamp(v_timestamp,
                        tz=datetime.timezone.utc).isoformat()

            v_fields = v_measure['field_set'].split(',')

            for v_field in v_fields:
                _sensor, _value = v_field.split('=')

                # Dirty hack done dirty cheap
                # DHT22 does not follow the rule 'sensor'_'measure'
                # Does not affect future fixes in firmware
                if _sensor in ['temperature', 'humidity']:
                    _sensor = 'DHT22_' + _sensor

                _sensor_model, _, _parameter = (_sensor.partition('_'))
                if _parameter in MESSAGE_PARAMETERS:
                    if _sensor_model not in _sensor_tree:
                        _sensor_tree[_sensor_model] = {}

                    _sensor_tree[_sensor_model].update({PARAMETERS_MAP[_parameter]: _value})

            # If GPS data is not present in SFDS message, uses position
            # parameters from config options
            if 'GPS' in _sensor_tree:
                v_latitude  = _sensor_tree['GPS']['latitude']
                v_longitude = _sensor_tree['GPS']['longitude']

            # Insofar, one message is sent for each sensor
            for _sensor, _data in _sensor_tree.items():
                if _sensor is 'GPS':
                    continue

                _message = dict()

                _data.update({'timestamp': v_timestamp, 'dateObserved': v_dateObserved})
                _data.update({'latitude': v_latitude, 'longitude': v_longitude})

                _message["payload"] = json.dumps(_data)
                _message["topic"] = "WeatherObserved/{}.{}".format(_station_id, _sensor)
                _message['qos'] = 0
                _message['retain'] = False
    
                v_messages.append(_message)

        v_logger.debug("Message topic:\'{:s}\', broker:\'{:s}:{:d}\', "
            "message:\'{:s}\'".format(v_topic, v_mqtt_host, v_mqtt_port, json.dumps(v_messages)))
        publish.multiple(v_messages, hostname=v_mqtt_host, port=v_mqtt_port)
    except socket.error:
        pass

    return _response


def signal_handler(sig, frame):
    sys.exit(0)


def main():
    # Initializes the default logger
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    logger = logging.getLogger(APPLICATION_NAME)

    # Checks the Python Interpeter version
    if (sys.version_info < (3, 0)):
        ###TODO: Print error message here
        sys.exit(-1)

    pre_parser = argparse.ArgumentParser(add_help=False)

    pre_parser.add_argument('-c', '--config-file', dest='config_file', action='store',
        type=str, metavar='FILE',
        help='specify the config file')

    args, remaining_args = pre_parser.parse_known_args()

    v_config_defaults = {
        'mqtt_host'     : MQTT_HOST,
        'mqtt_port'     : MQTT_PORT,
        'logging_level' : logging.INFO,
        'influxdb_host' : INFLUXDB_HOST,
        'influxdb_port' : INFLUXDB_PORT,
        'location'      : LOCATION
        }

    v_config_section_defaults = {
        APPLICATION_NAME: v_config_defaults
        }

    if args.config_file:
        v_config = configparser.ConfigParser()
        v_config.read_dict(v_config_section_defaults)
        v_config.read(args.config_file)

        v_config_defaults = dict(v_config.items(APPLICATION_NAME))

    parser = argparse.ArgumentParser(parents=[pre_parser], 
            description='Collects data from Luftdaten Fine Dust sensor and publish them to a local MQTT broker.',
            formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.set_defaults(**v_config_defaults)

    parser.add_argument('-l', '--logging-level', dest='logging_level', action='store', 
        type=int,
        help='threshold level for log messages (default: {})'.format(logging.INFO))
    parser.add_argument('--mqtt-host', dest='mqtt_host', action='store', 
        type=str,
        help='hostname or address of the local broker (default: {})'
            .format(MQTT_HOST))
    parser.add_argument('--mqtt-port', dest='mqtt_port', action='store', 
        type=int,
        help='port of the local broker (default: {})'.format(MQTT_PORT))
    parser.add_argument('--influxdb-host', dest='influxdb_host', action='store', 
        type=str,
        help='hostname or address of the influx database (default: {})'
            .format(INFLUXDB_HOST))
    parser.add_argument('--influxdb-port', dest='influxdb_port', action='store', 
        type=int,
        help='port of the influx database (default: {})'.format(INFLUXDB_PORT))
    parser.add_argument('--location', dest='location', action='store',
        type=str,
        help='GPS coordinates of the sensor as latitude,longitude (default: {})'.format(LOCATION))

    args = parser.parse_args(remaining_args)

    logger.setLevel(args.logging_level)

    signal.signal(signal.SIGINT, signal_handler)

    v_mqtt_topic = 'sensor/' + 'FEINSTAUB'
    v_latitude, v_longitude = map(float, args.location.split(','))

    config_dict = {
            'LOGGER'     : logger,
            'MQTT_HOST'  : args.mqtt_host,
            'MQTT_PORT'  : args.mqtt_port,
            'LOG_LEVEL'  : args.logging_level,
            'MQTT_TOPIC' : v_mqtt_topic,

            'INFLUXDB_HOST' : args.influxdb_host,
            'INFLUXDB_PORT' : args.influxdb_port,

            'LATITUDE'  : v_latitude,
            'LONGITUDE' : v_longitude,
            }

    app.config.from_mapping(config_dict)
    app.request_class = INFLUXDBRequest
    app.run(host='0.0.0.0')

if __name__ == "__main__":
    main()

# vim:ts=4:expandtab
# References:
#   http://blog.vwelch.com/2011/04/combining-configparser-and-argparse.html
