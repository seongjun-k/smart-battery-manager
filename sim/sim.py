"""가상 배터리·열 모델 + 펌웨어 제어 로직 이식 + WebSocket 서버.

ESP32-S3 대신 보고서 6장과 같은 JSON을 ws://localhost:<port>/ws 로 제공한다.
실행: python sim/sim.py [--cells 6] [--speed 60] [--port 8080]
"""
import argparse
import asyncio
import json
import random
from bisect import bisect_left

# 모델 상수 (추정값, 실측 없음 — 시제품에서 재조정)
OCV_TABLE = [(0, 3.27), (5, 3.61), (10, 3.69), (20, 3.73), (30, 3.77), (40, 3.80),
             (50, 3.82), (60, 3.87), (70, 3.93), (80, 4.00), (90, 4.08), (100, 4.20)]
CAPACITY_AH = 2.2     # 가상 배터리 용량
R_CELL = 0.005        # 셀 내부저항 [Ω]
R_LOAD = 5.0          # 10Ω 20W ×2 병렬
C_TH = 150.0          # 방열판+저항 열용량 [J/°C]
R_TH_FAN = 1.6        # 팬 최대일 때 총 열저항 [°C/W] (보고서 열 설계)
R_TH_NAT = 5.0        # 팬 정지 시 [°C/W]
TAU_BATT = 300.0      # 배터리 온도 시정수 [s]
T_AMB = 25.0
FAN_RPM_MAX = 6000
NOISE_V = 0.002
NOISE_I = 0.005

# 제어 상수 (보고서 2·4장). 펌웨어 상수와 같은 값을 유지한다.
DT = 0.1
P_TARGET = 25.0
I_HW = 5.0
C_RATE = 1.0
KP, KI = 0.02, 0.1    # 임의값, 실측으로 재조정
MAX_STEP = 0.05       # 제어 주기당 듀티 변화 한도 (소프트 스타트 겸용)
TAPER_V = 0.10        # 목표 +0.10V부터 전류 감소
TAPER_MIN = 0.05      # 테이퍼 하한. 0이면 목표 전압에 끝내 닿지 못한다
REST_S = 30.0         # 펄스-휴지 종료 판정의 휴지 시간
REST_MARGIN = 0.02    # 휴지 후 OCV가 목표+이 값보다 높으면 더 방전
TARGET_PRESETS = (3.80, 3.85, 3.90)
V_CUTOFF = 3.5
IMBALANCE_V = 0.05
FAN_ON_T = 40.0
DIAG_DUTY = 0.5       # IR 측정 펄스 듀티 (1초)
DONE_HOLD_S = 5.0
I_BAL = 0.05          # BQ76952 내장 밸런싱 전류 [확인 필요] 하드웨어 논의 때 확정
BAL_ON_V = 0.005      # 최저 셀보다 이만큼 높은 셀을 밸런싱
BAL_DONE_V = 0.010    # 셀 간 전압 차가 이 이하면 밸런싱 완료
CAP_END_V = 3.60      # 용량 테스트 종료 전압 [확인 필요] 하드웨어 차단 3.5V보다 노이즈 여유를 둠
MODES = ("STORAGE", "BALANCE", "CAPACITY", "DIAG")
TRIP_ALARMS = {"CONN", "UNDERVOLT", "OVERTEMP_BATT", "OVERTEMP_SINK", "FAN_STOP"}


def clamp(x, lo, hi):
    return min(max(x, lo), hi)


def ocv(soc):
    soc = clamp(soc, 0.0, 100.0)
    i = max(1, bisect_left([s for s, _ in OCV_TABLE], soc))
    (s0, v0), (s1, v1) = OCV_TABLE[i - 1], OCV_TABLE[i]
    return v0 + (v1 - v0) * (soc - s0) / (s1 - s0)


def derate(t, t0, t1):
    return clamp((t1 - t) / (t1 - t0), 0.0, 1.0)


def compute_soh(ir_mohm, imbalance_v, cap_ratio=None):
    # 가중치·기준값은 실험 데이터 없이 정한 임의값 [확인 필요]
    s_ir = clamp((25 - max(ir_mohm)) / 20, 0, 1)   # 5mΩ 새것 → 25mΩ 폐기 (추정)
    s_imb = clamp(1 - imbalance_v / 0.10, 0, 1)
    if cap_ratio is None:   # 같은 연결에서 용량 테스트를 안 했을 때
        return round(100 * (0.6 * s_ir + 0.4 * s_imb))
    return round(100 * (0.4 * s_ir + 0.4 * clamp(cap_ratio, 0, 1) + 0.2 * s_imb))


