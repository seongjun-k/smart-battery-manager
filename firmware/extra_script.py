import os

Import("env")

# 프로젝트 폴더명이 한글이면 Windows 링커가 맵 파일을 열지 못해 링크가 실패한다.
# 맵 파일은 필요 없으니 버리는 장치로 보낸다 (옵션을 빼면 --cref가 표준출력으로 쏟아진다).
flags, nxt = [], False
for f in env["LINKFLAGS"]:
    flags.append(os.devnull if nxt else f)
    nxt = f == "-Wl,--Map"
env.Replace(LINKFLAGS=flags)
