#include "web.h"

#include <ArduinoJson.h>
#include <ESPAsyncWebServer.h>
#include <LittleFS.h>
#include <WiFi.h>
#include <math.h>

#include "config.h"
#include "control.h"

static AsyncWebServer server(80);
static AsyncWebSocket ws("/ws");

// WebSocket 콜백은 async_tcp 태스크에서 돈다. 상태 머신은 loop() 태스크만 만지게 하려고
// 명령 원문만 큐에 넣고 wsPoll()이 loop()에서 처리한다 (락 없이 g를 보호).
struct CmdMsg {
  uint32_t id;
  char text[192];
};
static QueueHandle_t cmdQ;

static void onWsEvent(AsyncWebSocket *, AsyncWebSocketClient *c, AwsEventType type, void *arg, uint8_t *data, size_t len) {
  if (type != WS_EVT_DATA) return;
  auto *info = (AwsFrameInfo *)arg;
  if (!info->final || info->index != 0 || info->len != len || info->opcode != WS_TEXT) return;   // 명령은 짧아 조각 프레임은 받지 않는다
  CmdMsg m;
  m.id = c->id();
  size_t n = len < sizeof(m.text) - 1 ? len : sizeof(m.text) - 1;
  memcpy(m.text, data, n);
  m.text[n] = 0;
  xQueueSend(cmdQ, &m, 0);
}

void webInit() {
  cmdQ = xQueueCreate(4, sizeof(CmdMsg));
  WiFi.mode(WIFI_AP);
  WiFi.softAP(WIFI_SSID, WIFI_PASS);
  if (!LittleFS.begin(false)) Serial.println("LittleFS 마운트 실패: pio run -t uploadfs 필요");
  ws.onEvent(onWsEvent);
  server.addHandler(&ws);
  server.serveStatic("/", LittleFS, "/").setDefaultFile("index.html");
  server.onNotFound([](AsyncWebServerRequest *r) { r->send(404, "text/plain", "not found"); });
  server.begin();
}

static double rd(double x, int d) {
  double k = pow(10.0, d);
  return round(x * k) / k;
}

void wsBroadcast() {
  if (!ws.count()) {   // 구독자가 없으면 이벤트도 버린다 (sim과 같다)
    g.nEvents = 0;
    return;
  }
  if (!ws.availableForWriteAll()) return;   // 느린 클라이언트 큐가 찼으면 이번 주기는 건너뛴다. 이벤트는 유지
  JsonDocument d;
  d["type"] = "status";
  d["t"] = rd(g.t, 1);
  d["state"] = stateName(g.state);
  d["selMode"] = modeName(g.selMode);
  d["mode"] = modeName(g.mode);
  d["cellCount"] = g.cellCount;
  JsonArray cells = d["cells"].to<JsonArray>();
  for (int i = 0; i < g.nCells; i++) cells.add(rd(g.cells[i], 3));
  d["packV"] = rd(g.packV, 2);
  d["current"] = rd(g.currentAvg, 2);
  d["duty"] = rd(g.duty, 3);
  d["tempBatt"] = rd(g.tempBatt, 1);
  d["tempSink"] = rd(g.tempSink, 1);
  d["fanRpm"] = (int)lroundf(g.fanRpm);
  d["limit"] = limitName(g.limit);
  // 용량 테스트에서는 종료 전압을 targetV로 보낸다 (웹 진행률 계산용)
  d["targetV"] = rd(g.mode == Mode::CAPACITY ? CAP_END_V : g.targetV, 2);
  if (g.soh >= 0) d["soh"] = g.soh;
  else d["soh"] = nullptr;
  JsonArray bal = d["bal"].to<JsonArray>();
  for (int i = 0; i < g.nCells; i++) bal.add(g.bal[i]);
  float p = progress();
  if (isnan(p)) d["progress"] = nullptr;
  else d["progress"] = rd(p, 3);
  if (g.state == State::RUN) d["elapsed"] = rd(g.t - g.runT0, 1);
  else d["elapsed"] = nullptr;
  if (g.irN > 0) {
    JsonArray ir = d["ir"].to<JsonArray>();
    for (int i = 0; i < g.irN; i++) ir.add(rd(g.ir[i], 1));
  } else {
    d["ir"] = nullptr;
  }
  if (g.capValid) d["capMeasuredAh"] = rd(g.capMeasured, 3);
  else d["capMeasuredAh"] = nullptr;
  JsonArray al = d["alarms"].to<JsonArray>();
  const uint8_t mask = g.alarms | g.trip;
  for (uint8_t b = 1; b && b <= AL_UNDERVOLT; b <<= 1)
    if (mask & b) al.add(alarmName(b));
  JsonArray ev = d["events"].to<JsonArray>();
  for (int i = 0; i < g.nEvents; i++) ev.add(eventName(g.events[i]));

  char buf[1024];
  size_t n = serializeJson(d, buf, sizeof buf);
  g.nEvents = 0;
  ws.textAll(buf, n);
}

