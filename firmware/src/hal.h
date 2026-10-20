#pragma once
// 상태 머신·제어 코드가 하드웨어를 보는 유일한 창구.
// 측정원(BQ76952, 이후 다른 AFE)과 출력 방식은 구현 파일(bq76952.cpp, io.cpp)이 숨긴다.
#include "config.h"

enum class Sound : uint8_t { KEY, START, DONE, STOP, WARN, ERROR };

// ---- 측정 (bq76952.cpp, io.cpp) ----
void readCells(float v[MAX_CELLS]);              // [V], 못 읽은 칸은 0
float readCurrent();                             // [A], 방전이 +
void readTemps(float &batt, float &sink);        // [°C], 읽기 실패 시 과열 값으로 반환(안전 쪽)
float readFanRpm();

// ---- 출력 (io.cpp, bq76952.cpp) ----
void setLoadDuty(float duty);                    // 0~1
void setFanDuty(float duty);                     // 0~1
void setBalance(const bool bal[MAX_CELLS], int n);
void buzzerPlay(Sound s);
