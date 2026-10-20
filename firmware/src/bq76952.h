#pragma once
// TI BQ76952 드라이버. hal.h의 측정 함수(readCells/readCurrent/readTemps)와 setBalance를 구현한다.
#include "config.h"

bool bqInit();   // I2C 통신 확인 후 온도 핀·전류 이득·단위를 설정한다. 실패하면 측정 함수가 주기적으로 다시 시도한다
