#!/bin/bash
set -e

echo "=== 启动 grafana ==="
sudo docker run -d -p 3000:3000 --name=grafana grafana/grafana-oss

echo "=== 启动 node exporter ==="
sudo docker run -d \
  --name node-exporter \
  --net host \
  --restart always \
  prom/node-exporter

echo "=== 启动 dcgm exporter ==="
sudo docker run -d \
  --name dcgm-exporter \
  --net host \
  --privileged \
  --runtime nvidia \
  --restart always \
  nvidia/dcgm-exporter:latest

echo "=== 启动 prometheus ==="
sudo docker run -d \
  --name prometheus \
  -p 9090:9090 \
  --restart always \
  -v /home/ubuntu/savant_work/savant_coursework/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus