
Enabling simple long time state storage (LTSS) for your sensor states. Requires a PostgreSQL instance with the following extensions:
* TimescaleDB
* PostGIS

This component is not to be considered as a replacement to the recorder component in Home Assistant but rather as an alternative to the InfluxDB component for more space-efficient long time storage of specific sensor states.

Nice to know:
* Fully SQL compatible -> works with the [SQL sensor](https://www.home-assistant.io/integrations/sql/) in Home Assistant
* Compatible with Grafana for visualization of time series:
    * https://blog.timescale.com/blog/grafana-time-series-exploration-visualization-postgresql-8c7baa9c3bfe/
    * https://grafana.com/docs/grafana/latest/features/datasources/postgres/

## Installation

Precondition
* Make sure that you PostgreSQL instance is up and running and that you have created a database, ```DB_NAME```. I recommend the following docker image: https://docs.timescale.com/v1.0/getting-started/installation/docker/installation-docker#postgis-docker to get started quickly and easy.

Manual installation:
* Put the ltss folder from ```custom_components``` folder in this repo to a folder named ```custom_components``` in your HA config folder
Automatic installation:
* Just install ltss as an integration via [HACS](https://hacs.xyz/)

configuration.yaml
* Add a section to your HA configuration.yaml:

        ltss:
            db_url: postgresql://USER:PASSWORD@HOST_ADRESS/DB_NAME
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

        exclude
        (map)(Optional)
        Configure which integrations should be excluded from recordings.

            domains
            (list)(Optional)
            The list of domains to be excluded from recordings.

            entities
            (list)(Optional)
            The list of entity ids to be excluded from recordings.

        include
        (map)(Optional)
        Configure which integrations should be included in recordings. If set, all other entities will not be recorded.

            domains
            (list)(Optional)
            The list of domains to be included in the recordings.

            entities
            (list)(Optional)
            The list of entity ids to be included in the recordings.

## Details
The states are stored in a single [hypertable](https://docs.timescale.com/latest/using-timescaledb/hypertables) with the following layout:

| Column name: | id | time | entity_id | state | attributes | location |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| Type: | bigint | timestamp with timezone | string | string | string | POINT(4326) |
| Primary key: | x | x |  |  |  |
| Index: | x | x | x | x | | |

[Chunk size](https://docs.timescale.com/latest/using-timescaledb/hypertables#best-practices) of the hypertable is set to 1 month.

The location column is only populated for those states where ```latitude``` and ```longitude``` is part of the state attributes.

## Credits
Big thanks to the authors of the [recorder component](https://github.com/home-assistant/home-assistant/tree/dev/homeassistant/components/recorder) for Home Assistant for a great starting point code-wise!