class Plant:
    """가상 하드웨어: 셀, 방전 부하, 방열판, 팬. 결함 주입 대상."""

    def __init__(self, cells, rng):
        self.soc = [100.0] * cells
        self.r = [R_CELL] * cells
        self.rng = rng
        self.t_amb = self.t_sink = self.t_batt = T_AMB
        self.current = 0.0
        self.fan = 0.0
        self.fan_broken = False
        self.connected = True

    def step(self, duty, fan_cmd, bal, dt):
        i_on = sum(ocv(s) for s in self.soc) / (R_LOAD + sum(self.r))
        self.current = duty * i_on
        for k in range(len(self.soc)):
            i_cell = self.current + (I_BAL if bal[k] else 0.0)   # 밸런싱 전류는 팩 전류에 안 잡힌다
            self.soc[k] -= i_cell * dt / 3600 / CAPACITY_AH * 100
        self.fan = 0.0 if self.fan_broken else fan_cmd
        r_th = R_TH_NAT - (R_TH_NAT - R_TH_FAN) * self.fan
        p_load = duty * i_on ** 2 * R_LOAD
        self.t_sink += (p_load - (self.t_sink - self.t_amb) / r_th) * dt / C_TH
        self.t_batt += (self.t_amb - self.t_batt) * dt / TAU_BATT

    def inject(self, name):
        if name == "imbalance":
            self.soc[0] -= 10
        elif name == "fan_stop":
            self.fan_broken = True
        elif name == "overheat":
            self.t_amb = T_AMB + 15   # +25면 배터리 온도 45°C 차단이 먼저 걸려 방열판 감속을 못 본다
        elif name == "disconnect":
            self.connected = False
        elif name == "clear":
            self.fan_broken, self.t_amb, self.connected = False, T_AMB, True
        else:
            return f"알 수 없는 fault: {name}"
        return None

    # 측정 함수 — 펌웨어에서는 BQ76952 I2C 읽기로 바뀌는 부분
    def read_cells(self):
        if not self.connected:
            return [0.0] * len(self.soc)
        return [ocv(s) - self.current * r + self.rng.gauss(0, NOISE_V)
                for s, r in zip(self.soc, self.r)]

    def read_current(self):
        return self.current + self.rng.gauss(0, NOISE_I)

    def read_temps(self):
        return self.t_batt, self.t_sink

    def read_fan_rpm(self):
        return self.fan * FAN_RPM_MAX


