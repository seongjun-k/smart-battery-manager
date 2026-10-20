#include "bq76907.h"

#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <string.h>

#include "hal.h"

// 출처 표기: TRM = TI BQ76907 Technical Reference Manual SLUUCJ0 (2023-11), DS = 데이터시트 SLUSE96A (2023-11, 2026-07 개정)
// I2C CRC 모드는 쓰지 않는다 (I2C Config[CRC] 기본 0, TRM 12.2.1.4)

namespace {

// 7비트 0x08 = 8비트 0x10(쓰기)/0x11(읽기). I2C Address 기본값 (TRM 9.1, 12.2.1.3, DS 7.4.10)
constexpr uint8_t BQ_ADDR = 0x08;

// ---- Direct Command (TRM 11.1). 16비트 값은 리틀 엔디안 ----
constexpr uint8_t CMD_BATTERY_STATUS = 0x12;   // TRM 11.2.5
constexpr uint8_t CMD_CELL1_VOLTAGE = 0x14;    // 셀 n = 0x14 + 2*(n-1), n = 1~7, mV, 부호 있는 16비트 (TRM 표 5-1)
constexpr uint8_t CMD_TS_MEASUREMENT = 0x2A;   // TS 핀 ADC 코드, 부호 있는 16비트 (TRM 11.1, 7.4). 온도(°C)가 아니라 코드다
constexpr uint8_t CMD_CURRENT = 0x3A;          // CC2 전류, userA(공장 trim 기본값 = 1mΩ 기준 mA), 부호 있는 16비트 (TRM 5.2)
constexpr uint8_t CMD_FET_CONTROL = 0x68;      // 비트3 CHG_OFF, 비트2 DSG_OFF. HOST_FETOFF_EN=1일 때만 동작 (TRM 11.2.9)

// Battery Status 비트 (TRM 표 11-5)
constexpr uint16_t ST_DEEPSLEEP = 1u << 14;
constexpr uint16_t ST_SEC_MASK = 3u << 10;     // 1 = FULLACCESS, 3 = SEALED, 0 = 초기화 전
constexpr uint16_t ST_SEC_FULL = 1u << 10;
constexpr uint16_t ST_SEC_SEALED = 3u << 10;
constexpr uint16_t ST_POR = 1u << 7;           // 전원 리셋. CONFIG_UPDATE를 빠져나오면 지워진다
constexpr uint16_t ST_CFGUPDATE = 1u << 5;     // BQ76952와 달리 비트5다

// ---- Subcommand 전송 레지스터 (TRM 3.1) ----
constexpr uint8_t REG_SUBCMD = 0x3E;           // 0x3E 하위, 0x3F 상위 바이트
constexpr uint8_t REG_BUFFER = 0x40;           // 데이터 버퍼 0x40~0x5F
constexpr uint8_t REG_CHECKSUM = 0x60;         // 0x3E,0x3F,데이터의 합을 비트 반전
constexpr uint8_t REG_LENGTH = 0x61;           // 데이터 길이 + 4

// ---- Subcommand (TRM 11.3, 11.4) ----
constexpr uint16_t SUB_EXIT_DEEPSLEEP = 0x000E;
constexpr uint16_t SUB_DEEPSLEEP = 0x000F;         // 4초 안에 연속 두 번 보내야 적용 (TRM 8.4, 11.3)
constexpr uint16_t SUB_SET_CFGUPDATE = 0x0090;     // TRM 8.6
constexpr uint16_t SUB_EXIT_CFGUPDATE = 0x0092;
constexpr uint16_t SUB_CB_ACTIVE_CELLS = 0x0083;   // 1바이트 마스크. 비트 n = 셀 n(VCn-VC(n-1)), 비트0 예약, 0이면 해제 (TRM 11.5.5)

// ---- Data Memory 주소 (TRM 12.6 표, 필드 정의는 12.2~12.3). CONFIG_UPDATE 중에 서브커맨드 프로토콜로 쓴다 ----
constexpr uint16_t DM_POWER_CONFIG = 0x9014;       // H1
constexpr uint16_t DM_DA_CONFIG = 0x9019;          // H2
constexpr uint16_t DM_VCELL_MODE = 0x901B;         // H1
constexpr uint16_t DM_FET_OPTIONS = 0x901E;        // H1
constexpr uint16_t DM_BAL_MIN_TEMP = 0x9021;       // U1, 256코드 단위
constexpr uint16_t DM_BAL_MAX_TEMP = 0x9022;       // U1, 256코드 단위
constexpr uint16_t DM_ENABLED_PROT_A = 0x9024;     // H1
constexpr uint16_t DM_ENABLED_PROT_B = 0x9025;     // H1
constexpr uint16_t DM_DSG_PROT_A = 0x9026;         // H1
constexpr uint16_t DM_HWD_TIMEOUT = 0x902D;        // U1
constexpr uint16_t DM_CUV_THRESHOLD = 0x902E;      // I2, mV
constexpr uint16_t DM_CUV_DELAY = 0x9030;          // U1, ADSCAN 횟수
constexpr uint16_t DM_CUV_RECOVERY = 0x9031;       // H1
constexpr uint16_t DM_SCD_THRESHOLD = 0x903C;      // H1, 표 12-18 코드
constexpr uint16_t DM_SCD_DELAY = 0x903D;          // H1, 표 12-19 코드
constexpr uint16_t DM_OTD_THRESHOLD = 0x9046;      // U1, 54코드 단위
constexpr uint16_t DM_OTD_DELAY = 0x9047;          // U1, 측정 횟수
constexpr uint16_t DM_OTD_RECOVERY = 0x9048;       // U1, 54코드 단위

// 서미스터: DS 6.x 권장 조건의 RTS = 10kΩ(103-AT, 25°C). 내부 풀업 20kΩ은 1.8V(REG18)로 바이어스되고 ADC도 같은 기준이라
// 비율 측정이다. 풀스케일 코드는 입력 = REG18 x 5/3일 때 32768이므로 REG18(1.8V)에서 32768 x 3/5 (TRM 7.4, DS 7.5.4)
constexpr float TS_PULLUP_OHM = 20000.0f;
constexpr float TS_FULL_CODE = 19660.8f;
constexpr float NTC_R25 = 10000.0f;
// [실물 검증 필요] 문서 확인 실패: TI 문서에는 서미스터 B값이 없다 (DS 표 8-1 예시는 OTD 코드 2592가 약 60°C, 2970이 약 55°C라고만 한다).
// Semitec 103AT-2의 B값으로 알려진 3435K를 가정했다. 이 값으로 위 예시 코드는 59.4°C, 54.4°C로 계산된다 (약 0.6°C 낮음).
constexpr float NTC_BETA = 3435.0f;
constexpr int TS_CODE_SHORT = 100;             // 이 이하(NTC 단락)·아래 이상(NTC 단선)이면 읽기 실패로 본다
constexpr int TS_CODE_OPEN = 19000;

constexpr float TEMP_READ_FAIL = 125.0f;       // 읽기 실패 시 과열 값으로 두어 보호가 걸리게 한다
constexpr uint32_t REINIT_MS = 2000;
constexpr uint32_t BAL_REFRESH_MS = 5000;      // 호스트 밸런싱은 약 20초 뒤 자동 종료되므로 더 짧게 다시 보낸다 (TRM 10.1)
constexpr int BQ_CHANNELS = 7;
constexpr int COUNT_STABLE_READS = 2;          // 셀 수가 이 횟수만큼 더 같은 값으로 읽혀야 받아들인다 (커넥터 삽입 중 오판 방지)

bool ready = false;
uint32_t lastInitTry = 0;
uint8_t cfgVcell = 7;                          // BQ에 쓴 Vcell Mode. 7 = 모든 입력이 실제 셀(미확정 포함)
uint8_t chOf[MAX_CELLS] = {};                  // 배터리 셀 k+1이 읽힌 BQ 채널(1~7). 밸런싱 비트에 쓴다

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

// 서브커맨드 쓰기. 데이터가 있으면 버퍼, 체크섬, 길이를 이어서 쓴다 (TRM 3.1)
bool writeSub(uint16_t sub, const uint8_t *data = nullptr, uint8_t n = 0) {
  uint8_t head[2 + 32];
  head[0] = sub & 0xFF;
  head[1] = sub >> 8;
  if (n) memcpy(head + 2, data, n);
  if (!writeReg(REG_SUBCMD, head, 2 + n)) return false;
  if (!n) return true;
  uint8_t sum = 0;
  for (int i = 0; i < 2 + n; i++) sum += head[i];
  const uint8_t tail[2] = {(uint8_t)~sum, (uint8_t)(n + 4)};   // 길이는 체크섬 뒤에 쓰면 된다. 길이를 쓰는 순간 검증과 반영이 일어난다
  return writeReg(REG_CHECKSUM, tail, 2);
}

// Data Memory 읽기: 주소를 0x3E에 쓰면 값이 0x40 버퍼에 채워진다. 에코로 주소를 확인한다 (TRM 3.1 읽기 절차)
bool readDm(uint16_t addr, uint8_t *d, uint8_t n) {
  const uint8_t a[2] = {(uint8_t)(addr & 0xFF), (uint8_t)(addr >> 8)};
  uint8_t echo[2];
  if (!writeReg(REG_SUBCMD, a, 2) || !readReg(REG_SUBCMD, echo, 2) || memcmp(a, echo, 2)) return false;
  return readReg(REG_BUFFER, d, n);
}

struct Dm {
  uint16_t addr;
  uint8_t n;       // 1 또는 2바이트
  uint16_t val;    // 리틀 엔디안으로 쓴다
};

// 쓴 뒤 읽어서 비교한다. 보호 설정이 실제로 들어갔는지 모르는 채로 방전하지 않기 위해서다
bool writeVerifyDm(const Dm &e) {
  const uint8_t d[2] = {(uint8_t)(e.val & 0xFF), (uint8_t)(e.val >> 8)};
  uint8_t back[2] = {};
  if (writeSub(e.addr, d, e.n) && readDm(e.addr, back, e.n) && !memcmp(d, back, e.n)) return true;
  Serial.printf("BQ76907 설정 쓰기/확인 실패: 0x%04X\n", e.addr);
  return false;
}

bool waitStatus(uint16_t mask, bool want) {
  for (int i = 0; i < 40; i++) {
    int16_t st;
    if (readI16(CMD_BATTERY_STATUS, st) && (bool)((uint16_t)st & mask) == want) return true;
    delay(5);
  }
  return false;
}

bool readStatusCells(uint16_t &st, int16_t mv[BQ_CHANNELS]) {
  uint8_t b[2 + 2 * BQ_CHANNELS];   // 0x12~0x13 상태 + 0x14~0x21 셀 1~7을 한 번에 읽는다 (블록 읽기는 주소가 자동 증가, TRM 9.1)
  if (!readReg(CMD_BATTERY_STATUS, b, sizeof b)) return false;
  st = b[0] | (b[1] << 8);
  for (int c = 0; c < BQ_CHANNELS; c++) mv[c] = (int16_t)(b[2 + 2 * c] | (b[3 + 2 * c] << 8));
  return true;
}

int countCells(const int16_t mv[BQ_CHANNELS], uint8_t *ch = nullptr) {
  int n = 0;
  for (int c = 0; c < BQ_CHANNELS; c++)
    if (mv[c] > CELL_PRESENT_V * 1000.0f) {
      if (ch) ch[n] = c + 1;
      n++;
    }
  return n;
}

// 보호·FET·온도 설정을 한 번에 쓴다. CONFIG_UPDATE 중에는 보호와 측정이 멈추므로 DSG를 먼저 끈다 (TRM 8.6)
bool configure(int nCells) {
  // Vcell Mode: 2~6은 셀 수 그대로, 그 밖은 7(모든 입력이 실제 셀). 실제 셀 입력 위치는 표 5-8 / DS 표 7-1 고정 패턴이다
  // [실물 검증 필요] TRM 12.2.1.6은 최댓값 0x07, 12.6 요약표는 0x05라 서로 다르다. 6S는 값 6이 필요하다
  const uint8_t vcell = (nCells >= 2 && nCells <= 6) ? nCells : 7;
  const Dm tbl[] = {
      // Power Config: SLEEP_EN=0, CB_LOOP_SLOW=3. SLEEP에서는 셀 전압이 5초마다만 갱신돼 100ms 제어와 맞지 않는다 (TRM 8.3, 12.4.1.2).
      // 밸런싱 중 전압 측정을 16번 중 1번으로 줄여 밸런싱 시간을 약 92%로 늘린다 (TRM 10.1, 표 12-1)
      {DM_POWER_CONFIG, 1, 0x30},
      {DM_DA_CONFIG, 2, 0x0000},          // TSMODE=0 서미스터, CC 상시 동작, 변환 2.93ms (TRM 12.2.1.5)
      {DM_VCELL_MODE, 1, vcell},
      // FET Options: HOST_FETOFF_EN(6)=1 설정 중 DSG를 끄기 위해, FET_EN(2)=1 보호가 없으면 DSG를 자율로 켠다,
      // SFET(3)=0 CHG를 쓰지 않으므로 바디 다이오드 보호를 끈다 (TRM 12.2.1.8)
      {DM_FET_OPTIONS, 1, 0x44},
      // 밸런싱 온도 차단은 쓰지 않는다. NTC가 배터리가 아니라 방열판에 있어 TS로 밸런싱을 막으면 안 된다 (TRM 12.2.2.2~3)
      {DM_BAL_MIN_TEMP, 1, 255},          // TS 코드가 이 값 x256보다 크면(차가우면) 차단. 255 x 256은 코드 최대 약 19661보다 커서 걸리지 않는다
      {DM_BAL_MAX_TEMP, 1, 0},            // TS 코드가 이 값 x256보다 작으면(뜨거우면) 차단. 0이면 걸리지 않는다
      // 보호는 CUV, SCD, OTD, HWD를 켠다 (TRM 12.2.3.1~2, 표 12-10~11). SCD 기본 임계 10mV(5mΩ에서 2A)는
      // 펄스 5A 방전에 걸리므로 아래에서 40mV(8A)로 올린다. COV는 CHG만 끄고 REGOUT 검사는 LDO를 안 쓰므로 끈다
      {DM_ENABLED_PROT_A, 1, 0x60},       // CUV(비트6), SCD(비트5)
      {DM_SCD_THRESHOLD, 1, 2},           // 40mV = 5mΩ에서 8A. 펄스 최대 5A보다 여유 (TRM 표 6-9, 12-18)
      {DM_SCD_DELAY, 1, 3},               // 45~60µs. PWM 스위칭 순간의 짧은 스파이크로 오동작하지 않게 (TRM 표 6-10)
      {DM_ENABLED_PROT_B, 1, 0x21},       // OTD(비트5), HWD(비트0)
      {DM_DSG_PROT_A, 1, 0xFF},           // 켜진 보호가 걸리면 DSG를 끈다. CUV(7), HWD(3), OTD(2) 포함 (TRM 12.2.3.3)
      {DM_HWD_TIMEOUT, 1, 4},             // 0~15는 1~16초이므로 4 = 5초. 통신이 끊기면 DSG를 끈다 (TRM 6.15, 12.2.3.9)
      {DM_CUV_THRESHOLD, 2, 3500},        // 3.5V (TRM 12.3.1.1)
      {DM_CUV_DELAY, 1, 10},              // ADSCAN 10회. 7셀 NORMAL에서 약 0.23초 (TRM 12.3.1.2, 5.1.1)
      {DM_CUV_RECOVERY, 1, 2},            // 복구 히스테리시스 100mV (3.6V 이상이면 복구) (TRM 표 12-16)
      // OTD: TS 코드가 임계보다 작으면(뜨거우면) 걸린다. 54코드 단위. 18 x 54 = 972코드는 NTC_BETA 3380~3500에서
      // 96.2~99.4°C다. 17 x 54 = 918코드는 98.6~101.8°C라 100°C를 넘을 수 있어 한 칸 위를 골랐다 (TRM 6.11, 12.3.3.7)
      {DM_OTD_THRESHOLD, 1, 18},
      {DM_OTD_DELAY, 1, 15},              // 측정 15회 (TRM 12.3.3.8)
      {DM_OTD_RECOVERY, 1, 28},           // 1512코드, 78.7~81.0°C로 감속 시작 온도와 맞춘다. 식으면 DSG를 자율로 다시 켠다 (TRM 12.3.3.9)
  };

  const uint8_t fetOff = 0x0C;   // CHG_OFF | DSG_OFF
  const uint8_t fetAuto = 0x00;
  writeReg(CMD_FET_CONTROL, &fetOff, 1);
  bool ok = writeSub(SUB_SET_CFGUPDATE) && waitStatus(ST_CFGUPDATE, true);
  if (ok)
    for (const Dm &e : tbl) ok = writeVerifyDm(e) && ok;
  bool exited = writeSub(SUB_EXIT_CFGUPDATE) && waitStatus(ST_CFGUPDATE, false);   // 실패해도 반드시 빠져나가게 시도한다
  writeReg(CMD_FET_CONTROL, &fetAuto, 1);
  ok = ok && exited;
  if (ok) cfgVcell = vcell;
  return ok;
}

}  // namespace

