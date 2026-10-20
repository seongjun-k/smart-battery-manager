#pragma once
// 핀, Wi-Fi, 주기, 제어 상수를 한 곳에 둔다.
// 제어 상수는 sim/sim.py와 같은 값을 유지한다. 한쪽을 바꾸면 다른 쪽도 고친다.
#include <stdint.h>

// ---- 핀 배정 (docs/결과보고서_초안.md 3-1 표) ----
constexpr int PIN_SDA = 8;           // BQ76907, OLED 공유
constexpr int PIN_SCL = 9;
constexpr int PIN_BQ_ALERT = 13;     // 현재 폴링 방식이라 입력으로만 둔다
constexpr int PIN_BTN_NEXT = 4;      // 내부 풀업, 누르면 LOW
constexpr int PIN_BTN_OK = 5;
constexpr int PIN_BTN_STOP = 6;
constexpr int PIN_BUZZER = 7;        // 패시브 부저 + NPN
constexpr int PIN_LOAD = 10;         // 방전 MOSFET 게이트
constexpr int PIN_FAN_PWM = 11;
constexpr int PIN_FAN_TACH = 12;

// ---- Wi-Fi (AP 모드만 사용) ----
#define WIFI_SSID "SmartBMS"
#define WIFI_PASS "smartbms1234"     // WPA2는 8자 이상이어야 한다
// 주소는 ESP32 기본값 192.168.4.1

// ---- 주기 ----
constexpr uint32_t CTRL_PERIOD_MS = 100;   // sim DT와 같다
constexpr uint32_t STATUS_EVERY = 2;       // 제어 주기 2번마다 상태 전송 = 5Hz

// ---- PWM (Arduino 코어 3.x LEDC) ----
// 해상도는 APB 80MHz에서 주파수별 최대치(20kHz 11비트, 25kHz 11비트) 안쪽으로 잡는다
constexpr uint32_t LOAD_PWM_HZ = 20000;
constexpr uint8_t LOAD_PWM_BITS = 10;
constexpr uint32_t FAN_PWM_HZ = 25000;     // 4핀 PWM 팬 표준
constexpr uint8_t FAN_PWM_BITS = 10;
constexpr uint32_t BUZZER_BASE_HZ = 2000;
constexpr uint8_t BUZZER_BITS = 8;

// ---- 팬 ----
constexpr int FAN_TACH_PULSES_PER_REV = 2;
constexpr uint32_t FAN_RPM_WINDOW_MS = 500;
constexpr double FAN_GRACE_S = 2.0;        // 팬을 켠 뒤 이 시간이 지나야 정지 판정 (기동 지연)

// ---- 측정 ----
constexpr int MAX_CELLS = 6;
constexpr float SHUNT_MOHM = 5.0f;         // 보고서 3-1: 5mΩ 션트. BQ 전류값(1mΩ 기준 mA)을 실제 전류로 환산한다
constexpr float CELL_PRESENT_V = 2.5f;     // sim: cell_count = (셀 > 2.5V)인 개수
constexpr float V_FILT_ALPHA = 0.1f;       // 약 1초 이동평균 (100ms 주기)

// ---- 제어 상수 (sim.py와 동일) ----
constexpr double DT = 0.1;
constexpr float P_TARGET = 25.0f;
constexpr float I_HW = 5.0f;
constexpr float C_RATE = 1.0f;
constexpr float KP = 0.02f, KI = 0.1f;     // 임의값, 실측으로 재조정
constexpr float MAX_STEP = 0.05f;          // 제어 주기당 듀티 변화 한도 (소프트 스타트 겸용)
constexpr float TAPER_V = 0.10f;
constexpr float TAPER_MIN = 0.05f;
constexpr double REST_S = 30.0;
constexpr float REST_MARGIN = 0.02f;
constexpr float V_CUTOFF = 3.5f;
constexpr float IMBALANCE_V = 0.05f;
constexpr float IMBALANCE_HYST_V = 0.010f; // 경고가 켜진 뒤엔 이만큼 더 내려가야 꺼진다
constexpr float FAN_ON_T = 40.0f;
constexpr float DIAG_DUTY = 0.5f;
constexpr double DONE_HOLD_S = 5.0;
constexpr int BAL_MAX_CELLS = 3;           // 칩 발열 때문에 동시에 밸런싱하는 셀 수 상한
constexpr float BAL_AUTO_V = 0.015f;       // 보관 방전이 끝났을 때 셀 편차가 이보다 크면 밸런싱으로 자동 전환
constexpr float BAL_ON_V = 0.005f;
constexpr float BAL_DONE_V = 0.010f;
constexpr float CAP_END_V = 3.60f;
constexpr float CHARGE_V = 3.70f;          // 실행 중이 아닐 때 최저 셀이 이보다 낮으면 CHARGE_NEEDED
constexpr float CHARGE_HYST_V = 0.020f;    // 켜진 뒤엔 이만큼 더 올라야 꺼진다
constexpr float IR_LIMIT_MOHM = 25.0f;     // 셀 IR이 이보다 크면 HIGH_IR, 방전 거부
constexpr float CAPACITY_AH = 2.2f;        // 웹에서 값을 안 주면 쓰는 기본 용량
constexpr float R_LOAD = 5.0f;             // TO-247 후막 저항 TEH100 5Ω 1개
constexpr float TEMP_SINK_DERATE = 80.0f, TEMP_SINK_TRIP = 95.0f;
constexpr float TARGET_PRESETS[3] = {3.80f, 3.85f, 3.90f};

// ---- 완료 후 딥슬립 ----
// DONE 진입 후 이 시간이 지나면 AP·OLED·팬·BQ를 끄고 OK 버튼(GPIO5, LOW)으로 깨운다
constexpr double SLEEP_AFTER_S = 600.0;
