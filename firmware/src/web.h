#pragma once
// Wi-Fi AP, LittleFS 정적 파일(/), WebSocket(/ws). JSON 형식은 docs/결과보고서_초안.md 6장.
void webInit();
void wsPoll();                               // loop()에서 호출: 쌓인 명령을 처리하고 오류를 돌려보낸다
void wsBroadcast();                          // 상태 메시지 전송 (약 5Hz)
const char *wsOnCommand(const char *text);   // 오류면 메시지, 정상이면 nullptr
