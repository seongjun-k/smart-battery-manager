#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <driver/rtc_io.h>
#include <esp_sleep.h>

#include "bq76907.h"
#include "config.h"
#include "control.h"
#include "hal.h"
#include "io.h"
#include "oled.h"
#include "web.h"

static Mode nextMode(Mode m) {
  switch (m) {
    case Mode::STORAGE: return Mode::BALANCE;
    case Mode::BALANCE: return Mode::CAPACITY;
    case Mode::CAPACITY: return Mode::DIAG;
    default: return Mode::STORAGE;
  }
}

static void keyTone() {
  if (g.keyTone) buzzerPlay(Sound::KEY);
}

// 완료 후 SLEEP_AFTER_S가 지났을 때. 깨어나면 리셋과 같아서 setup()부터 다시 시작한다
static void enterDeepSleep() {
  Serial.println("완료 후 대기 시간이 지나 딥슬립에 들어감");
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_OFF);
  oledOff();
  ioHoldOff();   // 방전 게이트와 팬 PWM을 LOW로 고정 (PWM은 여기서 떼어낸다)
  if (!bqDeepSleep()) Serial.println("BQ76907 DEEPSLEEP 확인 실패");
  esp_sleep_enable_ext0_wakeup((gpio_num_t)PIN_BTN_OK, 0);
  rtc_gpio_pullup_en((gpio_num_t)PIN_BTN_OK);     // 딥슬립에서는 디지털 풀업이 꺼지므로 RTC 풀업을 쓴다
  rtc_gpio_pulldown_dis((gpio_num_t)PIN_BTN_OK);
  esp_deep_sleep_start();
}

void setup() {
  Serial.begin(115200);
  ioInit();
  Wire.begin(PIN_SDA, PIN_SCL, 400000);
  oledInit();
  if (!bqInit()) {
    Serial.println("BQ76907 초기화 실패: I2C 배선과 전원을 확인");
    buzzerPlay(Sound::ERROR);
  }
  controlInit();
  webInit();
}

void loop() {
  ioPoll();

  if (ioStopTriggered()) onStop();   // 게이트는 ISR이 이미 껐다. 여기서 상태를 STOP으로 맞춘다
  if (ioNextPressed()) {
    keyTone();
    if (g.state == State::SELECT) g.selMode = nextMode(g.selMode);
    else oledNextView();
  }
  if (ioOkPressed()) {
    keyTone();
    State s = g.state;
    if (s == State::SELECT || s == State::DONE || s == State::HOLD || s == State::STOP) {
      if (startRejectReason(g.selMode)) buzzerPlay(Sound::ERROR);   // HIGH_IR 등으로 방전 모드 거부 (웹 start 명령과 같은 규칙)
      else cmdStart(g.selMode, g.targetV, g.capacityAh);
    }
  }

  wsPoll();

  static uint32_t last = 0;
  static uint32_t tick = 0;
  uint32_t now = millis();
  if (now - last >= CTRL_PERIOD_MS) {
    last += CTRL_PERIOD_MS;
    if (now - last >= CTRL_PERIOD_MS) last = now;   // 크게 밀렸으면 따라잡지 않고 다시 맞춘다
    stateMachine();
    if (g.sleepNow) enterDeepSleep();
    if (++tick % STATUS_EVERY == 0) {
      wsBroadcast();
      oledUpdate();
    }
  }
  delay(1);
}
