"""시뮬레이터 자체 점검 = 보고서 7장 테스트 1~12. 실행: python sim/test_sim.py"""
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


# 1 보관 방전: 6S 만충 → 3.80V, 10분 시점 25W 상한
dev = ready_dev()
start(dev)
run_until(dev, lambda: dev.t > 600, 700)
p = dev.pack_v * dev.current_avg
assert dev.limit == "I_P" and abs(p - 25) < 1.5, (dev.limit, p)
assert 0 < dev.status()["progress"] < 1 and dev.status()["elapsed"] > 0
p40, t_max = None, 0.0   # 온도 한도가 걸린 뒤의 전력과 방열판 최고 온도 (보고서 7장 수치)
for _ in range(int(3 * 3600 / DT)):
    dev.step()
    t_max = max(t_max, dev.temp_sink)
    if p40 is None and dev.t > 2400:
        p40 = dev.pack_v * dev.current_avg
    if dev.state == "DONE":
        break
v = [ocv(s) for s in dev.p.soc]
assert dev.state == "DONE" and t_max <= 95 and all(abs(x - 3.80) <= 0.05 for x in v), (dev.state, t_max, v)
print(f"1 보관 방전 통과: {dev.t / 60:.0f}분, 10분 시점 {p:.1f}W, 40분 시점 {p40:.1f}W, 방열판 최고 {t_max:.1f}°C, 셀 OCV {min(v):.3f}~{max(v):.3f}V")

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
assert dev.bal[0] is False and sum(dev.bal) == 3 and dev.duty == 0, dev.bal   # 발열 제한: 동시 3셀
ps = []
run_until(dev, lambda: ps.append(dev.progress()) or dev.state == "DONE", 16 * 3600)
v = [ocv(s) for s in dev.p.soc]
assert max(v) - min(v) <= 0.012, v
back = max(a - b for a, b in zip(ps, ps[1:]) if a is not None and b is not None)
assert back < 0.05, back   # 진행률은 이동평균 기준이라 노이즈로 크게 뒤로 가지 않음
assert dev.events.count("WARN") == 1, dev.events   # 50mV 기준을 지날 때 경고가 반복되지 않음
print(f"3 밸런싱 통과: 편차 {before * 1000:.0f}mV → {(max(v) - min(v)) * 1000:.1f}mV, {dev.t / 3600:.1f}시간")

# 4 용량 테스트: 측정 용량이 모델에서 종료 전압까지 뺄 수 있는 용량과 ±5%
dev = ready_dev()
start(dev, "CAPACITY")
run_until(dev, lambda: dev.state == "DONE", 4 * 3600)
expect = CAPACITY_AH * (1 - soc_at(CAP_END_V) / 100)
err = dev.cap_measured / expect - 1
assert abs(err) <= 0.05 and dev.status()["capMeasuredAh"] is not None, (dev.cap_measured, expect)
run_until(dev, lambda: "CHARGE_NEEDED" in dev.alarms, 5)   # 3.70V 미만으로 끝났으니 충전 필요 알림
print(f"4 용량 테스트 통과: 측정 {dev.cap_measured:.3f}Ah, 기대 {expect:.3f}Ah, 오차 {err * 100:+.1f}%, SOH {dev.soh}, 충전 필요 알림")

# 5 팬 정지: 팬 동작 중 fan_stop → 즉시 중단
dev = ready_dev()
start(dev)
run_until(dev, lambda: dev.fan_duty > 0, 600)
cmd(dev, cmd="fault", name="fan_stop")
dev.step()
s = dev.status()
assert dev.duty == 0 and s["state"] == "STOP" and "FAN_STOP" in s["alarms"] and "WARN" in s["events"], s
print("5 팬 정지 통과: 1주기 안에 듀티 0, FAN_STOP 경고")

# 6 과열 감속: 주변 온도 상승 → I_T 한도로 전류 감소, 방열판 95°C 이하 유지
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
assert seen_it and t_max <= 95 and dev.state == "RUN", (seen_it, t_max, dev.state, dev.alarms)
print(f"6 과열 감속 통과: I_T 한도 작동, 전류 {i_before:.2f}A → 최저 {i_min:.2f}A, 방열판 최고 {t_max:.1f}°C")

# 7 연결 불량: 밸런스 잭 분리 → 즉시 중단
dev = ready_dev()
start(dev)
run_until(dev, lambda: dev.t > 60, 70)
cmd(dev, cmd="fault", name="disconnect")
dev.step()
s = dev.status()
assert dev.duty == 0 and s["state"] == "STOP" and "CONN" in s["alarms"], s
cmd(dev, cmd="fault", name="clear")
dev.step()
assert max(abs(f - c) for f, c in zip(dev.v_filt, dev.cells)) < 0.01, dev.v_filt   # 재연결 직후 평균이 0에서 시작하지 않음
print("7 연결 불량 통과: 1주기 안에 듀티 0, CONN 경고, 재연결 후 필터 즉시 정상")