class Device:
    """펌웨어 로직의 Python 이식: 상태 머신, 전류 제어, 경고. 펌웨어와 함께 고친다."""

    def __init__(self, plant):
        self.p = plant
        self.t = self.state_t = 0.0
        self.state = "IDLE"
        self.mode = None
        self.target_v = 3.80
        self.capacity_ah = CAPACITY_AH
        self.duty = self.integ = self.fan_duty = self.cap_acc = 0.0
        self.bal = [False] * len(plant.soc)
        self.limit = self.trip = self.rest_t = None
        self.alarms, self.events = [], []
        self.settings = {"buzzerKeyTone": True}
        self.ir = self.soh = self.cap_measured = None
        self.measure()

    def go(self, state):
        self.state, self.state_t = state, self.t

    def measure(self):
        self.cells = self.p.read_cells()
        self.current_avg = self.p.read_current()
        self.temp_batt, self.temp_sink = self.p.read_temps()
        self.fan_rpm = self.p.read_fan_rpm()
        self.cell_count = sum(v > 2.5 for v in self.cells)   # detectCellCount
        self.pack_v = sum(self.cells)

    def check_alarms(self):
        a = []
        if self.cell_count == 0:
            a.append("CONN")
        else:
            if max(self.cells) - min(self.cells) > IMBALANCE_V:
                a.append("IMBALANCE")
            if min(self.cells) < V_CUTOFF:
                a.append("UNDERVOLT")
        if self.temp_batt > 45:
            a.append("OVERTEMP_BATT")
        if self.temp_sink > 70:
            a.append("OVERTEMP_SINK")
        if self.fan_duty > 0 and self.fan_rpm == 0:
            a.append("FAN_STOP")
        if set(a) - set(self.alarms):
            self.events.append("WARN")
        self.alarms = a

    def compute_i_set(self):
        min_v = min(self.cells)
        limits = {
            "I_P": P_TARGET / self.pack_v,
            "I_C": self.capacity_ah * C_RATE,
            "I_T": min(derate(self.temp_batt, 40, 45), derate(self.temp_sink, 55, 70)) * I_HW,
            # 테이퍼는 보관 모드만. 용량 테스트는 종료 전압까지 정전력
            "I_V": clamp((min_v - self.target_v) / TAPER_V, TAPER_MIN, 1.0) * I_HW
                   if self.mode == "STORAGE" else I_HW,
            "I_HW": I_HW,
        }
        self.limit = min(limits, key=limits.get)
        return limits[self.limit]

    def control_step(self):
        i_set = self.compute_i_set()
        ff = i_set * R_LOAD / self.pack_v
        err = i_set - self.current_avg
        self.integ = clamp(self.integ + KI * err * DT, -0.2, 0.2)
        duty = clamp(ff + KP * err + self.integ, 0.0, 1.0)
        self.duty = clamp(duty, self.duty - MAX_STEP, self.duty + MAX_STEP)

    def halt(self, reason=None):
        """STOP 버튼·웹 정지·보호 동작 공통 경로. 즉시 듀티 0."""
        self.outputs_off()
        self.trip = reason
        self.go("STOP")
        if reason is None:
            self.events.append("STOP")

    def outputs_off(self):
        self.duty = self.integ = 0.0
        self.bal = [False] * len(self.bal)
        self.limit = self.rest_t = self.v_avg = None

    def finish(self):
        self.outputs_off()
        if self.mode == "CAPACITY":
            self.cap_measured = self.cap_acc
            if self.ir:
                self.soh = compute_soh(self.ir, max(self.cells) - min(self.cells), self.cap_ratio())
        self.go("DONE")
        self.events.append("DONE")

    def cap_ratio(self):
        return None if self.cap_measured is None else self.cap_measured / self.capacity_ah

    def step(self):
        self.p.step(self.duty, self.fan_duty, self.bal, DT)
        self.t += DT
        self.measure()
        # 팬 정지 판정은 직전 주기에 실제로 낸 팬 명령 기준. 새 명령을 먼저 넣으면 켜는 순간 오판한다.
        # ponytail: 실물 팬은 기동 지연이 있어 RPM 확인에 유예 시간이 필요하다 (시제품에서 측정)
        self.check_alarms()
        t = self.temp_sink
        self.fan_duty = 0.0 if t < FAN_ON_T else min(1.0, 0.3 + (t - FAN_ON_T) / 20)
        getattr(self, "on_" + self.state.lower())()

    def on_idle(self):
        if self.cell_count > 0:   # 새 연결: 이전 배터리의 측정 용량은 버린다
            self.cap_measured = None
            self.go("DIAG")

    def on_diag(self):
        # 1초 무부하 → 1초 펄스 부하, 전압 강하로 셀별 IR 산출 (estimateIR)
        if self.cell_count == 0:
            self.duty = 0.0
            return self.go("IDLE")
        el = self.t - self.state_t
        if el <= DT * 1.5:
            self.v_off, self.v_on, self.i_on = [], [], []
        if el < 1.0:
            self.v_off.append(self.cells)
        elif el < 2.0:
            self.duty = DIAG_DUTY
            if el > 1.2:
                self.v_on.append(self.cells)
                self.i_on.append(self.current_avg)
        else:
            self.duty = 0.0
            i = sum(self.i_on) / len(self.i_on)
            off = [sum(c) / len(c) for c in zip(*self.v_off)]
            on = [sum(c) / len(c) for c in zip(*self.v_on)]
            self.ir = [round((a - b) / i * 1000, 1) for a, b in zip(off, on)]
            self.soh = compute_soh(self.ir, max(off) - min(off), self.cap_ratio())
            self.go("SELECT")

    def on_select(self):
        if self.cell_count == 0:
            self.go("IDLE")

    def on_run(self):
        trip = TRIP_ALARMS.intersection(self.alarms)
        if trip:
            return self.halt(sorted(trip)[0])
        if self.mode == "BALANCE":
            return self.balance_step()
        if self.mode == "CAPACITY":
            return self.capacity_step()
        if self.rest_t is None:
            if min(self.cells) <= self.target_v:
                self.duty = self.integ = 0.0
                self.rest_t, self.limit = self.t, "REST"
            else:
                self.control_step()
        elif self.t - self.rest_t >= REST_S:
            if min(self.cells) > self.target_v + REST_MARGIN:
                self.rest_t = None
            else:
                self.finish()

    def balance_step(self):
        """BQ76952 내장 밸런싱: 최저 셀보다 높은 셀만 소량 방전. 메인 부하는 쓰지 않는다."""
        # 판정은 약 1초 이동평균으로. 순간값은 노이즈로 편차가 작게 보여 일찍 끝난다
        a = self.v_avg or self.cells
        self.v_avg = [x + 0.1 * (c - x) for x, c in zip(a, self.cells)]
        min_v = min(self.v_avg)
        if max(self.v_avg) - min_v <= BAL_DONE_V:
            return self.finish()
        self.bal = [v - min_v > BAL_ON_V for v in self.v_avg]

    def capacity_step(self):
        """정전력 방전하며 전하량 적산, 최저 셀이 종료 전압에 닿으면 용량 확정."""
        self.cap_acc += self.current_avg * DT / 3600
        if min(self.cells) <= CAP_END_V:
            return self.finish()
        self.control_step()

    def on_done(self):
        if self.t - self.state_t >= DONE_HOLD_S:
            self.go("HOLD")

    def on_hold(self):
        if self.cell_count == 0:
            self.go("IDLE")

    on_stop = on_hold

    def command(self, msg):
        """웹 명령 처리 (wsOnCommand). 오류면 메시지 문자열, 정상이면 None."""
        cmd = msg.get("cmd")
        if cmd == "stop":
            if self.state in ("RUN", "DIAG"):
                self.halt()
            return None
        if cmd == "start":
            mode = msg.get("mode")
            if mode not in MODES:
                return f"지원하지 않는 mode: {mode}"
            if self.state not in ("SELECT", "DONE", "HOLD", "STOP"):
                return f"{self.state} 상태에서는 시작할 수 없음"
            target = msg.get("targetV", 3.80)
            if target not in TARGET_PRESETS:
                return f"targetV는 {TARGET_PRESETS} 중 하나여야 함"
            cap = msg.get("capacityAh", CAPACITY_AH)
            if not isinstance(cap, (int, float)) or isinstance(cap, bool) or not 0 < cap <= 20:
                return "capacityAh는 0~20 사이 숫자여야 함"
            self.mode, self.target_v, self.capacity_ah = mode, target, cap
            self.outputs_off()
            self.trip = None
            self.cap_acc = 0.0
            self.go("DIAG" if mode == "DIAG" else "RUN")
            self.events.append("START")
            return None
        if cmd == "set":
            key, value = msg.get("key"), msg.get("value")
            if key not in self.settings or not isinstance(value, bool):
                return f"설정할 수 없는 key/value: {key}={value}"
            self.settings[key] = value
            return None
        if cmd == "fault":   # 시뮬레이터에서만 받는 명령
            return self.p.inject(msg.get("name"))
        return f"알 수 없는 cmd: {cmd}"

    def status(self):
        alarms = set(self.alarms) | ({self.trip} if self.trip else set())
        s = {
            "type": "status", "t": round(self.t, 1),
            "state": self.state, "mode": self.mode, "cellCount": self.cell_count,
            "cells": [round(v, 3) for v in self.cells],
            "packV": round(self.pack_v, 2), "current": round(self.current_avg, 2),
            "duty": round(self.duty, 3),
            "tempBatt": round(self.temp_batt, 1), "tempSink": round(self.temp_sink, 1),
            "fanRpm": round(self.fan_rpm),
            "limit": self.limit, "targetV": self.target_v, "soh": self.soh,
            "ir": self.ir,
            "capMeasuredAh": None if self.cap_measured is None else round(self.cap_measured, 3),
            "alarms": sorted(alarms), "events": self.events,
        }
        self.events = []
        return s


