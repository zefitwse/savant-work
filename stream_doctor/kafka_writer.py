import json

from stream_doctor.config import KAFKA_BOOTSTRAP_SERVERS, VQD_OUTPUT_TOPIC, ENABLE_KAFKA


class VQDKafkaWriter:
    def __init__(self):
        self.enabled = ENABLE_KAFKA
        self.producer = None

        if self.enabled:
            try:
                from kafka import KafkaProducer

                self.producer = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
                )
                print(f"[StreamDoctor] Kafka 已启用，输出 Topic: {VQD_OUTPUT_TOPIC}")
            except Exception as e:
                print(f"[StreamDoctor] Kafka 初始化失败，降级为本地输出: {e}")
                self.enabled = False

    def send(self, event: dict):
        if not self.enabled or self.producer is None:
            return

        self.producer.send(VQD_OUTPUT_TOPIC, value=event)
        self.producer.flush()
