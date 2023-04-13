#!/bin/bash

[ -d tests/bats/bats-helpers ] && rm -rf tests/bats/bats-helpers

mkdir -p tests/bats-helpers

git clone --depth 1 https://github.com/bats-core/bats-support.git tests/bats/bats-helpers/bats-support || true
git clone --depth 1 https://github.com/bats-core/bats-assert.git tests/bats/bats-helpers/bats-assert || true
git clone --depth 1 https://github.com/bats-core/bats-file.git tests/bats/bats-helpers/bats-file || true