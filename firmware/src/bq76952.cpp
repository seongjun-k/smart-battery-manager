#include "bq76952.h"

#include <Wire.h>
#include <string.h>

#include "hal.h"

// 출처 표기: TRM = TI BQ76952 Technical Reference Manual SLUUBY2B (2022-05), DS = 데이터시트 SLUSE13B (2021-11)
// I2C CRC 모드는 쓰지 않는다 (Comm Type 기본값 = CRC 없는 I2C Fast, TRM 표 9-1)

namespace {

// 기본 I2C 주소: 8비트 0x10(쓰기)/0x11(읽기) -> 7비트 0x08 (TRM 9.2, DS 같은 절)
constexpr uint8_t BQ_ADDR = 0x08;

// ---- Direct Command (TRM 표 12-1). 16비트 값은 리틀 엔디안 ----
constexpr uint8_t CMD_BATTERY_STATUS = 0x12;   // 비트0 = CFGUPDATE (TRM 표 6-2)
constexpr uint8_t CMD_CELL1_VOLTAGE = 0x14;    // 셀 n = 0x14 + 2*(n-1), 단위 mV, 부호 있는 16비트
constexpr uint8_t CMD_CC2_CURRENT = 0x3A;      // 단위 userA = 1mA (DA Configuration=0x05), 부호 있는 16비트
constexpr uint8_t CMD_TS1_TEMP = 0x70;         // 단위 0.1K, 부호 있는 16비트. TS1 핀 서미스터
constexpr uint8_t CMD_TS2_TEMP = 0x72;         // TS2 핀 서미스터

// ---- Subcommand 전송 레지스터 (TRM 3.1) ----
constexpr uint8_t REG_SUBCMD = 0x3E;           // 0x3E 하위, 0x3F 상위 바이트
constexpr uint8_t REG_BUFFER = 0x40;           // 데이터 버퍼 0x40~0x5F
constexpr uint8_t REG_CHECKSUM = 0x60;         // 0x3E,0x3F,데이터의 합을 비트 반전
constexpr uint8_t REG_LENGTH = 0x61;           // 데이터 길이 + 4

// ---- Subcommand (TRM 표 10-1, 12장 서브커맨드 표) ----
constexpr uint16_t SUB_CB_ACTIVE_CELLS = 0x0083;   // 쓰기: 밸런싱할 셀 비트마스크(bit0=셀1), 0이면 해제. 반영까지 최대 약 1초
constexpr uint16_t SUB_SET_CFGUPDATE = 0x0090;     // CONFIG_UPDATE 진입 (TRM 7.6)
constexpr uint16_t SUB_EXIT_CFGUPDATE = 0x0092;    // CONFIG_UPDATE 종료

// ---- Data Memory 주소 (TRM 13.1 접근법, 13.3.2 Settings:Configuration, 13.2.2 Calibration:Current) ----
constexpr uint16_t DM_CC_GAIN = 0x91A8;            // float32, 7.4768 / Rsense[mΩ]
constexpr uint16_t DM_CAPACITY_GAIN = 0x91AC;      // float32, CC Gain x 298261.6178
constexpr uint16_t DM_TS1_CONFIG = 0x92FD;         // 1바이트, 기본 0x07
constexpr uint16_t DM_TS2_CONFIG = 0x92FE;         // 1바이트, 기본 0x00(미사용)이라 반드시 써야 한다
constexpr uint16_t DM_DA_CONFIG = 0x9303;          // 1바이트, 기본 0x05

// TSn Config: OPT[5:4]=00 18kΩ 풀업, OPT[3:2]=00 18K 온도 모델, OPT[1:0]=01/10 서미스터, PIN_FXN=3 (TRM 13.3.2.12~13)
constexpr uint8_t TS1_CONFIG = 0x07;   // 서미스터, 셀 온도 보호용(배터리 온도)
constexpr uint8_t TS2_CONFIG = 0x0B;   // 서미스터, 값만 보고(방열판 온도)
// DA Configuration: USER_VOLTS_CV=1(10mV, 쓰지 않음), USER_AMPS=01(1mA) (TRM 13.3.2.18, 표 4-3)
constexpr uint8_t DA_CONFIG = 0x05;

// 배터리 셀 k -> BQ 셀 입력 번호. 보고서 회로도가 확정되면 맞춘다.
// [실물 검증 필요] DS 핀 설명: 셀 1, 2, 16은 항상 실제 셀에 연결해야 하고 안 쓰는 입력은 인접 핀과 단락한다.
// 아래 1~6 순서는 가정이며 6S 미만의 처리(어느 입력을 단락할지)는 회로도에서 정해야 한다.
constexpr uint8_t BQ_CELL_CH[MAX_CELLS] = {1, 2, 3, 4, 5, 6};

constexpr float TEMP_READ_FAIL = 125.0f;      // 읽기 실패 시 과열 값으로 두어 보호가 걸리게 한다
constexpr uint32_t REINIT_MS = 2000;
constexpr uint32_t BAL_REFRESH_MS = 5000;     // 호스트 밸런싱은 Cell Balance Interval(기본 20s) 뒤 자동 종료되므로 더 짧게 다시 보낸다 (TRM 10.1)

bool ready = false;
uint32_t lastInitTry = 0;

bool writeReg(uint8_t reg, const uint8_t *d, size_t n) {
  Wire.beginTransmission(BQ_ADDR);
  Wire.write(reg);
  Wire.write(d, n);
  return Wire.endTransmission() == 0;
}

bool readReg(uint8_t reg, uint8_t *d, size_t n) {
  Wire.beginTransmission(BQ_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;   // 반복 시작 조건 (TRM 그림 9-2)
  if (Wire.requestFrom((uint16_t)BQ_ADDR, (size_t)n, true) != n) return false;
  for (size_t i = 0; i < n; i++) d[i] = Wire.read();
  return true;
}

bool readI16(uint8_t reg, int16_t &v) {
  uint8_t b[2];
  if (!readReg(reg, b, 2)) return false;
  v = (int16_t)(b[0] | (b[1] << 8));
  return true;
}

// 서브커맨드 쓰기. 데이터가 있으면 버퍼, 체크섬, 길이를 이어서 쓴다 (TRM 3.1, 13.1)
bool writeSub(uint16_t sub, const uint8_t *data = nullptr, uint8_t n = 0) {
  uint8_t head[2 + 32];
  head[0] = sub & 0xFF;
  head[1] = sub >> 8;
  if (n) memcpy(head + 2, data, n);
  if (!writeReg(REG_SUBCMD, head, 2 + n)) return false;
  if (!n) return true;
  uint8_t sum = 0;
  for (int i = 0; i < 2 + n; i++) sum += head[i];
  const uint8_t tail[2] = {(uint8_t)~sum, (uint8_t)(n + 4)};   // 체크섬과 길이는 한 번에 써야 유효
  return writeReg(REG_CHECKSUM, tail, 2);
}

bool writeDm(uint16_t addr, const void *data, uint8_t n) { return writeSub(addr, (const uint8_t *)data, n); }

bool waitCfgUpdate(bool want) {
  for (int i = 0; i < 40; i++) {
    int16_t st;
    if (readI16(CMD_BATTERY_STATUS, st) && (bool)(st & 1) == want) return true;
    delay(5);
  }
  return false;
}

}  // namespace

bool bqInit() {
  lastInitTry = millis();
  ready = false;
  int16_t st;
  if (!readI16(CMD_BATTERY_STATUS, st)) return false;   // 통신 확인
  if (!writeSub(SUB_SET_CFGUPDATE) || !waitCfgUpdate(true)) return false;
  // [실물 검증 필요] 아래 쓰기 결과는 읽어서 확인하지 않는다. 기본 상태(FULLACCESS, TRM 13.8.2)를 가정한다
  float ccGain = 7.4768f / SHUNT_MOHM;   // [실물 검증 필요] TRM 4.12는 7.5684, 13.2.2.1은 7.4768로 다르다. 후자를 썼다
  float capGain = ccGain * 298261.6178f;
  bool ok = writeDm(DM_CC_GAIN, &ccGain, 4) && writeDm(DM_CAPACITY_GAIN, &capGain, 4) &&
            writeDm(DM_TS1_CONFIG, &TS1_CONFIG, 1) && writeDm(DM_TS2_CONFIG, &TS2_CONFIG, 1) &&
            writeDm(DM_DA_CONFIG, &DA_CONFIG, 1);
  bool exited = writeSub(SUB_EXIT_CFGUPDATE) && waitCfgUpdate(false);
  ready = ok && exited;
  return ready;
}

static bool ensureReady() {
  if (!ready && millis() - lastInitTry >= REINIT_MS) bqInit();
  return ready;
}

void readCells(float v[MAX_CELLS]) {
  for (int i = 0; i < MAX_CELLS; i++) v[i] = 0;
  if (!ensureReady()) return;
  for (int attempt = 0; attempt < 2; attempt++) {   // 한 번의 I2C 오류로 연결 불량 정지가 걸리지 않게 한 번 더 시도
    float tmp[MAX_CELLS];
    bool ok = true;
    for (int i = 0; i < MAX_CELLS && ok; i++) {
      int16_t mv;
      ok = readI16(CMD_CELL1_VOLTAGE + 2 * (BQ_CELL_CH[i] - 1), mv);
      tmp[i] = mv / 1000.0f;
    }
    if (ok) {
      memcpy(v, tmp, sizeof(tmp));
      return;
    }
  }
  ready = false;   // 연속 실패: 전부 0으로 돌려주고 재초기화를 시도한다
}

float readCurrent() {
  int16_t raw;
  if (!ready || !readI16(CMD_CC2_CURRENT, raw)) return 0;
  // [실물 검증 필요] 충전 전류가 +라고 문서에 있다(TRM 4.3). 방전을 +로 쓰려고 부호를 뒤집었다.
  // 션트의 SRP/SRN 방향이 회로도와 맞는지 확인할 것. CC2 갱신은 NORMAL 모드에서 3ms 주기 (TRM 4.3)
  return -raw / 1000.0f;
}

void readTemps(float &batt, float &sink) {
  int16_t r1, r2;
  if (!ready) {   // 측정기가 없으면 셀도 0이라 방전이 시작되지 않는다
    batt = sink = 25.0f;
    return;
  }
  batt = readI16(CMD_TS1_TEMP, r1) ? r1 * 0.1f - 273.15f : TEMP_READ_FAIL;
  sink = readI16(CMD_TS2_TEMP, r2) ? r2 * 0.1f - 273.15f : TEMP_READ_FAIL;
}

void setBalance(const bool bal[MAX_CELLS], int n) {
  static uint16_t lastMask = 0;
  static uint32_t lastSend = 0;
  uint16_t mask = 0;
  for (int i = 0; i < n; i++)
    if (bal[i]) mask |= 1u << (BQ_CELL_CH[i] - 1);
  if (!ready) return;
  uint32_t now = millis();
  if (mask == lastMask && (mask == 0 || now - lastSend < BAL_REFRESH_MS)) return;
  const uint8_t d[2] = {(uint8_t)(mask & 0xFF), (uint8_t)(mask >> 8)};
  if (writeSub(SUB_CB_ACTIVE_CELLS, d, 2)) {   // 실패하면 lastMask를 안 바꿔 다음 주기에 다시 보낸다
    lastMask = mask;
    lastSend = now;
  }
}
