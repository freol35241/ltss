TimescaleDB custom component for Home Assistant
========================================

Enabling simple long time state storage (LTSS) for your sensors.

Requires a PostgreSQL instance with the following extensions:
* TimescaleDB
* PostGIS

I recommend the following docker image: https://docs.timescale.com/v1.0/getting-started/installation/docker/installation-docker#postgis-docker

## Installation

* Make sure that you PostgreSQL instance is up and running and that you have created a database.
* Put this repo in a folder named ```custom_components``` in your HA config folder
* Add a section to your HA configuration.yaml:

        tsdb:
        db_url: postgresql://USER:PASSWORD@HOST_ADRESS/DB_NAME
        include:
            domains:
            - sensor
            entities:
            - person.john_doe
