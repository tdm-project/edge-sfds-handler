FROM ubuntu:latest

ENV APP_HOME=/opt/feinstaub/

# Install required packages
RUN apt-get update && \
	apt-get -y install python3-pip python3-dev && \
	pip3 install virtualenv

RUN \
	mkdir -p ${APP_HOME} && \
	cd ${APP_HOME} && \
	virtualenv venv && \
	. venv/bin/activate && \
	pip3 install flask paho-mqtt influxdb

WORKDIR ${APP_HOME}
COPY src src

EXPOSE 5000

ENTRYPOINT ["src/entrypoint.sh"]

CMD [ "-c", "/opt/tdm.conf" ]
