"""시뮬레이터 자체 점검 (보고서 7장 테스트 1~3). 실행: python sim/test_sim.py"""
import random

from sim import DT, Device, Plant, ocv


def run_until(dev, cond, max_s):
    for _ in range(int(max_s / DT)):
        dev.step()
        if cond():
            return
    raise AssertionError(f"{max_s}s 안에 조건 미달: state={dev.state} alarms={dev.alarms}")


def ready_dev(cells=6):
    dev = Device(Plant(cells, random.Random(0)))
    run_until(dev, lambda: dev.state == "SELECT", 10)
    assert dev.cell_count == cells and dev.soh is not None, (dev.cell_count, dev.soh)
    assert all(3 < r < 7 for r in dev.ir), dev.ir   # 모델 R_CELL = 5mΩ, 3S 펄스는 노이즈로 ±2mΩ까지
    return dev


START = {"type": "cmd", "cmd": "start", "mode": "STORAGE", "targetV": 3.80}

# 테스트 1: 6S 만충 → 보관 3.80V, 평균 25W
dev = ready_dev()
assert dev.command(START) is None
run_until(dev, lambda: dev.t > 600, 700)
p = dev.pack_v * dev.current_avg
assert dev.limit == "I_P" and abs(p - 25) < 1.5, (dev.limit, p)
run_until(dev, lambda: dev.state == "DONE", 3 * 3600)
v = [ocv(s) for s in dev.p.soc]
assert all(abs(x - 3.80) <= 0.05 for x in v), v
print(f"테스트 1 통과: {dev.t / 60:.0f}분, 10분 시점 {p:.1f}W, 셀 OCV {min(v):.3f}~{max(v):.3f}V, "
      f"방열판 {dev.temp_sink:.0f}°C")

# 테스트 2: 팬 동작 중 fan_stop → 즉시 중단
dev = ready_dev()
dev.command(START)
run_until(dev, lambda: dev.fan_duty > 0, 600)
assert dev.command({"type": "cmd", "cmd": "fault", "name": "fan_stop"}) is None
dev.step()
s = dev.status()
assert dev.duty == 0 and s["state"] == "STOP" and "FAN_STOP" in s["alarms"] and "WARN" in s["events"], s
print("테스트 2 통과: fan_stop 후 1주기 안에 듀티 0, FAN_STOP 경고")

# 테스트 3: 웹 정지 명령 → 즉시 듀티 0
dev = ready_dev(3)
dev.command(START)
run_until(dev, lambda: dev.t > 60, 70)
assert dev.duty > 0
dev.command({"type": "cmd", "cmd": "stop"})
s = dev.status()
assert dev.duty == 0 and s["state"] == "STOP" and "STOP" in s["events"], s
print("테스트 3 통과: 정지 명령 즉시 듀티 0")

# 명령 검증
assert dev.command({"cmd": "start", "mode": "STORAGE", "targetV": 4.1}) is not None
assert dev.command({"cmd": "fault", "name": "nope"}) is not None
assert dev.command({"cmd": "set", "key": "buzzerKeyTone", "value": False}) is None
print("명령 검증 통과")
