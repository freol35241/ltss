#!/usr/bin/env bats

load "./bats-helpers/bats-support/load"
load "./bats-helpers/bats-assert/load"
load "./bats-helpers/bats-file/load"

_start_db_container () {
    # Start a container running the db instance
    docker run -d \
        --name db \
        -e POSTGRES_HOST_AUTH_METHOD=trust \
        -p 5432:5432 \
        "$1"

    # Give it some slack time to start approprietly
    sleep 5

    echo "Container with db instance (using ${1}) started!"
}

_kill_and_remove_containers () {
    (docker ps -aq | xargs docker stop | xargs docker rm) || :
}

_run_hass () {

    config_dir="$1"

    # Start home assistant in a background process
    echo "Starting HA with configuration directory: ${config_dir}"
    hass --skip-pip -c "$config_dir" 3>&- 2>&1 & hass_pid=$!

    sleep 1

    # Listen for successful startup (allowing maximum 120 seconds) by tailing the log file
    tail -f "${config_dir}/home-assistant.log" | timeout 120s grep --line-buffered -m 1 "Home Assistant initialized in"

    # Kill the subprocess
    kill "$hass_pid"

    # Read log file
    local logs
    logs="$(cat "${config_dir}/home-assistant.log")"
    echo "$logs"
}

setup() {
    REPO_ROOT="$( cd "$( dirname "$BATS_TEST_FILENAME" )"/../.. >/dev/null 2>&1 && pwd )"
    TMP_HA_CONFIG_DIR="$(temp_make)"
    echo "#" "$(pip list 2>&1 | grep '^homeassistant')"
}

teardown() {
    temp_del "$TMP_HA_CONFIG_DIR"
    _kill_and_remove_containers
}

@test "HA successful startup using LTSS (TSDB: yes ; POSTGIS: yes)" {

    _start_db_container "timescale/timescaledb-ha:pg15.2-ts2.10.1-latest"

    # Setup configuration directory
    cp "${REPO_ROOT}/tests/bats/config/configuration.yaml" "${TMP_HA_CONFIG_DIR}/"
    cp -r "${REPO_ROOT}/custom_components/" "${TMP_HA_CONFIG_DIR}/"

    run _run_hass "${TMP_HA_CONFIG_DIR}"

    echo "$output"

    # First of all, HA must have started successfully
    assert_line --partial "Home Assistant initialized in"

    # Secondly, lets check that LTSS was setup as expected
    assert_line --partial "We found a custom integration ltss which has not been tested by Home Assistant."
    assert_line --partial "Creating LTSS table"
    assert_line --partial "PostGIS extension is available, activating location extraction..."
    assert_line --partial "TimescaleDB extension is available, creating hypertable..."
    assert_line --partial "Setup of domain ltss took"
}

@test "HA successful startup using LTSS (TSDB: no ; POSTGIS: no)" {

    _start_db_container "postgres:15.2"

    # Setup configuration directory
    cp "${REPO_ROOT}/tests/bats/config/configuration.yaml" "${TMP_HA_CONFIG_DIR}/"
    cp -r "${REPO_ROOT}/custom_components/" "${TMP_HA_CONFIG_DIR}/"

    run _run_hass "${TMP_HA_CONFIG_DIR}"

    echo "$output"

    # First of all, HA must have started successfully
    assert_line --partial "Home Assistant initialized in"

    # Secondly, lets check that LTSS was setup as expected
    assert_line --partial "We found a custom integration ltss which has not been tested by Home Assistant."
    assert_line --partial "Creating LTSS table"
    refute_line --partial "PostGIS extension is available, activating location extraction..."
    refute_line --partial "TimescaleDB extension is available, creating hypertable..."
    assert_line --partial "Setup of domain ltss took"
}

@test "HA successful startup using LTSS (TSDB: no ; POSTGIS: yes)" {

    _start_db_container "postgis/postgis:15-3.3"

    # Setup configuration directory
    cp "${REPO_ROOT}/tests/bats/config/configuration.yaml" "${TMP_HA_CONFIG_DIR}/"
    cp -r "${REPO_ROOT}/custom_components/" "${TMP_HA_CONFIG_DIR}/"

    run _run_hass "${TMP_HA_CONFIG_DIR}"

    echo "$output"

    # First of all, HA must have started successfully
    assert_line --partial "Home Assistant initialized in"

    # Secondly, lets check that LTSS was setup as expected
    assert_line --partial "We found a custom integration ltss which has not been tested by Home Assistant."
    assert_line --partial "Creating LTSS table"
    assert_line --partial "PostGIS extension is available, activating location extraction..."
    refute_line --partial "TimescaleDB extension is available, creating hypertable..."
    assert_line --partial "Setup of domain ltss took"
}

@test "HA successful startup using LTSS (TSDB: yes ; POSTGIS: no)" {

    _start_db_container "timescale/timescaledb:2.10.1-pg15"

    # Setup configuration directory
    cp "${REPO_ROOT}/tests/bats/config/configuration.yaml" "${TMP_HA_CONFIG_DIR}/"
    cp -r "${REPO_ROOT}/custom_components/" "${TMP_HA_CONFIG_DIR}/"

    run _run_hass "${TMP_HA_CONFIG_DIR}"

    echo "$output"

    # First of all, HA must have started successfully
    assert_line --partial "Home Assistant initialized in"

    # Secondly, lets check that LTSS was setup as expected
    assert_line --partial "We found a custom integration ltss which has not been tested by Home Assistant."
    assert_line --partial "Creating LTSS table"
    refute_line --partial "PostGIS extension is available, activating location extraction..."
    assert_line --partial "TimescaleDB extension is available, creating hypertable..."
    assert_line --partial "Setup of domain ltss took"
}

@test "Testing any migrations that needs performing since last release" {

    _start_db_container "timescale/timescaledb:2.10.1-pg15"

    # Setup configuration directory using a freshly checked out version of ltss (latest version)
    cp "${REPO_ROOT}/tests/bats/config/configuration.yaml" "${TMP_HA_CONFIG_DIR}/"
    latest_release=$(git describe --tags --abbrev=0)
    tmp_clone_dir="$(temp_make)"
    git clone --depth 1 --branch "${latest_release}" 'https://github.com/freol35241/ltss.git' "${tmp_clone_dir}"
    cp -r "${tmp_clone_dir}/custom_components/" "${TMP_HA_CONFIG_DIR}/"
    rm -rf "$tmp_clone_dir"

    echo "Running HA using LTSS: ${latest_release}"

    run _run_hass "${TMP_HA_CONFIG_DIR}"

    echo "$output"

    # First of all, HA must have started successfully
    assert_line --partial "Home Assistant initialized in"

    # Secondly, lets check that LTSS was setup as expected
    assert_line --partial "We found a custom integration ltss which has not been tested by Home Assistant."
    assert_line --partial "Creating LTSS table"
    assert_line --partial "Setup of domain ltss took"

    # Now, lets replace the custom component with the current version of ltss
    cp -r "${REPO_ROOT}/custom_components/" "${TMP_HA_CONFIG_DIR}/"

    # And run HA again
    current_commit_hash=$(git rev-parse --short HEAD)
    echo "Running HA using LTSS: ${current_commit_hash}"
    run _run_hass "${TMP_HA_CONFIG_DIR}"

    echo "$output"

    # First of all, HA must have started successfully
    assert_line --partial "Home Assistant initialized in"

    # Secondly, lets check that LTSS was setup as expected
    assert_line --partial "We found a custom integration ltss which has not been tested by Home Assistant."
    assert_line --partial "Setup of domain ltss took"
    refute_line --partial "ERROR (LTSS)"
}