bool bqInit() {
  lastInitTry = millis();
  ready = false;
  uint16_t st;
  int16_t mv[BQ_CHANNELS];
  if (!readStatusCells(st, mv)) return false;   // 통신 확인
  if ((st & ST_SEC_MASK) == ST_SEC_SEALED) {
    // 공장 기본 키 0x0414, 0x3672를 리틀 엔디안으로 연속해서 보낸다 (TRM 4, 12.5.1.2~3)
    // [실물 검증 필요] 키를 바꿔 출하한 부품이면 실패한다
    const uint8_t k1[2] = {0x14, 0x04}, k2[2] = {0x72, 0x36};
    if (!writeReg(REG_SUBCMD, k1, 2) || !writeReg(REG_SUBCMD, k2, 2) || !readStatusCells(st, mv)) return false;
  }
  if ((st & ST_SEC_MASK) != ST_SEC_FULL) return false;   // 초기화 전이거나 SEALED면 설정을 쓸 수 없다
  if (st & ST_DEEPSLEEP) {
    // 딥슬립에서 깨어난 ESP32가 처음부터 시작한 경우. 통신만으로는 깨어나지 않는다 (TRM 8.4)
    if (!writeSub(SUB_EXIT_DEEPSLEEP) || !waitStatus(ST_DEEPSLEEP, false) || !readStatusCells(st, mv)) return false;
  }
  const int n = countCells(mv);   // 지금 보이는 셀 수로 Vcell Mode를 먼저 맞춘다. 확정이 안 되면 7로 둔다
  ready = configure(n);
  return ready;
}

