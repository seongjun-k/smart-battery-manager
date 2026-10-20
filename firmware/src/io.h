#pragma once
// 버튼, PWM 출력(방전 게이트·팬·부저), 팬 TACH. hal.h의 출력·팬 함수를 구현한다.
#include "config.h"

void ioInit();
void ioPoll();                 // 부저 시퀀서를 진행시킨다. loop()에서 자주 호출
bool ioNextPressed();          // 눌림 에지마다 한 번 true
bool ioOkPressed();
bool ioStopTriggered();        // STOP 인터럽트가 걸렸으면 true를 한 번 돌려주고 게이트 출력을 다시 연결
void ioHoldOff();              // 딥슬립 직전: 방전 게이트·팬 PWM 핀을 LOW로 고정
