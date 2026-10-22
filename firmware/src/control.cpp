#include "control.h"

#include <math.h>
#include <stdio.h>

#include "hal.h"

Device g;

static float clampf(float x, float lo, float hi) { return fminf(fmaxf(x, lo), hi); }

static float derate(float t, float t0, float t1) { return clampf((t1 - t) / (t1 - t0), 0.0f, 1.0f); }

static float minOf(const float *v, int n) {
  float m = v[0];
  for (int i = 1; i < n; i++) m = fminf(m, v[i]);
  return m;
}

static float maxOf(const float *v, int n) {
  float m = v[0];
  for (int i = 1; i < n; i++) m = fmaxf(m, v[i]);
  return m;
}

const char *stateName(State s) {
  static const char *const N[] = {"IDLE", "DIAG", "SELECT", "RUN", "DONE", "HOLD", "STOP"};
  return N[(int)s];
}

const char *modeName(Mode m) {
  static const char *const N[] = {nullptr, "STORAGE", "BALANCE", "CAPACITY", "DIAG"};
  return N[(int)m];
}

const char *limitName(Limit l) {
  static const char *const N[] = {nullptr, "I_P", "I_C", "I_T", "I_V", "I_HW", "REST"};
  return N[(int)l];
}

const char *eventName(Event e) {
  static const char *const N[] = {"START", "DONE", "STOP", "WARN"};
  return N[(int)e];
}

const char *alarmName(uint8_t bit) {
  static const char *const N[] = {"CHARGE_NEEDED", "CONN", "FAN_STOP", "HIGH_IR", "IMBALANCE", "OVERTEMP_SINK", "UNDERVOLT"};
  return N[__builtin_ctz(bit)];
}

static void go(State s) {
  g.state = s;
  g.stateT = g.t;
}

static void addEvent(Event e) {
  if (g.nEvents < MAX_EVENTS) g.events[g.nEvents++] = e;
  static const Sound S[] = {Sound::START, Sound::DONE, Sound::STOP, Sound::WARN};
  buzzerPlay(S[(int)e]);
}

// detectCellCount: 2.5V를 넘는 셀 수. 셀 벡터 길이는 측정값이 있는 가장 높은 번호의 셀까지(sim은 전체 목록).
// 방전된 셀은 낮은 값 그대로 남아 UNDERVOLT로 걸린다.
static void measure() {
  float raw[MAX_CELLS];
  readCells(raw);
  int top = 0, cnt = 0;
  for (int i = 0; i < MAX_CELLS; i++) {
    if (raw[i] > CELL_PRESENT_V) cnt++;
    if (raw[i] > 0) top = i + 1;
  }
  g.cellCount = cnt;
  if (top > 0) g.nCells = top;   // 끊기면 마지막 길이를 유지해 웹 셀 카드 수가 흔들리지 않게 한다
  for (int i = 0; i < MAX_CELLS; i++) g.cells[i] = (top > 0 && i < top) ? raw[i] : 0.0f;
  g.currentAvg = readCurrent();
  g.tempSink = readTemp();
  g.fanRpm = readFanRpm();
  g.packV = 0;
  for (int i = 0; i < g.nCells; i++) g.packV += g.cells[i];
  // 약 1초 이동평균. 불균형 경고·밸런싱 판정용 (순간값은 노이즈로 셀 편차가 흔들린다)
  // 끊기면 비운다. 0V를 남기면 재연결 후 약 3초간 평균이 0에서 올라와 셀 편차를 작게 본다
  if (g.cellCount == 0) {
    g.vFiltValid = false;
  } else if (!g.vFiltValid) {
    for (int i = 0; i < MAX_CELLS; i++) g.vFilt[i] = g.cells[i];
    g.vFiltValid = true;
  } else {
    for (int i = 0; i < g.nCells; i++) g.vFilt[i] += V_FILT_ALPHA * (g.cells[i] - g.vFilt[i]);
  }
}

