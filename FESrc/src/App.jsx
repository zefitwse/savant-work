import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { Layout } from "./components/Layout";

function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#1890ff",
        },
      }}
    >
      <Layout />
    </ConfigProvider>
  );
}

export default App;
