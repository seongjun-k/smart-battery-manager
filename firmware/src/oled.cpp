#include "oled.h"

#include <U8g2lib.h>
#include <math.h>
#include <stdio.h>

#include "control.h"

// Wire는 main에서 먼저 시작한다 (BQ76907과 같은 I2C 버스)
static U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);
static unsigned oledView = 0;

void oledInit() {
  u8g2.begin();
  u8g2.setFontPosTop();
}

void oledNextView() { oledView++; }

void oledOff() { u8g2.setPowerSave(1); }

namespace {

enum Kind : uint8_t { TEXT, TITLE, CELLS, BAR };
struct Line {
  Kind kind;
  char t[30];
  float bar;
};

// 웹은 상태 JSON의 반올림된 값으로 그린다. 같은 값이 나오도록 같은 자리수로 반올림한다
float rnd(float x, int d) {
  float k = powf(10.0f, d);
  return roundf(x * k) / k;
}
int jsRound(float x) { return (int)floorf(x + 0.5f); }   // JS Math.round

void clockStr(char *out, size_t n, float t) {
  int s = t > 0 ? (int)floorf(t) : 0;
  snprintf(out, n, "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60);
}

struct Frame {
  Line l[8];
  int n = 0;
  Line &add(Kind k) {
    Line &x = l[n++];
    x.kind = k;
    x.t[0] = 0;
    x.bar = 0;
    return x;
  }
};

// web/index.html oledFrame()과 같은 순서·문구
void oledFrame(Frame &f, float *c, int nc) {
  float lo = 0, hi = 0;
  if (nc) {
    lo = hi = c[0];
    for (int i = 1; i < nc; i++) {
      lo = fminf(lo, c[i]);
      hi = fmaxf(hi, c[i]);
    }
  }
  const bool run = g.state == State::RUN;
  const float packV = rnd(g.packV, 2), cur = rnd(g.currentAvg, 2);
  const float targetV = g.mode == Mode::CAPACITY ? CAP_END_V : g.targetV;
  const int views = run ? 3 : 2;
  const int v = oledView % views;

  if (v == 1 && g.cellCount) {
    snprintf(f.add(CELLS).t, sizeof(Line::t), "CELLS   d=%dmV", jsRound((hi - lo) * 1000));
    return;
  }
  if (run && v == 0) {
    const char *title = g.mode == Mode::STORAGE ? "DISCHARGING" : g.mode == Mode::BALANCE ? "BALANCING" : "CAP TEST";
    snprintf(f.add(TITLE).t, sizeof(Line::t), "%s", title);
    snprintf(f.add(TEXT).t, sizeof(Line::t), "I %.2fA P %.1fW", cur, packV * cur);
    if (g.mode == Mode::BALANCE) snprintf(f.add(TEXT).t, sizeof(Line::t), "d %dmV  to 10mV", jsRound((hi - lo) * 1000));
    else snprintf(f.add(TEXT).t, sizeof(Line::t), "Vmin %.2f tgt %.2f", lo, targetV);
    char ck[16];
    clockStr(ck, sizeof ck, rnd((float)(g.t - g.runT0), 1));
    snprintf(f.add(TEXT).t, sizeof(Line::t), "Time %s", ck);
    float p = progress();
    f.add(BAR).bar = isnan(p) ? 0 : p;
    return;
  }
  if (run) {   // v == 2
    snprintf(f.add(TITLE).t, sizeof(Line::t), "%s MODE", modeName(g.mode));
    snprintf(f.add(TEXT).t, sizeof(Line::t), "%dS  %.2fV", g.cellCount, packV);
    snprintf(f.add(TEXT).t, sizeof(Line::t), "RUN %dW %.2fA", jsRound(packV * cur), cur);
    snprintf(f.add(TEXT).t, sizeof(Line::t), "Load %dC Fan %d", jsRound(rnd(g.tempSink, 1)), (int)lroundf(g.fanRpm));
    snprintf(f.add(TEXT).t, sizeof(Line::t), "NEXT:view STOP:end");
    return;
  }
  if (g.state == State::SELECT) {   // web oledFrame()의 SELECT 화면과 같게
    const uint8_t al = g.alarms | g.trip;
    snprintf(f.add(TITLE).t, sizeof(Line::t), "SELECT MODE");
    snprintf(f.add(TEXT).t, sizeof(Line::t), "> %s", modeName(g.selMode));
    snprintf(f.add(TEXT).t, sizeof(Line::t), "%dS  %.2fV", g.cellCount, packV);
    if (al) snprintf(f.add(TEXT).t, sizeof(Line::t), "%s", alarmName(al & -al));
    else if (g.soh >= 0) snprintf(f.add(TEXT).t, sizeof(Line::t), "SOH %d", g.soh);
    else snprintf(f.add(TEXT).t, sizeof(Line::t), "SOH -");
    snprintf(f.add(TEXT).t, sizeof(Line::t), "NEXT:mode OK:start");
    return;
  }
  static const char *const HEAD[] = {"CONNECT BATT", "DIAGNOSING", "SELECT MODE", nullptr, "DONE", "HOLD", "STOPPED"};
  // State 순서: IDLE, DIAG, SELECT, RUN, DONE, HOLD, STOP
  snprintf(f.add(TITLE).t, sizeof(Line::t), "%s", HEAD[(int)g.state]);
  const uint8_t al = g.alarms | g.trip;
  if (al) snprintf(f.add(TEXT).t, sizeof(Line::t), "%s", alarmName(al & -al));   // 상태 JSON의 alarms[0]
  if (g.cellCount) snprintf(f.add(TEXT).t, sizeof(Line::t), "%dS  %.2fV", g.cellCount, packV);
  if (g.soh >= 0) {
    float mx = 0;   // 웹: ir이 null이면 [0]의 최댓값
    for (int i = 0; i < g.irN; i++) mx = i ? fmaxf(mx, rnd(g.ir[i], 1)) : rnd(g.ir[i], 1);
    snprintf(f.add(TEXT).t, sizeof(Line::t), "SOH %d  IR %.1fm", g.soh, mx);
  }
  if (g.capValid) snprintf(f.add(TEXT).t, sizeof(Line::t), "CAP %dmAh", jsRound(rnd(g.capMeasured, 3) * 1000));
  snprintf(f.add(TEXT).t, sizeof(Line::t), "%s", g.state == State::SELECT ? "NEXT:mode OK:start" : "NEXT:view");
}

}  // namespace

// web/index.html drawOled()와 같은 좌표
void oledUpdate() {
  float c[MAX_CELLS];
  for (int i = 0; i < g.nCells; i++) c[i] = rnd(g.cells[i], 3);
  Frame f;
  oledFrame(f, c, g.nCells);

  u8g2.clearBuffer();
  int y = 0;
  for (int i = 0; i < f.n; i++) {
    const Line &L = f.l[i];
    if (L.kind == CELLS) {
      u8g2.setFont(u8g2_font_5x8_tf);
      u8g2.drawStr(1, 0, L.t);
      float lo = c[0], hi = c[0];
      for (int k = 1; k < g.nCells; k++) {
        lo = fminf(lo, c[k]);
        hi = fmaxf(hi, c[k]);
      }
      const int rows = g.nCells, h = 52 / rows;
      for (int k = 0; k < rows; k++) {
        const int yy = 11 + k * h;
        char buf[8];
        snprintf(buf, sizeof buf, "C%d", k + 1);
        u8g2.drawStr(1, yy, buf);
        const int w = 14 + jsRound(50 * (hi > lo ? (c[k] - lo) / (hi - lo) : 1.0f));
        u8g2.drawBox(16, yy + 1, w, h - 3);
        snprintf(buf, sizeof buf, "%.2f", c[k]);
        u8g2.drawStr(96, yy, buf);
      }
      break;
    }
    if (L.kind == BAR) {
      u8g2.drawFrame(1, y + 1, 126, 9);
      u8g2.drawBox(3, y + 3, jsRound(122 * L.bar), 5);
      y += 11;
      continue;
    }
    const bool title = L.kind == TITLE;
    u8g2.setFont(title ? u8g2_font_6x12_tf : u8g2_font_5x8_tf);
    u8g2.drawStr(1, y, L.t);
    y += title ? 13 : 10;
    if (title) {
      u8g2.drawHLine(0, y - 1, 128);
      y += 2;
    }
  }
  u8g2.sendBuffer();
}
