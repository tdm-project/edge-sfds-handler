#!/usr/bin/env python
#
#  Copyright 2018, CRS4 - Center for Advanced Studies, Research and Development
#  in Sardinia
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

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
from influxdb.exceptions import InfluxDBClientError


MQTT_LOCAL_HOST = "localhost"     # MQTT Broker address
MQTT_LOCAL_PORT = 1883            # MQTT Broker port
INFLUXDB_DB = "luftdaten"         # INFLUXDB database
INFLUXDB_HOST = "localhost"     # INFLUXDB address
INFLUXDB_PORT = 8086            # INFLUXDB port
GPS_LOCATION = "0.0,0.0"        # DEFAULT location


APPLICATION_NAME = 'FEINSTAUB_publisher'

app = flask.Flask(__name__)


class INFLUXDBRequest(flask.Request):
    # accept up to 1kB of transmitted data.
    max_content_length = 1024

    @cached_property
    def get_payload(self):
        _form_content_type = 'application/x-www-form-urlencoded'
        if self.headers.get('content-type') == _form_content_type:
            l_points = []
            v_payload = self.get_data()
            v_points = v_payload.splitlines()
            for _point in v_points:
                l_points.append(
                    dict(
                        zip(
                            ['tag_set', 'field_set', 'timestamp'],
                            _point.decode().split())))

            return l_points


PARAMETERS_MAP = {
    'windSpeed': 'windSpeed',
    'windDir': 'windDirection',
    'rain': 'precipitation',
    'temperature': 'temperature',
    'humidity': 'relativeHumidity',
    'pressure': 'barometricPressure',
    'light': 'illuminance',
    'lat': 'latitude',
    'lon': 'longitude',
    'height': 'altitude',
    'CO': 'CO',
    'NO': 'NO',
    'NO2': 'NO2',
    'NOx': 'NOx',
    'SO2': 'SO2',
    'P1': 'PM10',
    'P2': 'PM2.5'
}


MESSAGE_PARAMETERS = PARAMETERS_MAP.keys()