// 웹 명령 검증과 처리. 검증 규칙은 sim.py Device.command와 같다. fault는 시뮬레이터 전용이라 받지 않는다.
const char *wsOnCommand(const char *text) {
  static char err[96];
  JsonDocument d;
  if (deserializeJson(d, text) || !d.is<JsonObject>() || strcmp(d["type"] | "", "cmd") != 0)
    return "type이 cmd인 JSON 객체가 아님";
  const char *cmd = d["cmd"] | "";

  if (!strcmp(cmd, "stop")) {
    onStop();
    return nullptr;
  }

  if (!strcmp(cmd, "start")) {
    const char *ms = d["mode"] | "";
    Mode m = Mode::NONE;
    for (Mode k : {Mode::STORAGE, Mode::BALANCE, Mode::CAPACITY, Mode::DIAG})
      if (!strcmp(ms, modeName(k))) m = k;
    if (m == Mode::NONE) {
      snprintf(err, sizeof err, "지원하지 않는 mode: %s", ms);
      return err;
    }
    State s = g.state;
    if (s != State::SELECT && s != State::DONE && s != State::HOLD && s != State::STOP) {
      snprintf(err, sizeof err, "%s 상태에서는 시작할 수 없음", stateName(s));
      return err;
    }
    float target = TARGET_PRESETS[0];
    if (!d["targetV"].isNull()) {
      bool ok = false;
      if (d["targetV"].is<float>())
        for (float p : TARGET_PRESETS)
          if (fabsf(d["targetV"].as<float>() - p) < 0.005f) {
            target = p;
            ok = true;
          }
      if (!ok) return "targetV는 3.80, 3.85, 3.90 중 하나여야 함";
    }
    float cap = CAPACITY_AH;
    if (!d["capacityAh"].isNull()) {
      if (!d["capacityAh"].is<float>()) return "capacityAh는 0~20 사이 숫자여야 함";
      cap = d["capacityAh"].as<float>();
      if (!(cap > 0 && cap <= 20)) return "capacityAh는 0~20 사이 숫자여야 함";
    }
    cmdStart(m, target, cap);
    return nullptr;
  }

  if (!strcmp(cmd, "set")) {
    const char *key = d["key"] | "";
    if (strcmp(key, "buzzerKeyTone") || !d["value"].is<bool>()) {
      snprintf(err, sizeof err, "설정할 수 없는 key/value: %s", key);
      return err;
    }
    g.keyTone = d["value"].as<bool>();
    return nullptr;
  }

  snprintf(err, sizeof err, "알 수 없는 cmd: %s", cmd);
  return err;
}

void wsPoll() {
  CmdMsg m;
  while (xQueueReceive(cmdQ, &m, 0) == pdTRUE) {
    const char *e = wsOnCommand(m.text);
    if (!e) continue;
    JsonDocument d;
    d["type"] = "error";
    d["msg"] = e;
    char buf[200];
    size_t n = serializeJson(d, buf, sizeof buf);
    ws.text(m.id, buf, n);
  }
  static uint32_t lastClean = 0;
  if (millis() - lastClean >= 1000) {   // 끊긴 클라이언트 정리
    lastClean = millis();
    ws.cleanupClients();
  }
}
