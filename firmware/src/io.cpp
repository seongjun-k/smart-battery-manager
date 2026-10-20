#include "io.h"

#include <Arduino.h>
#include <esp_rom_gpio.h>
#include <soc/gpio_reg.h>
#include <soc/gpio_sig_map.h>
#include <soc/soc.h>

#include "hal.h"

// ---------------- 방전 게이트·팬 PWM ----------------

static uint32_t dutyCounts(float duty, uint8_t bits) {
  if (!(duty > 0)) return 0;   // NaN 포함
  if (duty >= 1) duty = 1;
  return (uint32_t)lroundf(duty * ((1u << bits) - 1));
}

void setLoadDuty(float duty) { ledcWrite(PIN_LOAD, dutyCounts(duty, LOAD_PWM_BITS)); }

void setFanDuty(float duty) { ledcWrite(PIN_FAN_PWM, dutyCounts(duty, FAN_PWM_BITS)); }

// ---------------- STOP 버튼 ----------------

static volatile bool stopFlag = false;

// ISR에서 ledcWrite()는 쓰지 않는다: 내부의 ledc_set_duty()가 IRAM 보장이 없고 락을 잡는다.
// 대신 게이트 핀을 LEDC 신호에서 떼어 GPIO 출력 레지스터로 직접 LOW로 만든다 (ROM 함수와 레지스터 쓰기뿐).
static void IRAM_ATTR stopIsr() {
  esp_rom_gpio_connect_out_signal(PIN_LOAD, SIG_GPIO_OUT_IDX, false, false);
  REG_WRITE(GPIO_OUT_W1TC_REG, 1u << PIN_LOAD);
  REG_WRITE(GPIO_ENABLE_W1TS_REG, 1u << PIN_LOAD);
  stopFlag = true;
}

bool ioStopTriggered() {
  if (!stopFlag) return false;
  stopFlag = false;
  // 게이트를 LEDC에 되돌린다. 듀티 0으로 시작하므로 다음 시작 명령 전까지 출력은 꺼져 있다
  ledcDetach(PIN_LOAD);
  ledcAttach(PIN_LOAD, LOAD_PWM_HZ, LOAD_PWM_BITS);
  ledcWrite(PIN_LOAD, 0);
  return true;
}

// ---------------- 일반 버튼 (폴링 + 30ms 디바운스) ----------------

struct Btn {
  uint8_t pin;
  bool raw, stable;
  uint32_t t;
};
static Btn btnNext{(uint8_t)PIN_BTN_NEXT, false, false, 0};
static Btn btnOk{(uint8_t)PIN_BTN_OK, false, false, 0};

static bool pressedEdge(Btn &b) {
  bool r = digitalRead(b.pin) == LOW;
  uint32_t now = millis();
  if (r != b.raw) {
    b.raw = r;
    b.t = now;
  }
  if (now - b.t >= 30 && b.stable != b.raw) {
    b.stable = b.raw;
    return b.stable;
  }
  return false;
}

bool ioNextPressed() { return pressedEdge(btnNext); }
bool ioOkPressed() { return pressedEdge(btnOk); }

// ---------------- 팬 TACH ----------------

static volatile uint32_t tachCount = 0;
static void IRAM_ATTR tachIsr() { tachCount = tachCount + 1; }

float readFanRpm() {
  static uint32_t lastMs = 0, lastCount = 0;
  static float rpm = 0;
  uint32_t now = millis();
  if (now - lastMs >= FAN_RPM_WINDOW_MS) {
    uint32_t c = tachCount;
    rpm = (c - lastCount) * 60000.0f / (now - lastMs) / FAN_TACH_PULSES_PER_REV;
    lastCount = c;
    lastMs = now;
  }
  return rpm;
}

// ---------------- 부저 ----------------

struct Step {
  uint16_t hz, ms;   // hz 0 = 무음
};
struct Pattern {
  const Step *s;
  uint8_t n, prio;
};

// 보고서 4장: 버튼음 약 2kHz 30~50ms, 시작 상승 2음, 완료 긴 3음 3회, STOP 하강음, 경고 빠른 연속 비프, 오류 낮은 장음
static const Step P_KEY[] = {{2000, 40}};
static const Step P_START[] = {{1500, 80}, {0, 30}, {2200, 120}};
static const Step P_DONE[] = {{2000, 400}, {0, 150}, {2000, 400}, {0, 150}, {2000, 400}};
static const Step P_STOP[] = {{2200, 120}, {0, 30}, {1200, 250}};
static const Step P_WARN[] = {{2500, 60}, {0, 60}, {2500, 60}, {0, 60}, {2500, 60}, {0, 60}, {2500, 60}};
static const Step P_ERROR[] = {{400, 800}};

// 순서는 enum class Sound와 같다. prio가 낮은 소리는 재생 중인 높은 소리를 끊지 못한다
static const Pattern PATTERNS[] = {
    {P_KEY, 1, 0},
    {P_START, 3, 1},
    {P_DONE, 5, 1},
    {P_STOP, 3, 2},
    {P_WARN, 7, 2},
    {P_ERROR, 1, 2},
};

static const Pattern *cur = nullptr;
static uint8_t curIdx = 0;
static uint32_t stepEnd = 0;

static void startStep() {
  const Step &st = cur->s[curIdx];
  ledcWriteTone(PIN_BUZZER, st.hz);   // 0이면 듀티 0
  stepEnd = millis() + st.ms;
}

void buzzerPlay(Sound s) {
  const Pattern &p = PATTERNS[(int)s];
  if (cur && p.prio < cur->prio) return;
  cur = &p;
  curIdx = 0;
  startStep();
}

void ioPoll() {
  if (!cur || (int32_t)(millis() - stepEnd) < 0) return;
  if (++curIdx >= cur->n) {
    cur = nullptr;
    ledcWrite(PIN_BUZZER, 0);
    return;
  }
  startStep();
}

// ---------------- 초기화 ----------------

void ioInit() {
  ledcAttach(PIN_LOAD, LOAD_PWM_HZ, LOAD_PWM_BITS);
  ledcWrite(PIN_LOAD, 0);
  ledcAttach(PIN_FAN_PWM, FAN_PWM_HZ, FAN_PWM_BITS);
  ledcWrite(PIN_FAN_PWM, 0);
  ledcAttach(PIN_BUZZER, BUZZER_BASE_HZ, BUZZER_BITS);
  ledcWrite(PIN_BUZZER, 0);

  pinMode(PIN_BTN_NEXT, INPUT_PULLUP);
  pinMode(PIN_BTN_OK, INPUT_PULLUP);
  pinMode(PIN_BTN_STOP, INPUT_PULLUP);
  pinMode(PIN_BQ_ALERT, INPUT);
  pinMode(PIN_FAN_TACH, INPUT_PULLUP);   // 오픈 컬렉터 TACH

  attachInterrupt(PIN_BTN_STOP, stopIsr, FALLING);
  attachInterrupt(PIN_FAN_TACH, tachIsr, FALLING);
}