bool bqDeepSleep() {
  // 두 번째 명령은 첫 번째로부터 4초 안에 보낸다. 밸런싱은 DEEPSLEEP 진입 때 종료된다 (TRM 8.4, 10.1)
  bool ok = writeSub(SUB_DEEPSLEEP) && writeSub(SUB_DEEPSLEEP);
  delay(20);
  int16_t st;
  return ok && readI16(CMD_BATTERY_STATUS, st) && ((uint16_t)st & ST_DEEPSLEEP);
}

static bool ensureReady() {
  if (!ready && millis() - lastInitTry >= REINIT_MS) bqInit();
  return ready;
}

// 7개 채널을 모두 읽어 2.5V를 넘는 채널을 아래부터 순서대로 배터리 셀 1~n으로 쓴다.
// 6S 헤더는 채널 6이 PCB에서 단락돼 0V라 건너뛰고, 2S는 채널 1과 7이 실제 셀이다
void readCells(float v[MAX_CELLS]) {
  for (int i = 0; i < MAX_CELLS; i++) v[i] = 0;
  if (!ensureReady()) return;
  uint16_t st = 0;
  int16_t mv[BQ_CHANNELS];
  bool ok = false;
  for (int attempt = 0; attempt < 2 && !ok; attempt++) ok = readStatusCells(st, mv);   // 한 번의 I2C 오류로 연결 불량 정지가 걸리지 않게 한 번 더 시도
  if (!ok || (st & ST_POR)) {   // 연속 실패 또는 BQ 리셋으로 설정이 사라짐: 전부 0으로 돌려주고 재초기화를 시도한다
    ready = false;
    return;
  }
  uint8_t ch[BQ_CHANNELS];
  const int n = countCells(mv, ch);
  static int lastN = -1, same = 0;
  same = n == lastN ? (same < 100 ? same + 1 : same) : 0;
  lastN = n;
  // 지원 범위(2~6S)가 아니거나 셀 수가 아직 흔들리면 0으로 돌려 연결 불량으로 처리한다 (7S, 1S, 삽입 중)
  if (n < 2 || n > MAX_CELLS || same < COUNT_STABLE_READS) return;
  if (n != cfgVcell) {   // 셀 수가 바뀌었다. 쓰지 않는 입력의 0V가 저전압 보호에 걸리지 않게 Vcell Mode를 갱신
    if (!configure(n)) ready = false;
    return;
  }
  for (int k = 0; k < n; k++) {
    chOf[k] = ch[k];
    v[k] = mv[ch[k] - 1] / 1000.0f;
  }
}

