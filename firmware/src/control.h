#pragma once
// sim/sim.py의 Device 클래스를 C++로 옮긴 상태 머신·전류 제어·경고.
// 식과 순서를 sim.py와 같게 유지한다. 한쪽을 바꾸면 다른 쪽도 고친다.
#include "config.h"

enum class State : uint8_t { IDLE, DIAG, SELECT, RUN, DONE, HOLD, STOP };
enum class Mode : uint8_t { NONE, STORAGE, BALANCE, CAPACITY, DIAG };
enum class Limit : uint8_t { NONE, I_P, I_C, I_T, I_V, I_HW, REST };
enum Event : uint8_t { EV_START, EV_DONE, EV_STOP, EV_WARN };

// 비트 순서 = 이름의 알파벳 순서. 낮은 비트부터 내보내면 sim의 sorted(alarms)와 같다
enum Alarm : uint8_t {
  AL_CONN = 1, AL_FAN_STOP = 2, AL_IMBALANCE = 4,
  AL_OVERTEMP_BATT = 8, AL_OVERTEMP_SINK = 16, AL_UNDERVOLT = 32,
};
constexpr uint8_t TRIP_ALARMS = AL_CONN | AL_UNDERVOLT | AL_OVERTEMP_BATT | AL_OVERTEMP_SINK | AL_FAN_STOP;
constexpr int MAX_EVENTS = 8;

struct Device {
  double t = 0, stateT = 0;
  State state = State::IDLE;
  Mode mode = Mode::NONE;
  Mode selMode = Mode::STORAGE;     // OK 버튼으로 시작할 모드. NEXT로 바꾼다
  float targetV = 3.80f, capacityAh = CAPACITY_AH;
  float duty = 0, integ = 0, fanDuty = 0, capAcc = 0;
  bool bal[MAX_CELLS] = {};
  Limit limit = Limit::NONE;
  uint8_t trip = 0;                 // 보호 동작으로 멈춘 원인 (Alarm 비트 하나)
  uint8_t alarms = 0;
  bool restActive = false;
  double restT = 0;
  Event events[MAX_EVENTS];
  uint8_t nEvents = 0;
  bool keyTone = true;              // settings.buzzerKeyTone

  int soh = -1;                     // -1 = 없음(null)
  float ir[MAX_CELLS] = {};
  int irN = 0;                      // 0 = 없음(null)
  bool capValid = false;
  float capMeasured = 0;

  bool runValid = false;            // 진행률 기준: 시작 시각, 최저 셀 전압, 셀 편차
  double runT0 = 0;
  float v0 = 0, d0 = 0;

  // 측정값
  float cells[MAX_CELLS] = {};
  int nCells = MAX_CELLS;           // cells[]의 유효 길이. 연결이 끊기면 마지막 길이를 유지한다
  int cellCount = 0;                // detectCellCount: 2.5V 넘는 셀 수
  float vFilt[MAX_CELLS] = {};
  bool vFiltValid = false;
  float packV = 0, currentAvg = 0, tempBatt = 25, tempSink = 25, fanRpm = 0;
  double fanOnT = -1;               // 팬 명령이 켜진 시각, 꺼져 있으면 -1

  // 진단(estimateIR) 누적: sim의 v_off/v_on/i_on 리스트 대신 합계와 개수
  float vOffSum[MAX_CELLS] = {}, vOnSum[MAX_CELLS] = {}, iOnSum = 0;
  int nOff = 0, nOn = 0;
};

extern Device g;

const char *stateName(State s);
const char *modeName(Mode m);              // NONE이면 nullptr
const char *limitName(Limit l);            // NONE이면 nullptr
const char *eventName(Event e);
const char *alarmName(uint8_t bit);       // Alarm 비트 하나 -> 이름

void controlInit();
void stateMachine();                       // 100ms마다 한 번 (sim.step)
void onStop();                             // STOP 버튼·웹 정지 공통 경로
void cmdStart(Mode m, float targetV, float capacityAh);  // wsOnCommand가 검증한 뒤 호출
void applyOutputs();                       // 듀티·팬·밸런싱을 하드웨어에 반영
float progress();                          // 0~1, 없으면 NaN
