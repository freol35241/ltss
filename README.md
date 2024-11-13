Long time state storage (LTSS) custom component for Home Assistant
========================================

**NOTE:** From version 2.0 LTSS requires at least Home Assistant 2023.3

**NOTE:** Starting 2020-09-13 attributes are stored with type JSONB instead of as a plain string, in addition a GIN index is created on this column by default. At first startup after updating of LTSS, migration of your DB happens automatically. Note that this can take a couple of minutes and HASS will not finish starting (i.e. frontend will not be available) until migration is done.

**WARNING:** I take no responsibility for any data loss that may happen as a result of this. Please make sure to backup your data before upgrading!

----

Enabling simple long time state storage (LTSS) for your sensor states in a PostgreSQL database.

The following extensions are required for full functionality:
* TimescaleDB
* PostGIS

LTSS automatically detects the available extensions and creates the necessary table accordingly. A PostgeSQL instance without those extensions can be used but will lack some features: efficient storing and accessing time-series data (without TimescaleDB) and directly accessing geolocation data of logged data (without PostGis).

This component is not to be considered as a replacement to the recorder component in Home Assistant but rather as an alternative to the InfluxDB component for more space-efficient long time storage of specific sensor states.

Nice to know:
* Fully SQL compatible -> works with the [SQL sensor](https://www.home-assistant.io/integrations/sql/) in Home Assistant
* Compatible with Grafana for visualization of time series:
    * https://blog.timescale.com/blog/grafana-time-series-exploration-visualization-postgresql-8c7baa9c3bfe/
    * https://grafana.com/docs/grafana/latest/features/datasources/postgres/

## Installation

Precondition
* Make sure that you PostgreSQL instance is up and running and that you have created a database, ```DB_NAME```. 
* I recommend the following docker image (includes postgis): https://hub.docker.com/r/timescale/timescaledb-ha to get started quickly and easy.
* If you are using an armv7-system (like raspberry pi) you can find a precompiled docker-image [here](https://hub.docker.com/repository/docker/dekiesel/timescaledb-postgis).


Manual installation:
* Put the ```ltss``` folder from ```custom_components``` folder in this repo to a folder named ```custom_components``` in your HA config folder

Automatic installation:
* Just install ltss as an integration via [HACS](https://hacs.xyz/)


configuration.yaml
* Add a section to your HA configuration.yaml:

        ltss:
            db_url: postgresql://USER:PASSWORD@HOST_ADRESS/DB_NAME
            chunk_time_interval: 2592000000000
            include:
                domains:
                - sensor
                entities:
                - person.john_doe

**NOTE**: During the initial startup of the component, the extensions will be created on the specified database. This requires superuser priviligies on the PostgreSQL instance. Once the extensions are created, a user without superuser rights can be used! Ref: https://community.home-assistant.io/t/can-i-use-timescale-db-as-an-alternative-to-influx-db-in-homeassistant-for-grafana/120517/11

## Configuration

    ltss
    (map)(Required) 
    Enables the recorder integration. Only allowed once.

        db_url
        (string)(Required)
        The URL that points to your database.

        db_retry_wait
        (float)(Optional)
        Time to wait between DB reconnects.

        db_retry_limit
        (int)(Optional)
        Max number of times to retry DB reconnect on startup. Defaults to 10. If set to `null` (without quotes) LTSS will try to reconnect to the DB indefinitely. Note that this setting applies only to LTSS startup; during normal operation LTSS will retry 10 times and then drop the write to prevent filling up the internal queue.

        chunk_time_interval
        (int)(Optional)
        The time interval to be used for chunking in TimescaleDB in microseconds. Defaults to 2592000000000 (30 days). Ignored for databases without TimescaleDB extension.

        exclude
        (map)(Optional)
        Configure which integrations should be excluded from recordings.

            domains
            (list)(Optional)
            The list of domains to be excluded from recordings.

            entities
            (list)(Optional)
            The list of entity ids to be excluded from recordings.

            entity_globs:
            (list)(Optional)
            Exclude all entities matching a listed pattern from recordings (e.g., `sensor.weather_*`).

        include
        (map)(Optional)
        Configure which integrations should be included in recordings. If set, all other entities will not be recorded.

            domains
            (list)(Optional)
            The list of domains to be included in the recordings.

            entities
            (list)(Optional)
            The list of entity ids to be included in the recordings.

            entity_globs:
            (list)(Optional)
            Include all entities matching a listed pattern from recordings (e.g., `sensor.weather_*`).

## Details
The states are stored in a single table ([hypertable](https://docs.timescale.com/latest/using-timescaledb/hypertables), when TimescaleDB is available) with the following layout:

| Column name: | time | entity_id | state | attributes | location [PostGIS-only] |
|:---:|:---:|:---:|:---:|:---:|:-----------------------:|
| Type: | timestamp with timezone | string | string | JSONB |       POINT(4326)       |
| Primary key: | x | x |  |  |  |
| Index: | x | x | x | x |                         |

### Only available with TimescaleDB:
[Chunk size](https://docs.timescale.com/latest/using-timescaledb/hypertables#best-practices) of the hypertable is configurable using the `chunk_time_interval` config option. It defaults to 2592000000000 microseconds (30 days).

### Only available with PosttGIS:
The location column is populated for those states where ```latitude``` and ```longitude``` is part of the state attributes.

## Credits
Big thanks to the authors of the [recorder component](https://github.com/home-assistant/home-assistant/tree/dev/homeassistant/components/recorder) for Home Assistant for a great starting point code-wise!