static void checkAlarms() {
  uint8_t a = 0;
  if (g.cellCount == 0) {
    a |= AL_CONN;
  } else {
    // 이동평균 + 히스테리시스: 켜진 뒤엔 10mV 더 내려가야 꺼진다. 없으면 기준 근처에서 경고음이 반복된다
    bool on = g.alarms & AL_IMBALANCE;
    if (maxOf(g.vFilt, g.nCells) - minOf(g.vFilt, g.nCells) > IMBALANCE_V - (on ? IMBALANCE_HYST_V : 0.0f))
      a |= AL_IMBALANCE;
    if (minOf(g.cells, g.nCells) < V_CUTOFF) a |= AL_UNDERVOLT;   // 보호 판정은 순간값
    // 장치는 충전을 못 하므로 알림만. 실행 중엔 판정하지 않는다 (용량 테스트 도중 경고음 방지)
    bool cn = g.alarms & AL_CHARGE_NEEDED;
    if (g.state != State::RUN && minOf(g.vFilt, g.nCells) < CHARGE_V + (cn ? CHARGE_HYST_V : 0.0f)) a |= AL_CHARGE_NEEDED;
    // 배터리 온도 센서가 없어 IR로 손상 배터리를 거른다
    if (g.irN > 0 && maxOf(g.ir, g.irN) > IR_LIMIT_MOHM) a |= AL_HIGH_IR;
  }
  if (g.tempSink > TEMP_SINK_TRIP) a |= AL_OVERTEMP_SINK;
  // 판정 기준은 직전 주기에 실제로 낸 팬 명령(fanDuty). 새 명령을 먼저 넣으면 켜는 순간 오판한다.
  // 실물 팬은 기동 지연이 있어 켠 뒤 FAN_GRACE_S가 지나야 회전수 0을 정지로 본다.
  if (g.fanDuty > 0 && g.fanOnT >= 0 && g.t - g.fanOnT >= FAN_GRACE_S && g.fanRpm == 0) a |= AL_FAN_STOP;
  if (a & ~g.alarms) addEvent(EV_WARN);
  g.alarms = a;
}

// computeISet: I_P, I_C, I_T, I_V, I_HW 중 최솟값. 같으면 앞의 것을 limit으로 남긴다 (sim의 dict 순서)
static float computeISet() {
  float minV = minOf(g.cells, g.nCells);
  float lim[5];
  lim[0] = P_TARGET / g.packV;
  lim[1] = g.capacityAh * C_RATE;
  lim[2] = derate(g.tempSink, TEMP_SINK_DERATE, TEMP_SINK_TRIP) * I_HW;
  // 테이퍼는 보관 모드만. 용량 테스트는 종료 전압까지 정전력
  lim[3] = g.mode == Mode::STORAGE ? clampf((minV - g.targetV) / TAPER_V, TAPER_MIN, 1.0f) * I_HW : I_HW;
  lim[4] = I_HW;
  int k = 0;
  for (int i = 1; i < 5; i++)
    if (lim[i] < lim[k]) k = i;
  g.limit = (Limit)(k + 1);
  return lim[k];
}

static void controlStep() {
  float iSet = computeISet();
  float ff = iSet * R_LOAD / g.packV;
  float err = iSet - g.currentAvg;
  g.integ = clampf(g.integ + KI * err * (float)DT, -0.2f, 0.2f);   // 적분 포화 방지
  float d = clampf(ff + KP * err + g.integ, 0.0f, 1.0f);
  g.duty = clampf(d, g.duty - MAX_STEP, g.duty + MAX_STEP);        // 기울기 제한
}

static void outputsOff() {
  g.duty = g.integ = 0;
  for (int i = 0; i < MAX_CELLS; i++) g.bal[i] = false;
  g.limit = Limit::NONE;
  g.restActive = false;
}

// STOP 버튼·웹 정지·보호 동작 공통 경로. 즉시 듀티 0
static void halt(uint8_t reason = 0) {
  outputsOff();
  g.trip = reason;
  go(State::STOP);
  if (!reason) addEvent(EV_STOP);
}

static int computeSOH(float maxIrMohm, float imbalanceV, float capRatio) {
  // 가중치·기준값은 실험 데이터 없이 정한 임의값 [확인 필요]
  float sIr = clampf((25.0f - maxIrMohm) / 20.0f, 0, 1);   // 5mΩ 새것 → 25mΩ 폐기 (추정)
  float sImb = clampf(1.0f - imbalanceV / 0.10f, 0, 1);
  if (capRatio < 0) return lroundf(100.0f * (0.6f * sIr + 0.4f * sImb));   // 용량 테스트를 안 했을 때
  return lroundf(100.0f * (0.4f * sIr + 0.4f * clampf(capRatio, 0, 1) + 0.2f * sImb));
}

static float capRatio() { return g.capValid ? g.capMeasured / g.capacityAh : -1.0f; }

static void finish() {
  outputsOff();
  if (g.mode == Mode::CAPACITY) {
    g.capMeasured = g.capAcc;
    g.capValid = true;
    if (g.irN > 0) {
      float imb = maxOf(g.cells, g.nCells) - minOf(g.cells, g.nCells);
      g.soh = computeSOH(maxOf(g.ir, g.irN), imb, capRatio());
    }
  }
  go(State::DONE);
  g.doneT = g.t;
  addEvent(EV_DONE);
}

