import { Layout as AntLayout, Menu } from "antd";
import { VideoCameraOutlined, DashboardOutlined } from "@ant-design/icons";
import { useState } from "react";
import { VideoView } from "./VideoView";
import { Dashboard } from "./Dashboard";

const { Header, Sider, Content } = AntLayout;

export const Layout = () => {
  const [currentMenu, setCurrentMenu] = useState("video");

  const menuItems = [
    {
      key: "video",
      icon: <VideoCameraOutlined />,
      label: "视频监控",
    },
    {
      key: "dashboard",
      icon: <DashboardOutlined />,
      label: "实时仪表盘",
    },
  ];

  const renderContent = () => {
    switch (currentMenu) {
      case "video":
        return <VideoView />;
      case "dashboard":
        return <Dashboard />;
      default:
        return <VideoView />;
    }
  };

  return (
    <AntLayout style={{ height: "100vh" }}>
      <Sider trigger={null}>
        <div
          style={{
            height: 32,
            margin: 16,
            background: "rgba(255, 255, 255, 0.2)",
            borderRadius: 6,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "white",
            fontWeight: "bold",
          }}
        >
          {"视频监控系统"}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[currentMenu]}
          items={menuItems}
          onClick={({ key }) => setCurrentMenu(key)}
        />
      </Sider>
      <AntLayout>
        <Header
          style={{
            padding: 0,
            background: "#001529",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            paddingLeft: 16,
            paddingRight: 16,
          }}
        ></Header>
        <Content
          style={{
            margin: 0,
            padding: 0,
            background: "#141414",
            overflow: "auto",
          }}
        >
          {renderContent()}
        </Content>
      </AntLayout>
    </AntLayout>
  );
};