@app.route("/write", methods=['POST'])
def publish_data():
    v_logger = app.config['LOGGER']

    v_mqtt_local_host = app.config['MQTT_LOCAL_HOST']
    v_mqtt_local_port = app.config['MQTT_LOCAL_PORT']
    v_topic = app.config['MQTT_TOPIC']
    v_influxdb_host = app.config['INFLUXDB_HOST']
    v_influxdb_port = app.config['INFLUXDB_PORT']

    v_latitude = app.config['LATITUDE']
    v_longitude = app.config['LONGITUDE']

    _data = flask.request.get_data()
    _args = flask.request.args.to_dict()
    _auth = flask.request.authorization
    _db = _args.get('db')

    # The required 'db' must match the configured db
    if _db != app.config['INFLUXDB_DB']:
        v_logger.error('Query not allowed: invalid db.')
        _response = flask.make_response('Query not allowed: invalid db.', 400)
        return _response

    if _auth is None:
        _db_username = None
        _db_password = None
    else:
        _db_username = _auth['username']
        _db_password = _auth['password']

    # Ok, a dirty hack
    # In presence of a GPS module, SDFS sends GPS date and time as unquoted
    # strings and they cannot be saved to Influxdb.  Here these values are
    # removed from the message and replaced by a ISO format time string
    _m, _f = _data.decode().split(' ')
    _gps_dts = {
        _i.split('=')[0]: _i.split('=')[1]
        for _i in _f.split(',')
        if _i.startswith('GPS_date') or _i.startswith('GPS_time')
    }

    if _gps_dts:
        _nmea_gps_format = '%m/%d/%Y-%H:%M:%S.%f'
        _nmea_gps_string = '{:s}-{:s}'.format(
            _gps_dts['GPS_date'], _gps_dts['GPS_time'])
        _gps_dt = datetime.datetime.strptime(
            _nmea_gps_string, _nmea_gps_format)
        _influx_gps_time = 'GPS_time="{:%Y-%m-%dT%H:%M:%SZ}"'.format(_gps_dt)

        _new_f = [_i for _i in _f.split(',')
                  if not _i.startswith('GPS_date') and not
                  _i.startswith('GPS_time')]

        _new_f.insert(0, _influx_gps_time)
        _new_f = ','.join(_new_f)
        _data = ' '.join([_m, _new_f])

    try:
        _client = influxdb.InfluxDBClient(
            host=v_influxdb_host,
            port=v_influxdb_port,
            username=_db_username,
            password=_db_password,
            database=_db
        )

        _dbs = _client.get_list_database()
        if _db not in [_d['name'] for _d in _dbs]:
            v_logger.info(
                "InfluxDB database '{:s}' not found. Creating a new one.".
                format(_db))
            _client.create_database(_db)

    except InfluxDBClientError as _iex:
        v_logger.error('InfluDB return code {}: {}'.
                       format(_iex.code, _iex.content.rstrip()))
        _response = flask.make_response(_iex.content, _iex.code)
        return _response

    try:
        v_logger.debug("Insert data into InfluxDB: {:s}".format(str(_data)))
        _result = _client.request(
            'write',
            'POST',
            params=_args,
            data=_data,
            expected_response_code=204)
        _response = flask.make_response(_result.text, _result.status_code)
    except InfluxDBClientError as _iex:
        v_logger.error(_iex)
        _response = flask.make_response(_iex.content, _iex.code)
    except Exception as _ex:
        v_logger.error(_ex)
        _response = flask.make_response(_ex, 400)
    finally:
        _client.close()

    v_messages = []

    try:
        v_payload = flask.request.get_payload

        # Creates a dictionary with the sensor data
        for v_measure in v_payload:
            _sensor_tree = dict()

            _tags = v_measure['tag_set']
            _station_type, _tag = _tags.split(',')
            _, _station_id = _tag.split('=')

            try:
                v_timestamp = v_measure['timestamp']
            except KeyError:
                t_now = datetime.datetime.now().timestamp()
                v_timestamp = int(t_now)

            v_dateObserved = datetime.datetime.fromtimestamp(
                v_timestamp, tz=datetime.timezone.utc).isoformat()

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

                    _sensor_tree[_sensor_model].update(
                        {PARAMETERS_MAP[_parameter]: _value})

            # If GPS data is not present in SFDS message, uses position
            # parameters from config options
            if 'GPS' in _sensor_tree:
                v_latitude = _sensor_tree['GPS']['latitude']
                v_longitude = _sensor_tree['GPS']['longitude']

            # Insofar, one message is sent for each sensor
            for _sensor, _data in _sensor_tree.items():
                if _sensor is 'GPS':
                    continue

                _message = dict()

                _data.update({
                    'timestamp': v_timestamp,
                    'dateObserved': v_dateObserved})
                _data.update({
                    'latitude': v_latitude,
                    'longitude': v_longitude})

                _message["payload"] = json.dumps(_data)
                _message["topic"] = "WeatherObserved/{}.{}".format(
                    _station_id, _sensor)
                _message['qos'] = 0
                _message['retain'] = False

                v_messages.append(_message)

        v_logger.debug(
            "Message topic:\'{:s}\', broker:\'{:s}:{:d}\', "
            "message:\'{:s}\'".format(
                v_topic, v_mqtt_local_host, v_mqtt_local_port,
                json.dumps(v_messages)))
        publish.multiple(v_messages, hostname=v_mqtt_local_host,
                         port=v_mqtt_local_port)
    except socket.error:
        pass

    return _response


def signal_handler(sig, frame):
    sys.exit(0)


