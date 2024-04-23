#!/bin/bash
# Copyright (c) 2021 José Manuel Barroso Galindo <theypsilon@gmail.com>

./build_hash_db.py
RET=$?
set -euo pipefail
cat "${DB_FILE}"
git config --global user.email "theypsilon@gmail.com"
git config --global user.name "The CI/CD Bot"
git pull origin main
git add "${DB_FILE}"
git commit -m "${DB_FILE}" || true
git push origin main
exit ${RET}
