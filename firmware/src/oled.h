#pragma once
// SSD1306 128x64 OLED. 화면 배치는 web/index.html의 oledFrame()/drawOled()와 같아야 한다.
void oledInit();
void oledUpdate();
void oledNextView();   // NEXT 버튼: 화면 전환
void oledOff();        // 딥슬립 전: 디스플레이 끄기
