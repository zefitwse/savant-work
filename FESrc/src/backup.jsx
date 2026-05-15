import { useEffect, useRef } from "react";
import "./App.css";

// 四路视频流配置（改成你自己的）
const VIDEO_LIST = [
  { id: "v1", name: "视频1", stream: "processed/stream1_1" },
  { id: "v2", name: "视频2", stream: "processed/stream1_2" },
  { id: "v3", name: "视频3", stream: "processed/stream2_1" },
  { id: "v4", name: "视频4", stream: "processed/stream2_2" },
];

// ZLM 服务器地址
const ZLM_HOST = "http://58.87.71.128";

function App() {
  const players = useRef({});

  // 播放单个视频
  const playVideo = (domId, stream) => {
    const url = `${ZLM_HOST}/index/api/webrtc?app=live&stream=${stream}&type=play`;

    const player = new window.ZLMRTCClient.Endpoint({
      element: document.getElementById(domId),
      debug: false,
      zlmsdpUrl: url,
      recvOnly: true, // 只播放
      audioEnable: false, // 关闭声音
      videoEnable: true,
      usedatachannel: false,
    });

    players.current[domId] = player;
  };

  // 页面加载自动播放
  useEffect(() => {
    VIDEO_LIST.forEach((item) => {
      playVideo(item.id, item.stream);
    });

    // 页面关闭时停止播放
    return () => {
      Object.values(players.current).forEach((p) => p?.close());
    };
  }, []);

  return (
    <div className="container">
      <div className="grid">
        {VIDEO_LIST.map((item) => (
          <div key={item.id} className="box">
            <video id={item.id} autoPlay muted playsInline />
            <div className="label">{item.name}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default App;
