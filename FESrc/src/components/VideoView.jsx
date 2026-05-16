import { useState, useRef, useEffect, useCallback } from "react";
import { Row, Col, Button, Space, Card, Empty } from "antd";
import {
  BorderOutlined,
  BorderInnerOutlined,
  BorderTopOutlined,
  BorderBottomOutlined,
  WarningOutlined,
} from "@ant-design/icons";

export const VideoView = () => {
  const videoStreams = window.VIDEO_STREAMS_CONFIG || [];
  const streamHost = window.location.hostname || "127.0.0.1";
  const streamPort = 8080;

  const players = useRef({});
  const MAX_GRID = 16;
  const [splitMode, setSplitMode] = useState(9);

  // ===================== 新增：摄像头状态 =====================
  const [cameraStatus, setCameraStatus] = useState({});

  // 获取单个摄像头状态
  const fetchCameraStatus = useCallback(async (cameraId) => {
    if (!cameraId) return;
    try {
      const res = await fetch(`/api/v1/vqd/status?camera_id=${cameraId}`);
      const data = await res.json();
      setCameraStatus((prev) => ({
        ...prev,
        [cameraId]: data,
      }));
    } catch (err) {
      console.error("获取状态失败", cameraId, err);
    }
  }, []);

  // 轮询所有摄像头状态（3秒刷新一次）
  useEffect(() => {
    const cameraIds = videoStreams.map((s) => s.cam).filter(Boolean);
    if (cameraIds.length === 0) return;

    // 立即执行一次
    cameraIds.forEach((cam) => fetchCameraStatus(cam));

    // 定时轮询
    const timer = setInterval(() => {
      cameraIds.forEach((cam) => fetchCameraStatus(cam));
    }, 3000);

    return () => clearInterval(timer);
  }, [videoStreams, fetchCameraStatus]);

  // 分屏模式配置
  const splitModeConfig = {
    1: { rows: 1, cols: 1 },
    4: { rows: 2, cols: 2 },
    9: { rows: 3, cols: 3 },
    16: { rows: 4, cols: 4 },
  };

  // 初始化播放
  const playVideo = useCallback(
    (domId, stream) => {
      if (!domId || !stream) return;
      if (players.current[domId]) return;

      const streamUrl = `http://${streamHost}:${streamPort}${stream}`;
      const domEle = document.getElementById(domId);
      if (!domEle || !window.flvjs) return;

      const config = {
        type: "flv",
        url: streamUrl,
        isLive: true,
        hasAudio: false,
        enableWorker: true,
        autoCleanupSourceBuffer: true,
        liveBufferLatencyChasing: true,
        liveBufferLatencyMaxLatency: 0.5,
        liveBufferLatencyMinRemain: 0.3,
      };

      const player = window.flvjs.createPlayer(config);
      player.attachMediaElement(domEle);
      player.load();
      player.play().catch(() => {});

      players.current[domId] = player;
    },
    [streamHost, streamPort],
  );

  // 固定16格
  const getFixedGridList = () => {
    const list = [];
    for (let i = 0; i < MAX_GRID; i++) {
      const stream = videoStreams[i];
      list.push({
        id: stream?.id || `empty-grid-${i}`,
        stream: stream?.stream || "",
        name: stream?.name || "",
        index: i,
      });
    }
    return list;
  };

  const handleSplitModeChange = (mode) => {
    setSplitMode(mode);
  };

  // 初始化播放
  useEffect(() => {
    const list = getFixedGridList();
    list.forEach((item) => {
      if (item.stream) {
        setTimeout(() => playVideo(item.id, item.stream), 50);
      }
    });

    return () => {
      Object.values(players.current).forEach((p) => p?.destroy());
    };
  }, [playVideo]);

  const isGridShow = (index) => index < splitMode;

  const renderSplitModeButtons = () => (
    <Space>
      <Button
        type={splitMode === 1 ? "primary" : "default"}
        icon={<BorderOutlined />}
        onClick={() => handleSplitModeChange(1)}
      >
        单屏
      </Button>
      <Button
        type={splitMode === 4 ? "primary" : "default"}
        icon={<BorderInnerOutlined />}
        onClick={() => handleSplitModeChange(4)}
      >
        四分屏
      </Button>
      <Button
        type={splitMode === 9 ? "primary" : "default"}
        icon={<BorderTopOutlined />}
        onClick={() => handleSplitModeChange(9)}
      >
        九分屏
      </Button>
      <Button
        type={splitMode === 16 ? "primary" : "default"}
        icon={<BorderBottomOutlined />}
        onClick={() => handleSplitModeChange(16)}
      >
        十六分屏
      </Button>
    </Space>
  );

  // ===================== 渲染视频格子（带状态） =====================
  const renderVideoGrid = () => {
    const gridList = getFixedGridList();
    const { rows, cols } = splitModeConfig[splitMode];

    return (
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${cols}, 1fr)`,
          gridTemplateRows: `repeat(${rows}, 1fr)`,
          gap: 4,
          height: "100%",
        }}
      >
        {gridList.map((item, index) => {
          const show = isGridShow(index);
          const status = cameraStatus[item.id]; // 状态
          const isError = status?.status === "MAINTENANCE";

          return (
            <div
              key={item.id}
              style={{
                background: "#000",
                position: "relative",
                minHeight: 200,
                display: show ? "block" : "none",
                overflow: "hidden",
              }}
            >
              {/* 视频 */}
              {item.stream ? (
                <video
                  style={{ height: "100%", width: "100%", objectFit: "fill" }}
                  id={item.id}
                  autoPlay
                  muted
                  playsInline
                  controls
                />
              ) : (
                <div
                  style={{
                    height: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    background: "#1a1a1a",
                    border: "1px dashed #333",
                  }}
                >
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={
                      <span style={{ color: "#fff" }}>无视频流</span>
                    }
                  />
                </div>
              )}

              {/* ===================== 摄像头状态提示（悬浮层） ===================== */}
              {isError && (
                <div
                  style={{
                    position: "absolute",
                    top: 6,
                    left: 6,
                    zIndex: 10,
                    background: "rgba(255,77,79,0.85)",
                    color: "#fff",
                    padding: "2px 8px",
                    borderRadius: 4,
                    fontSize: 12,
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                  }}
                >
                  <WarningOutlined />
                  {status?.status || "摄像头异常"}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <Card size="small" style={{ marginBottom: 0, borderRadius: 0 }}>
        <Row justify="space-between" align="middle">
          <Col>
            <Space>
              <span style={{ fontWeight: "bold" }}>分屏模式:</span>
              {renderSplitModeButtons()}
            </Space>
          </Col>
        </Row>
      </Card>
      <div style={{ flex: 1, overflow: "hidden" }}>{renderVideoGrid()}</div>
    </div>
  );
};