# 8 정지: 웹 정지 명령 → 즉시 듀티 0 (2S 배터리로)
dev = ready_dev(2)
start(dev)
run_until(dev, lambda: dev.t > 60, 70)
assert dev.duty > 0
cmd(dev, cmd="stop")
s = dev.status()
assert dev.duty == 0 and s["state"] == "STOP" and "STOP" in s["events"], s
print("8 정지 통과: 2S에서 정지 명령 즉시 듀티 0")

# 9 내부저항 높은 배터리: 진단에서 걸러 방전 거부, 진단은 허용
dev = Device(Plant(6, random.Random(0)))
cmd(dev, cmd="fault", name="high_ir")
run_until(dev, lambda: dev.state == "SELECT", 10)
run_until(dev, lambda: "HIGH_IR" in dev.alarms, 1)
assert dev.command({"cmd": "start", "mode": "STORAGE", "targetV": 3.80}) is not None
assert dev.command({"cmd": "start", "mode": "CAPACITY"}) is not None
assert dev.command({"cmd": "start", "mode": "BALANCE"}) is not None
cmd(dev, cmd="start", mode="DIAG")
print(f"9 IR 거부 통과: 셀 IR 최대 {max(dev.ir)}mΩ, 방전 모드 거부, 진단은 허용")

# 10 자동 밸런싱: 불균형 상태로 보관 방전 → 목표 도달 후 밸런싱으로 이어서 모든 셀을 맞춤
dev = ready_dev()
cmd(dev, cmd="fault", name="imbalance")
start(dev)
switched = False
for _ in range(int(16 * 3600 / DT)):
    dev.step()
    switched |= dev.mode == "BALANCE"
    if dev.state == "DONE":
        break
v = [ocv(s) for s in dev.p.soc]
assert switched and dev.state == "DONE" and max(v) - min(v) <= 0.012 and all(abs(x - 3.80) <= 0.05 for x in v), (switched, dev.state, v)
print(f"10 자동 밸런싱 통과: 보관 후 밸런싱 전환, 셀 OCV {min(v):.3f}~{max(v):.3f}V, {dev.t / 3600:.1f}시간")

# 11 PWM FET 단락: 듀티 0으로는 전류가 안 끊긴다 → 정지 명령이 보호 FET(DSG)로 끊는다
dev = ready_dev()
start(dev)
run_until(dev, lambda: dev.t > 120, 200)
dev.p.pwm_fet_short = True
run_until(dev, lambda: dev.current_avg > 4.5, 5)   # 6S 전체 인가 약 5A
i_short = dev.current_avg
cmd(dev, cmd="stop")
dev.step()
dev.step()   # 정지 다음 주기에 plant가 DSG 꺼짐을 반영하고, 그다음 측정에 나온다
assert dev.state == "STOP" and dev.p.current == 0 and dev.current_avg < 0.05, (dev.state, dev.p.current, dev.current_avg)
print(f"11 PWM FET 단락 통과: 단락 시 {i_short:.2f}A, 정지 후 보호 FET로 {dev.current_avg:.2f}A")

# 12 저전압 배터리: 셀 하나가 3.5V 아래면 진단 펄스도 걸지 않고, 방전 시작은 저전압 정지로 끝난다
dev = Device(Plant(6, random.Random(0)))
dev.p.soc[0] = soc_at(3.40)
d_max = 0.0
for _ in range(int(10 / DT)):
    dev.step()
    d_max = max(d_max, dev.duty)
    if dev.state == "SELECT":
        break
assert dev.state == "SELECT" and d_max == 0 and dev.ir is None and "UNDERVOLT" in dev.alarms, (dev.state, d_max, dev.ir, dev.alarms)
start(dev)
dev.step()
assert dev.state == "STOP" and dev.trip == "UNDERVOLT" and dev.duty == 0, (dev.state, dev.trip)
cmd(dev, cmd="fault", name="disconnect")
run_until(dev, lambda: dev.cell_count == 0, 5)
assert dev.command({"cmd": "start", "mode": "STORAGE", "targetV": 3.80}) is not None   # 배터리 없이는 시작 거부
print(f"12 저전압 배터리 통과: 최저 셀 3.40V, 진단 듀티 최대 {d_max:.0f}, 시작 시 {dev.trip} 정지, 배터리 없이 시작 거부")

# 명령 검증
assert dev.command({"cmd": "start", "mode": "STORAGE", "targetV": 4.1}) is not None
assert dev.command({"cmd": "start", "mode": "STORAGE", "capacityAh": True}) is not None
assert dev.command({"cmd": "fault", "name": "nope"}) is not None
assert "batteryId" not in s
cmd(dev, cmd="set", key="buzzerKeyTone", value=False)
print("명령 검증 통과")
