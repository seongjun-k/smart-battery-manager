#pragma once
// TI BQ76907 드라이버. hal.h의 측정 함수(readCells/readCurrent/readTemp)와 setBalance를 구현한다.
#include "config.h"

bool bqInit();   // I2C 통신 확인 후 보호·온도·FET 구동 설정을 쓰고 읽어서 확인한다. 실패하면 측정 함수가 주기적으로 다시 시도한다
bool bqDeepSleep();   // BQ를 DEEPSLEEP으로 보낸다 (FET 드라이버·보호·측정 모두 정지). 깨우기는 bqInit()이 한다
