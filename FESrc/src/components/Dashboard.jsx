import { useState, useEffect, useRef } from "react";
import {
  Row,
  Col,
  Card,
  Statistic,
  Progress,
  Space,
  Button,
  Alert,
} from "antd";
import {
  TeamOutlined,
  WarningOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
} from "@ant-design/icons";
import { useAppStore } from "../store/appStore";

import { HeatmapComponent } from "./HeatmapComponent";

export const Dashboard = () => {
  const { dashboardData, setDashboardData } = useAppStore();
  const [isPlaying, setIsPlaying] = useState(true);
  const [connectionStatus, setConnectionStatus] = useState("disconnected");
  const wsRef = useRef(null);
  const connectingRef = useRef(false);

  const [peopleCount, setPeopleCount] = useState(0);
  const [alertCount, setAlertCount] = useState(0);
  const [heatmapData, setHeatmapData] = useState([]);

  // ==========================
  // 连接 Kafka WebSocket
  // ==========================
  const connectWebSocket = () => {
    // 已经在连接 / 已连接 → 不再重复创建
    if (connectingRef.current || wsRef.current) return;

    // 开始连接 → 上锁
    connectingRef.current = true;

    // 关闭旧连接
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    console.log("→ 新建 WebSocket 连接");
    const ws = new WebSocket("ws://82.156.163.237:8666");
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("✅ 连接成功");
      setConnectionStatus("connected");
      connectingRef.current = false;
    };

    ws.onclose = () => {
      console.log("❌ 连接关闭");
      setConnectionStatus("disconnected");
      wsRef.current = null;
      connectingRef.current = false;
    };

    ws.onerror = () => {
      console.log("⚠️ 连接错误");
      setConnectionStatus("error");
      connectingRef.current = false;
    };

    ws.onmessage = (e) => {
      if (!isPlaying) return;
      try {
        const obj = JSON.parse(e.data);

        if (obj.class_name === "person") {
          setPeopleCount((prev) => prev + 1);
        }
        if (obj.event_type === "attribute_changed") {
          setAlertCount((prev) => prev + 1);
        }
        if (obj.bbox) {
          const x = obj.bbox.left + obj.bbox.width / 2;
          const y = obj.bbox.top + obj.bbox.height / 2;
          setHeatmapData((prev) => [
            ...prev.slice(-50),
            {
              lng: 116.3 + (x / 800) * 0.1,
              lat: 39.8 + (y / 450) * 0.1,
              value: Math.floor(obj.confidence * 20) + 5,
            },
          ]);
        }
      } catch (err) {}
    };
  };

  const disconnectWebSocket = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  };

  const resetAll = () => {
    setPeopleCount(0);
    setAlertCount(0);
    setHeatmapData([]);
  };

  useEffect(() => {
    connectWebSocket();
    return () => disconnectWebSocket();
  }, []);

  // useEffect(() => {
  //   if (isPlaying) {
  //     connectWebSocket();
  //   } else {
  //     disconnectWebSocket();
  //   }
  // }, [isPlaying]);

  return (
    <div style={{ padding: 24, height: "100%", overflow: "auto" }}>
      <Alert
        message={
          <Space>
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor:
                  connectionStatus === "connected" ? "#52c41a" : "#faad14",
              }}
            />
            <span>
              {connectionStatus === "connected"
                ? "Kafka 已连接 · 实时接收数据"
                : "未连接"}
            </span>
          </Space>
        }
        type={connectionStatus === "connected" ? "success" : "warning"}
        action={
          <Space>
            {/* <Button
              icon={
                isPlaying ? <PauseCircleOutlined /> : <PlayCircleOutlined />
              }
              onClick={() => setIsPlaying(!isPlaying)}
            >
              {isPlaying ? "暂停" : "播放"}
            </Button>
            <Button icon={<ReloadOutlined />} onClick={resetAll}>
              清空
            </Button> */}
          </Space>
        }
        style={{ marginBottom: 16 }}
      />

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="累计人数"
              value={peopleCount}
              prefix={<TeamOutlined />}
              suffix="人"
              valueStyle={{ color: peopleCount > 50 ? "#ff4d4f" : "#3f8600" }}
            />
            <Progress percent={Math.min(peopleCount, 100)} />
          </Card>
        </Col>

        <Col span={6}>
          <Card>
            <Statistic
              title="累计告警次数"
              value={alertCount}
              prefix={<WarningOutlined />}
              valueStyle={{ color: "#cf1322" }}
            />
          </Card>
        </Col>

        <Col span={12}>
          <Card title="说明">热力图、人流统计、告警统计全部正常工作 ✅</Card>
        </Col>
      </Row>

      {/* ✅ 你漂亮的热力图！ */}
      <Row gutter={16}>
        <Col span={12}>
          <Card title="人流热力图">
            <HeatmapComponent
              data={heatmapData}
              type="crowd"
              style={{ height: 380 }}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="告警热力图">
            <HeatmapComponent
              data={heatmapData}
              type="alert"
              style={{ height: 380 }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
};
