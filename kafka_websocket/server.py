import asyncio
import websockets
from kafka import KafkaConsumer

# 配置
KAFKA_BROKER = '127.0.0.1:9092'
KAFKA_TOPIC = 'deepstream.events'  
PORT = 8666

async def handle_client(websocket, path):
    print("前端已连接")
    
    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=[KAFKA_BROKER],
        auto_offset_reset='latest',
        enable_auto_commit=True,
        group_id='heatmap-group'
    )

    for msg in consumer:
        try:
            data = msg.value.decode('utf-8')
            await websocket.send(data)
        except:
            continue

print(f"WebSocket 服务启动: ws://0.0.0.0:{PORT}")
start_server = websockets.serve(handle_client, "0.0.0.0", PORT)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()