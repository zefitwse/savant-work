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
  EyeOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
} from "@ant-design/icons";
import { useAppStore } from "../store/appStore";
import { HeatmapComponent } from "./HeatmapComponent";

export const Dashboard = () => {
  const { dashboardData, setDashboardData } = useAppStore();
  const [isPlaying, setIsPlaying] = useState(true);
  const [connectionStatus] = useState("disconnected");
  const wsRef = useRef(null);
  const intervalRef = useRef(null);

  // 模拟实时数据流
  const generateMockData = () => {
    const baseLng = 116.3974; // 经度
    const baseLat = 39.9093; // 纬度

    return {
      crowdDensity: Math.floor(Math.random() * 1000) + 100,
      alertCount: Math.floor(Math.random() * 50) + 5,
      heatmapData: Array.from({ length: 20 }, () => ({
        lng: baseLng + (Math.random() - 0.5) * 0.1,
        lat: baseLat + (Math.random() - 0.5) * 0.1,
        value: Math.floor(Math.random() * 100) + 1,
      })),
      timestamp: Date.now(),
    };
  };

  // 模拟实时数据更新
  const startMockDataStream = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }

    intervalRef.current = window.setInterval(() => {
      setDashboardData(generateMockData());
    }, 2000); // 每2秒更新一次
  };

  const stopMockDataStream = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  useEffect(() => {
    // 初始化时生成一些模拟数据
    setDashboardData(generateMockData());

    // 启动模拟数据流
    startMockDataStream();

    return () => {
      stopMockDataStream();
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  useEffect(() => {
    if (isPlaying) {
      startMockDataStream();
    } else {
      stopMockDataStream();
    }
  }, [isPlaying]);

  const getStatusColor = () => {
    switch (connectionStatus) {
      case "connected":
        return "#52c41a";
      case "disconnected":
        return "#faad14";
      case "error":
        return "#ff4d4f";
      default:
        return "#d9d9d9";
    }
  };

  const getStatusText = () => {
    switch (connectionStatus) {
      case "connected":
        return "实时数据连接正常";
      case "disconnected":
        return "数据连接断开";
      case "error":
        return "数据连接错误";
      default:
        return "未知状态";
    }
  };

  return (
    <div style={{ padding: 24, height: "100%", overflow: "auto" }}>
      {/* 顶部状态栏 */}
      <Alert
        message={
          <Space>
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: getStatusColor(),
              }}
            />
            <span>{getStatusText()}</span>
            <span>•</span>
            <span>
              最后更新:{" "}
              {dashboardData
                ? new Date(dashboardData.timestamp).toLocaleTimeString()
                : "--"}
            </span>
          </Space>
        }
        type={
          connectionStatus === "connected"
            ? "success"
            : connectionStatus === "disconnected"
              ? "warning"
              : "error"
        }
        action={
          <Space>
            <Button
              type="text"
              icon={
                isPlaying ? <PauseCircleOutlined /> : <PlayCircleOutlined />
              }
              onClick={() => setIsPlaying(!isPlaying)}
            >
              {isPlaying ? "暂停" : "播放"}
            </Button>
            <Button
              type="text"
              icon={<ReloadOutlined />}
              onClick={() => setDashboardData(generateMockData())}
            >
              刷新
            </Button>
          </Space>
        }
        style={{ marginBottom: 16 }}
      />

      {/* 关键指标 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="当前人流密度"
              value={dashboardData?.crowdDensity || 0}
              prefix={<TeamOutlined />}
              suffix="人"
              valueStyle={{
                color:
                  dashboardData && dashboardData.crowdDensity > 800
                    ? "#ff4d4f"
                    : "#3f8600",
              }}
            />
            <Progress
              percent={
                dashboardData
                  ? Math.min((dashboardData.crowdDensity / 1000) * 100, 100)
                  : 0
              }
              status={
                dashboardData && dashboardData.crowdDensity > 800
                  ? "exception"
                  : "normal"
              }
              style={{ marginTop: 8 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="告警数量"
              value={dashboardData?.alertCount || 0}
              prefix={<WarningOutlined />}
              valueStyle={{
                color:
                  dashboardData && dashboardData.alertCount > 30
                    ? "#ff4d4f"
                    : "#cf1322",
              }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: "#666" }}>
              较上一时段:{" "}
              {dashboardData
                ? dashboardData.alertCount > 25
                  ? "↑"
                  : "↓"
                : "-"}
              {dashboardData ? Math.abs(dashboardData.alertCount - 25) : 0}
            </div>
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="在线监控点"
              value={16}
              prefix={<EyeOutlined />}
              valueStyle={{ color: "#1890ff" }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: "#666" }}>
              正常: 14 异常: 2
            </div>
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="平均响应时间"
              value={187}
              prefix={<ClockCircleOutlined />}
              suffix="ms"
              valueStyle={{ color: "#52c41a" }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: "#666" }}>
              目标: &lt;500ms ✅
            </div>
          </Card>
        </Col>
      </Row>

      {/* 热力图和图表 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card
            title="人流密度热力图"
            extra={
              <Button type="link" size="small">
                查看详情
              </Button>
            }
          >
            <HeatmapComponent
              data={dashboardData?.heatmapData || []}
              type="crowd"
              style={{ height: 300 }}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card
            title="告警频率热力图"
            extra={
              <Button type="link" size="small">
                查看详情
              </Button>
            }
          >
            <HeatmapComponent
              data={dashboardData?.heatmapData || []}
              type="alert"
              style={{ height: 300 }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
};