float progress() {
  if (g.state == State::DONE) return 1.0f;
  if (g.state != State::RUN || !g.runValid) return NAN;
  float lo = minOf(g.cells, g.nCells), span, done;
  if (g.mode == Mode::BALANCE) {   // 완료 판정과 같은 이동평균. 순간값은 노이즈로 진행률이 들쭉날쭉하다
    const float *v = g.vFiltValid ? g.vFilt : g.cells;
    span = g.d0 - BAL_DONE_V;
    done = g.d0 - (maxOf(v, g.nCells) - minOf(v, g.nCells));
  } else {
    float end = g.mode == Mode::CAPACITY ? CAP_END_V : g.targetV;
    span = g.v0 - end;
    done = g.v0 - lo;
  }
  return span > 0 ? roundf(clampf(done / span, 0, 1) * 1000.0f) / 1000.0f : NAN;
}

static void onIdle() {
  if (g.cellCount > 0) {   // 새 연결: 이전 배터리의 측정 용량·IR·SOH는 버린다
    g.capValid = false;
    g.irN = 0;
    g.soh = -1;
    go(State::DIAG);
  }
}

// estimateIR: 1초 무부하 → 1초 펄스 부하, 전압 강하로 셀별 IR 산출
static void onDiag() {
  if (g.cellCount == 0) {
    g.duty = 0;
    return go(State::IDLE);
  }
  if (TRIP_ALARMS & g.alarms) {   // 저전압·과열·팬 정지 상태에서는 펄스 부하를 걸지 않는다. IR 없이 모드 선택으로
    g.duty = 0;
    g.irN = 0;
    g.soh = -1;
    return go(State::SELECT);
  }
  double el = g.t - g.stateT;
  if (el <= DT * 1.5) {
    for (int i = 0; i < MAX_CELLS; i++) g.vOffSum[i] = g.vOnSum[i] = 0;
    g.iOnSum = 0;
    g.nOff = g.nOn = 0;
  }
  if (el < 1.0) {
    for (int i = 0; i < g.nCells; i++) g.vOffSum[i] += g.cells[i];
    g.nOff++;
  } else if (el < 2.0) {
    g.duty = DIAG_DUTY;
    if (el > 1.2) {
      for (int i = 0; i < g.nCells; i++) g.vOnSum[i] += g.cells[i];
      g.iOnSum += g.currentAvg;
      g.nOn++;
    }
  } else {
    g.duty = 0;
    // 펄스 전류가 0이면 나눗셈이 무의미하다(MOSFET 불량 등). IR·SOH를 비우고 모드 선택으로 넘어간다
    float i = g.nOn ? g.iOnSum / g.nOn : 0.0f;
    if (g.nOff > 0 && i >= 0.05f) {
      float off[MAX_CELLS];
      for (int k = 0; k < g.nCells; k++) {
        off[k] = g.vOffSum[k] / g.nOff;
        float on = g.vOnSum[k] / g.nOn;
        g.ir[k] = roundf((off[k] - on) / i * 10000.0f) / 10.0f;
      }
      g.irN = g.nCells;
      g.soh = computeSOH(maxOf(g.ir, g.irN), maxOf(off, g.nCells) - minOf(off, g.nCells), capRatio());
    } else {
      g.irN = 0;
      g.soh = -1;
    }
    go(State::SELECT);
  }
}

static void onSelect() {
  if (g.cellCount == 0) go(State::IDLE);
}

// BQ76907 내장 밸런싱: 최저 셀보다 높은 셀만 소량 방전. 메인 부하는 쓰지 않는다
static void balanceStep() {
  // 판정은 이동평균으로. 순간값은 노이즈로 편차가 작게 보여 일찍 끝난다
  float minV = minOf(g.vFilt, g.nCells);
  if (maxOf(g.vFilt, g.nCells) - minV <= BAL_DONE_V) return finish();
  // 발열 제한: 기준을 넘는 셀 중 가장 높은 BAL_MAX_CELLS개만. 전압이 같으면 번호가 큰 셀이 먼저 (sim의 sorted 뒤쪽)
  for (int i = 0; i < MAX_CELLS; i++) g.bal[i] = false;
  for (int k = 0; k < BAL_MAX_CELLS; k++) {
    int best = -1;
    for (int i = 0; i < g.nCells; i++)
      if (!g.bal[i] && g.vFilt[i] - minV > BAL_ON_V && (best < 0 || g.vFilt[i] >= g.vFilt[best])) best = i;
    if (best < 0) break;
    g.bal[best] = true;
  }
}

