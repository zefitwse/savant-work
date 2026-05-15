import numpy as np
from stream_doctor.metrics import diagnose_frame


def test_dark():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = diagnose_frame(frame)
    assert "DARK" in result["issues"]
    print("过暗检测通过")


def test_blur():
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 120
    result = diagnose_frame(frame)
    assert "BLUR" in result["issues"]
    print("模糊检测通过")


def test_normal():
    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    result = diagnose_frame(frame)
    print("随机画面检测结果：", result)


if __name__ == "__main__":
    test_dark()
    test_blur()
    test_normal()
    print("task9 test passed")
