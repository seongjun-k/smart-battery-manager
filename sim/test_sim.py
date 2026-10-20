"""시뮬레이터 자체 점검 = 보고서 7장 테스트 1~8. 실행: python sim/test_sim.py"""
import random

from sim import CAP_END_V, CAPACITY_AH, DT, OCV_TABLE, Device, Plant, ocv


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


def cmd(dev, **kw):
    err = dev.command({"type": "cmd", **kw})
    assert err is None, err


def start(dev, mode="STORAGE"):
    cmd(dev, cmd="start", mode=mode, targetV=3.80)


def soc_at(v):
    for (s0, v0), (s1, v1) in zip(OCV_TABLE, OCV_TABLE[1:]):
        if v0 <= v <= v1:
            return s0 + (s1 - s0) * (v - v0) / (v1 - v0)


# 1 보관 방전: 6S 만충 → 3.80V, 평균 25W
dev = ready_dev()
start(dev)
run_until(dev, lambda: dev.t > 600, 700)
p = dev.pack_v * dev.current_avg
assert dev.limit == "I_P" and abs(p - 25) < 1.5, (dev.limit, p)
assert 0 < dev.status()["progress"] < 1 and dev.status()["elapsed"] > 0
run_until(dev, lambda: dev.state == "DONE", 3 * 3600)
v = [ocv(s) for s in dev.p.soc]
assert all(abs(x - 3.80) <= 0.05 for x in v), v
print(f"1 보관 방전 통과: {dev.t / 60:.0f}분, 10분 시점 {p:.1f}W, 셀 OCV {min(v):.3f}~{max(v):.3f}V")

# 2 진단: IR·SOH
dev = ready_dev()
cmd(dev, cmd="start", mode="DIAG")
run_until(dev, lambda: dev.state == "SELECT", 10)
assert all(3 < r < 7 for r in dev.ir) and dev.soh >= 90, (dev.ir, dev.soh)
print(f"2 진단 통과: IR {min(dev.ir)}~{max(dev.ir)}mΩ, SOH {dev.soh}")

# 3 밸런싱: 셀 1개 SOC −10% → 높은 셀만 방전해 편차 해소
dev = ready_dev()
cmd(dev, cmd="fault", name="imbalance")
run_until(dev, lambda: "IMBALANCE" in dev.alarms, 5)   # 이동평균이라 약 1초 지연
before = max(dev.cells) - min(dev.cells)
start(dev, "BALANCE")
dev.step()
assert dev.bal[0] is False and all(dev.bal[1:]) and dev.duty == 0, dev.bal
run_until(dev, lambda: dev.state == "DONE", 8 * 3600)
v = [ocv(s) for s in dev.p.soc]
assert max(v) - min(v) <= 0.012, v
assert dev.events.count("WARN") == 1, dev.events   # 50mV 기준을 지날 때 경고가 반복되지 않음
print(f"3 밸런싱 통과: 편차 {before * 1000:.0f}mV → {(max(v) - min(v)) * 1000:.1f}mV, {dev.t / 3600:.1f}시간")

# 4 용량 테스트: 측정 용량이 모델에서 종료 전압까지 뺄 수 있는 용량과 ±5%
dev = ready_dev()
start(dev, "CAPACITY")
run_until(dev, lambda: dev.state == "DONE", 4 * 3600)
expect = CAPACITY_AH * (1 - soc_at(CAP_END_V) / 100)
err = dev.cap_measured / expect - 1
assert abs(err) <= 0.05 and dev.status()["capMeasuredAh"] is not None, (dev.cap_measured, expect)
print(f"4 용량 테스트 통과: 측정 {dev.cap_measured:.3f}Ah, 기대 {expect:.3f}Ah, 오차 {err * 100:+.1f}%, SOH {dev.soh}")

# 5 팬 정지: 팬 동작 중 fan_stop → 즉시 중단
dev = ready_dev()
start(dev)
run_until(dev, lambda: dev.fan_duty > 0, 600)
cmd(dev, cmd="fault", name="fan_stop")
dev.step()
s = dev.status()
assert dev.duty == 0 and s["state"] == "STOP" and "FAN_STOP" in s["alarms"] and "WARN" in s["events"], s
print("5 팬 정지 통과: 1주기 안에 듀티 0, FAN_STOP 경고")

# 6 과열 감속: 주변 온도 상승 → I_T 한도로 전류 감소, 방열판 70°C 이하 유지
dev = ready_dev()
start(dev)
run_until(dev, lambda: dev.t > 300, 400)
i_before = dev.current_avg
cmd(dev, cmd="fault", name="overheat")
seen_it, t_max, i_min = False, 0.0, i_before
for _ in range(int(1800 / DT)):
    dev.step()
    seen_it |= dev.limit == "I_T"
    t_max = max(t_max, dev.temp_sink)
    if dev.limit == "I_T":
        i_min = min(i_min, dev.current_avg)
assert seen_it and t_max <= 70 and dev.state == "RUN", (seen_it, t_max, dev.state, dev.alarms)
print(f"6 과열 감속 통과: I_T 한도 작동, 전류 {i_before:.2f}A → 최저 {i_min:.2f}A, 방열판 최고 {t_max:.1f}°C")

# 7 연결 불량: 밸런스 잭 분리 → 즉시 중단
dev = ready_dev()
start(dev)
run_until(dev, lambda: dev.t > 60, 70)
cmd(dev, cmd="fault", name="disconnect")
dev.step()
s = dev.status()
assert dev.duty == 0 and s["state"] == "STOP" and "CONN" in s["alarms"], s
print("7 연결 불량 통과: 1주기 안에 듀티 0, CONN 경고")

# 8 정지: 웹 정지 명령 → 즉시 듀티 0
dev = ready_dev(3)
start(dev)
run_until(dev, lambda: dev.t > 60, 70)
assert dev.duty > 0
cmd(dev, cmd="stop")
s = dev.status()
assert dev.duty == 0 and s["state"] == "STOP" and "STOP" in s["events"], s
print("8 정지 통과: 정지 명령 즉시 듀티 0")

# 명령 검증
assert dev.command({"cmd": "start", "mode": "STORAGE", "targetV": 4.1}) is not None
assert dev.command({"cmd": "start", "mode": "STORAGE", "capacityAh": True}) is not None
assert dev.command({"cmd": "fault", "name": "nope"}) is not None
assert "batteryId" not in s
cmd(dev, cmd="set", key="buzzerKeyTone", value=False)
print("명령 검증 통과")