def configuration_parser(p_args=None):
    pre_parser = argparse.ArgumentParser(add_help=False)

    pre_parser.add_argument(
        '-c', '--config-file', dest='config_file', action='store',
        type=str, metavar='FILE',
        help='specify the config file')

    args, remaining_args = pre_parser.parse_known_args(p_args)

    v_general_config_defaults = {
        'mqtt_local_host'     : MQTT_LOCAL_HOST,
        'mqtt_local_port'     : MQTT_LOCAL_PORT,
        'logging_level' : logging.INFO,
        'influxdb_db'   : INFLUXDB_DB,
        'influxdb_host' : INFLUXDB_HOST,
        'influxdb_port' : INFLUXDB_PORT,
        'gps_location'  : GPS_LOCATION,
    }

    v_specific_config_defaults = {
    }

    v_config_section_defaults = {
        'GENERAL': v_general_config_defaults,
        APPLICATION_NAME: v_specific_config_defaults
    }

    # Default config values initialization
    v_config_defaults = {}
    v_config_defaults.update(v_general_config_defaults)
    v_config_defaults.update(v_specific_config_defaults)

    if args.config_file:
        _config = configparser.ConfigParser()
        _config.read_dict(v_config_section_defaults)
        _config.read(args.config_file)

        # Filter out GENERAL options not listed in v_general_config_defaults
        _general_defaults = {_key: _config.get('GENERAL', _key) for _key in
                             _config.options('GENERAL') if _key in
                             v_general_config_defaults}

        # Updates the defaults dictionary with general and application specific
        # options
        v_config_defaults.update(_general_defaults)
        v_config_defaults.update(_config.items(APPLICATION_NAME))

    parser = argparse.ArgumentParser(
        parents=[pre_parser],
        description=('Collects data from Luftdaten Fine Dust sensor and '
                     'publish them to a local MQTT broker.'),
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.set_defaults(**v_config_defaults)

    parser.add_argument(
        '-l', '--logging-level', dest='logging_level', action='store',
        type=int,
        help='threshold level for log messages (default: {})'.
        format(logging.INFO))
    parser.add_argument(
        '--mqtt-host', dest='mqtt_local_host', action='store',
        type=str,
        help='hostname or address of the local broker (default: {})'
        .format(MQTT_LOCAL_HOST))
    parser.add_argument(
        '--mqtt-port', dest='mqtt_local_port', action='store',
        type=int,
        help='port of the local broker (default: {})'.format(MQTT_LOCAL_PORT))
    parser.add_argument(
        '--influxdb-host', dest='influxdb_host', action='store',
        type=str,
        help='hostname or address of the influx database (default: {})'
        .format(INFLUXDB_HOST))
    parser.add_argument(
        '--influxdb-port', dest='influxdb_port', action='store',
        type=int,
        help='port of the influx database (default: {})'.format(INFLUXDB_PORT))
    parser.add_argument(
        '--influxdb-db', dest='influxdb_db', action='store',
        type=str,
        help='name of the database to use (default: {})'.format(INFLUXDB_DB))
    parser.add_argument(
        '--gps-location', dest='gps_location', action='store',
        type=str,
        help=('GPS coordinates of the sensor as latitude,longitude '
              '(default: {})').format(GPS_LOCATION))

    args = parser.parse_args(remaining_args)
    return args


def main():
    # Initializes the default logger
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO)
    logger = logging.getLogger(APPLICATION_NAME)

    # Checks the Python Interpeter version
    if (sys.version_info < (3, 0)):
        logger.fatal("This software requires Python version >= 3.0: exiting.")
        sys.exit(-1)

    args = configuration_parser()

    logger.setLevel(args.logging_level)

    signal.signal(signal.SIGINT, signal_handler)

    v_mqtt_topic = 'sensor/' + 'FEINSTAUB'
    v_latitude, v_longitude = map(float, args.gps_location.split(','))

    config_dict = {
        'LOGGER'     : logger,
        'MQTT_LOCAL_HOST'  : args.mqtt_local_host,
        'MQTT_LOCAL_PORT'  : args.mqtt_local_port,
        'LOG_LEVEL'  : args.logging_level,
        'MQTT_TOPIC' : v_mqtt_topic,

        'INFLUXDB_DB' : args.influxdb_db,
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
