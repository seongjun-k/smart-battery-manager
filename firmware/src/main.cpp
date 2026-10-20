#include <Arduino.h>
#include <Wire.h>

#include "bq76952.h"
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

void setup() {
  Serial.begin(115200);
  ioInit();
  Wire.begin(PIN_SDA, PIN_SCL, 400000);
  oledInit();
  if (!bqInit()) {
    Serial.println("BQ76952 초기화 실패: I2C 배선과 전원을 확인");
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
    if (s == State::SELECT || s == State::DONE || s == State::HOLD || s == State::STOP)
      cmdStart(g.selMode, g.targetV, g.capacityAh);
  }

  wsPoll();

  static uint32_t last = 0;
  static uint32_t tick = 0;
  uint32_t now = millis();
  if (now - last >= CTRL_PERIOD_MS) {
    last += CTRL_PERIOD_MS;
    if (now - last >= CTRL_PERIOD_MS) last = now;   // 크게 밀렸으면 따라잡지 않고 다시 맞춘다
    stateMachine();
    if (++tick % STATUS_EVERY == 0) {
      wsBroadcast();
      oledUpdate();
    }
  }
  delay(1);
}