async def serve(dev, speed, port):
    from aiohttp import WSMsgType, web

    clients = set()

    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        clients.add(ws)
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    m = json.loads(msg.data)
                except json.JSONDecodeError:
                    m = None
                if isinstance(m, dict) and m.get("type") == "cmd":
                    err = dev.command(m)
                else:
                    err = "type이 cmd인 JSON 객체가 아님"
                if err:
                    await ws.send_json({"type": "error", "msg": err})
        finally:
            clients.discard(ws)
        return ws

    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "localhost", port).start()
    print(f"ws://localhost:{port}/ws  배속 x{speed}  (Ctrl+C 종료)")
    tick = 0
    while True:
        for _ in range(speed):
            dev.step()
        tick += 1
        if tick % 2 == 0:   # 실시간 5Hz 상태 전송
            text = json.dumps(dev.status())
            for ws in list(clients):
                try:
                    await ws.send_str(text)
                except ConnectionResetError:
                    clients.discard(ws)
        await asyncio.sleep(DT)   # ponytail: sleep 누적 드리프트 있음, 시연엔 무관


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="스마트 배터리 관리 디바이스 가상 하드웨어")
    ap.add_argument("--cells", type=int, default=6, choices=range(3, 7))
    ap.add_argument("--speed", type=int, default=60, help="시뮬레이션 배속 (1 = 실시간)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    try:
        asyncio.run(serve(Device(Plant(a.cells, random.Random(a.seed))), max(1, a.speed), a.port))
    except KeyboardInterrupt:
        pass