// 정전력 방전하며 전하량 적산, 최저 셀이 종료 전압에 닿으면 용량 확정
static void capacityStep() {
  g.capAcc += g.currentAvg * (float)DT / 3600.0f;
  if (minOf(g.cells, g.nCells) <= CAP_END_V) return finish();
  controlStep();
}

static void onRun() {
  uint8_t trip = TRIP_ALARMS & g.alarms;
  if (trip) return halt(trip & -trip);   // 가장 낮은 비트 = 알파벳 첫 이름 (sim의 sorted()[0])
  if (g.mode == Mode::BALANCE) return balanceStep();
  if (g.mode == Mode::CAPACITY) return capacityStep();
  if (!g.restActive) {
    if (minOf(g.cells, g.nCells) <= g.targetV) {
      g.duty = g.integ = 0;
      g.restActive = true;
      g.restT = g.t;
      g.limit = Limit::REST;
    } else {
      controlStep();
    }
  } else if (g.t - g.restT >= REST_S) {
    if (minOf(g.cells, g.nCells) > g.targetV + REST_MARGIN) {
      g.restActive = false;
    } else if (maxOf(g.vFilt, g.nCells) - minOf(g.vFilt, g.nCells) > BAL_AUTO_V) {
      // 최저 셀이 목표에 닿았는데 다른 셀이 높으면 밸런싱으로 이어서 맞춘다 (계획서 3.5)
      outputsOff();
      g.mode = Mode::BALANCE;
      g.d0 = maxOf(g.vFilt, g.nCells) - minOf(g.vFilt, g.nCells);
    } else {
      finish();
    }
  }
}

static void onDone() {
  if (g.t - g.stateT >= DONE_HOLD_S) go(State::HOLD);
}

static void onHold() {
  if (g.cellCount == 0) go(State::IDLE);
  else if (g.state == State::HOLD && g.t - g.doneT >= SLEEP_AFTER_S) g.sleepNow = true;   // DONE은 5초 뒤 HOLD로 넘어가므로 여기서 판정
}

void applyOutputs() {
  setDischargeAllowed(g.state == State::RUN || g.state == State::DIAG);
  setLoadDuty(g.duty);
  setFanDuty(g.fanDuty);
  setBalance(g.bal, g.nCells);
}

void controlInit() { measure(); }

void stateMachine() {
  g.t += DT;
  measure();
  checkAlarms();
  float t = g.tempSink;
  g.fanDuty = t < FAN_ON_T ? 0.0f : fminf(1.0f, 0.3f + (t - FAN_ON_T) / 20.0f);
  if (g.fanDuty <= 0) g.fanOnT = -1;
  else if (g.fanOnT < 0) g.fanOnT = g.t;
  switch (g.state) {
    case State::IDLE: onIdle(); break;
    case State::DIAG: onDiag(); break;
    case State::SELECT: onSelect(); break;
    case State::RUN: onRun(); break;
    case State::DONE: onDone(); break;
    case State::HOLD:
    case State::STOP: onHold(); break;
  }
  applyOutputs();
}

void onStop() {
  if (g.state == State::RUN || g.state == State::DIAG) halt();
  applyOutputs();
}

const char *startRejectReason(Mode m) {
  static char err[128];
  if (g.cellCount == 0) return "배터리가 연결되지 않음";
  if (m == Mode::DIAG || !(g.alarms & AL_HIGH_IR)) return nullptr;
  snprintf(err, sizeof err, "내부저항이 %.1fmΩ으로 높아 방전할 수 없음. 부푼 배터리인지 확인", maxOf(g.ir, g.irN));
  return err;
}

void cmdStart(Mode m, float targetV, float capacityAh) {
  g.mode = m;
  g.selMode = m;   // 다음에 OK만 누르면 같은 모드를 다시 시작
  g.targetV = targetV;
  g.capacityAh = capacityAh;
  outputsOff();
  g.trip = 0;
  g.capAcc = 0;
  float lo = minOf(g.cells, g.nCells);
  g.runT0 = g.t;
  g.v0 = lo;
  const float *v = g.vFiltValid ? g.vFilt : g.cells;
  g.d0 = maxOf(v, g.nCells) - minOf(v, g.nCells);
  g.runValid = true;
  go(m == Mode::DIAG ? State::DIAG : State::RUN);
  addEvent(EV_START);
  applyOutputs();
}
