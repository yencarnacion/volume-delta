#!/bin/bash

if [ -z "$1" ]; then
  echo "Usage: $0 STOCK_TICKER"
  exit 1
fi

poetry run python vd.py "$1"