float readCurrent() {
  int16_t raw;
  if (!ready || !readI16(CMD_CURRENT, raw)) return 0;
  // 충전 전류가 +다 (SRP가 배터리 − 쪽, SRN이 팩 − 쪽, TRM 5.2). 방전을 +로 쓰려고 부호를 뒤집는다.
  // 공장 trim 기본값은 1mΩ 기준 mA라서 실제 션트 값으로 나눈다. 16비트 범위 때문에 5mΩ에서 약 ±6.5A까지 읽힌다
  return -raw / 1000.0f / SHUNT_MOHM;
}

float readTemp() {
  int16_t code;
  if (!ready) return 25.0f;   // 측정기가 없으면 셀도 0이라 방전이 시작되지 않는다
  if (!readI16(CMD_TS_MEASUREMENT, code) || code <= TS_CODE_SHORT || code >= TS_CODE_OPEN) return TEMP_READ_FAIL;
  const float r = TS_PULLUP_OHM * code / (TS_FULL_CODE - code);   // 풀업과 NTC의 분압
  return 1.0f / (1.0f / 298.15f + logf(r / NTC_R25) / NTC_BETA) - 273.15f;
}

void setBalance(const bool bal[MAX_CELLS], int n) {
  static uint8_t lastMask = 0;
  static uint32_t lastSend = 0;
  uint8_t mask = 0;
  for (int i = 0; i < n; i++)
    if (bal[i] && chOf[i]) mask |= 1u << chOf[i];   // 배터리 셀 -> BQ 채널 번호. 인접 셀 동시 밸런싱도 문서상 허용 (TRM 10.1, DS 7.7)
  if (!ready) return;
  uint32_t now = millis();
  if (mask == lastMask && (mask == 0 || now - lastSend < BAL_REFRESH_MS)) return;
  if (writeSub(SUB_CB_ACTIVE_CELLS, &mask, 1)) {   // 실패하면 lastMask를 안 바꿔 다음 주기에 다시 보낸다
    lastMask = mask;
    lastSend = now;
  }
}
