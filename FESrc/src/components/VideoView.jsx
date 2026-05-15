import { useState, useRef, useEffect } from "react";
import { Row, Col, Button, Space, Card, Empty } from "antd";
import {
  BorderOutlined,
  BorderInnerOutlined,
  BorderTopOutlined,
  BorderBottomOutlined,
} from "@ant-design/icons";

export const VideoView = () => {
  const videoStreams = window.VIDEO_STREAMS_CONFIG || [];

  const streamHost = window.location.hostname || "127.0.0.1";
  const streamPort = 8080;

  const players = useRef({});

  const [splitMode, setSplitMode] = useState(9);

  // 分屏模式配置
  const splitModeConfig = {
    1: { rows: 1, cols: 1, gridClass: "split-1" },
    4: { rows: 2, cols: 2, gridClass: "split-4" },
    9: { rows: 3, cols: 3, gridClass: "split-9" },
    16: { rows: 4, cols: 4, gridClass: "split-16" },
  };

  const playVideo = (domId, stream) => {
    const streamUrl = `http://${streamHost}:${streamPort}${stream}`;
    console.log(streamUrl);

    if (stream) {
      let domEle = document.getElementById(domId);

      if (domEle) {
        let config = {
          type: "flv",
          url: streamUrl,
          isLive: true,
          hasAudio: false,
          enableWorker: true,
          enableStashInitialMedia: false,
          stashInitialSize: 128,
          autoCleanupSourceBuffer: true,
          autoCleanupMaxBackwardDuration: 3,
          autoCleanupMinBackwardDuration: 2,
          lazyLoad: true,
          lazyLoadMaxDuration: 3,
          lazyLoadRecoverDuration: 2,
          liveBufferLatencyChasing: true,
          liveBufferLatencyMaxLatency: 0.5,
          liveBufferLatencyMinRemain: 0.3,
          liveSync: true,
          liveSyncMaxLatency: 0.5,
          liveSyncMinRemain: 0.3,
        };

        const player = flvjs.createPlayer(config);

        player.attachMediaElement(domEle);
        player.load();
        player.play();

        players.current[domId] = player;
      }
    }
  };

  useEffect(() => {
    videoStreams.forEach((item) => {
      playVideo(item.id, item.stream);
    });

    // 页面关闭时停止播放
    return () => {
      Object.values(players.current).forEach((p) => p?.destroy());
    };
  }, []);

  // 获取当前显示的流
  const getDisplayStreams = () => {
    const maxStreams = splitMode;
    const streamsToDisplay = videoStreams.slice(0, maxStreams);

    // 如果流数量不足，用空位补全
    while (streamsToDisplay.length < maxStreams) {
      streamsToDisplay.push({
        id: `empty-${streamsToDisplay.length}`,
        name: "",
        url: "",
      });
    }

    return streamsToDisplay;
  };

  // 分屏模式切换
  const handleSplitModeChange = (mode) => {
    setSplitMode(mode);
  };

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

  const renderVideoGrid = () => {
    const displayStreams = getDisplayStreams();
    const config = splitModeConfig[splitMode];

    return (
      <div className={`split-layout ${config.gridClass}`}>
        {displayStreams.map((stream, index) => {
          const hidden = index >= splitMode;

          return (
            <div
              key={stream?.id || `empty-${index}`}
              style={{
                background: "#000",
                position: "relative",
                minHeight: 200,
                display: hidden ? "none" : "block",
              }}
            >
              {stream.stream ? (
                <video
                  style={{
                    height: "100%",
                    width: "100%",
                  }}
                  id={stream.id}
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
                    color: "#666",
                    border: "1px dashed #333",
                  }}
                >
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    style={{ color: "#fff" }}
                    description={
                      <span style={{ color: "#fff" }}>无视频流</span>
                    }
                  />
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
      {/* 顶部控制栏 */}
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

      {/* 视频网格区域 */}
      <div style={{ flex: 1, overflow: "hidden" }}>{renderVideoGrid()}</div>
    </div>
  );
};
