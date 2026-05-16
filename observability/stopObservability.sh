#!/bin/bash
set -e

echo "=== 停止 grafana ==="
sudo docker stop grafana

echo "=== 停止 node exporter ==="
sudo docker stop node-exporter

echo "=== 停止 dcgm exporter ==="
sudo docker stop dcgm-exporter

echo "=== 停止 prometheus ==="
sudo docker stop prometheus