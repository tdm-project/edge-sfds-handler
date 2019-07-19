DOCKER_IMAGE_VERSION=1.0.0
DOCKER_IMAGE_NAME=tdmproject/edge-sfds-handler
DOCKER_IMAGE_TAGNAME=$(DOCKER_IMAGE_NAME):$(DOCKER_IMAGE_VERSION)

default: build

build:
	docker build --target=final -f docker/Dockerfile -t $(DOCKER_IMAGE_TAGNAME) .
	docker tag $(DOCKER_IMAGE_TAGNAME) $(DOCKER_IMAGE_NAME):latest

push:
	docker push $(DOCKER_IMAGE_TAGNAME)
	docker push $(DOCKER_IMAGE_NAME)

test:
	docker build --target=testing -f docker/Dockerfile -t $(DOCKER_IMAGE_TAGNAME)-testing .
	docker run --rm --entrypoint=tests/entrypoint.sh $(DOCKER_IMAGE_TAGNAME)-testing
