import { useEffect, useRef } from "react";
import { Empty } from "antd";

export const HeatmapComponent = ({ data, type, style = {} }) => {
  const canvasRef = useRef(null);

  // 热力图颜色配置
  const colorConfig = {
    crowd: {
      minColor: [34, 139, 34], // 绿色
      maxColor: [255, 0, 0], // 红色
    },
    alert: {
      minColor: [255, 255, 0], // 黄色
      maxColor: [255, 0, 0], // 红色
    },
  };

  // 绘制热力图
  const drawHeatmap = () => {
    const canvas = canvasRef.current;
    if (!canvas || data.length === 0) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // 清除画布
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // 设置热力点半径和模糊度
    const pointRadius = 30;
    const blurRadius = 15;

    // 计算数据范围用于归一化
    const values = data.map((d) => d.value);
    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const valueRange = maxValue - minValue;

    // 创建临时画布用于高斯模糊效果
    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = canvas.width;
    tempCanvas.height = canvas.height;
    const tempCtx = tempCanvas.getContext("2d");
    if (!tempCtx) return;

    // 绘制热力点
    data.forEach((point) => {
      // 归一化值 (0-1)
      const normalizedValue =
        valueRange > 0 ? (point.value - minValue) / valueRange : 0.5;

      // 计算颜色
      const config = colorConfig[type];
      const r = Math.round(
        config.minColor[0] +
          normalizedValue * (config.maxColor[0] - config.minColor[0]),
      );
      const g = Math.round(
        config.minColor[1] +
          normalizedValue * (config.maxColor[1] - config.minColor[1]),
      );
      const b = Math.round(
        config.minColor[2] +
          normalizedValue * (config.maxColor[2] - config.minColor[2]),
      );

      // 将经纬度转换为画布坐标 (简化版)
      const x = ((point.lng - 116.3) / 0.2) * canvas.width;
      const y = ((point.lat - 39.8) / 0.2) * canvas.height;

      // 绘制热力点
      const gradient = tempCtx.createRadialGradient(x, y, 0, x, y, pointRadius);
      gradient.addColorStop(
        0,
        `rgba(${r}, ${g}, ${b}, ${0.8 * normalizedValue})`,
      );
      gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);

      tempCtx.fillStyle = gradient;
      tempCtx.fillRect(
        x - pointRadius,
        y - pointRadius,
        pointRadius * 2,
        pointRadius * 2,
      );
    });

    // 应用高斯模糊效果
    ctx.filter = `blur(${blurRadius}px)`;
    ctx.drawImage(tempCanvas, 0, 0);
    ctx.filter = "none";

    // 添加网格和标注
    drawGridAndLabels(ctx, canvas.width, canvas.height);
  };

  // 绘制网格和坐标标注
  const drawGridAndLabels = (ctx, width, height) => {
    ctx.strokeStyle = "rgba(255, 255, 255, 0.3)";
    ctx.lineWidth = 0.5;
    ctx.font = "10px Arial";
    ctx.fillStyle = "rgba(255, 255, 255, 0.7)";

    // 绘制网格线
    for (let i = 0; i <= 4; i++) {
      const x = (width / 4) * i;
      const y = (height / 4) * i;

      // 垂直线
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();

      // 水平线
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();

      // 坐标标注
      if (i > 0 && i < 4) {
        const lng = 116.3 + i * 0.05;
        const lat = 39.8 + i * 0.05;

        ctx.fillText(lng.toFixed(2), x - 15, height - 5);
        ctx.fillText(lat.toFixed(2), 5, y + 10);
      }
    }

    // 添加标题
    ctx.font = "12px Arial";
    ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
    ctx.fillText(
      type === "crowd" ? "人流密度热力图" : "告警频率热力图",
      10,
      20,
    );
  };

  useEffect(() => {
    drawHeatmap();
  }, [data, type]);

  // 处理画布大小变化
  useEffect(() => {
    const handleResize = () => {
      const canvas = canvasRef.current;
      if (canvas) {
        const container = canvas.parentElement;
        if (container) {
          canvas.width = container.clientWidth;
          canvas.height = container.clientHeight;
          drawHeatmap();
        }
      }
    };

    handleResize();
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, [data, type]);

  if (data.length === 0) {
    return (
      <div
        style={{
          ...style,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Empty description="暂无数据" />
      </div>
    );
  }

  return (
    <div
      style={{
        ...style,
        position: "relative",
        background: "linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%)",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      <canvas
        ref={canvasRef}
        style={{
          width: "100%",
          height: "100%",
          display: "block",
        }}
      />

      {/* 数据统计信息 */}
      <div
        style={{
          position: "absolute",
          top: 10,
          right: 10,
          background: "rgba(0, 0, 0, 0.7)",
          color: "white",
          padding: "8px 12px",
          borderRadius: 4,
          fontSize: 12,
        }}
      >
        <div>数据点: {data.length}</div>
        <div>最大值: {Math.max(...data.map((d) => d.value))}</div>
        <div>最小值: {Math.min(...data.map((d) => d.value))}</div>
      </div>
    </div>
  );
};
