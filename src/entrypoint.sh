#!/bin/bash

cd ${APP_HOME}
. venv/bin/activate
python src/feinstaub_publisher.py $@
