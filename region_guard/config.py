import os

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
INPUT_TOPIC = os.getenv("TASK6_INPUT_TOPIC", "deepstream.events")
OUTPUT_TOPIC = os.getenv("TASK6_OUTPUT_TOPIC", "region.alerts")
GROUP_ID = os.getenv("TASK6_GROUP_ID", "task6-region-worker")
DB_PATH = os.getenv("TASK6_DB_PATH", "task6_alerts.db")



TRIPWIRE_RULES = [
    {
        "name": "A_to_B",
        "from": "A_warning",
        "to": "B_forbidden",
    }
]

LOITERING_SECONDS = int(os.getenv("TASK6_LOITERING_SECONDS", "5"))
DENSITY_THRESHOLD = int(os.getenv("TASK6_DENSITY_THRESHOLD", "3"))