# kocom.py

[Change log]

(12.9 수정) github 개설, serial 강제 종료시 error handling

(11.19 수정) 패킷발송 후 기기상태 수신시까지 다음패킷 발송않도록 처리, 충돌시 random jump, 패킷타이밍 튜닝기능(read_write_gap변수)

(11.18 추가수정) 연결 시작시에도 패킷충돌 감지, fan command오류수정

(11.18 수정) polling 도중 command 발생시 간헐적 충돌 해결

(11.17 수정) RS485연결 또는 mqtt연결이 끊어졌을 때 예외처리/자동복구, RS485 read/write 패킷충돌 방지

(11.15 수정) 하나의 파이썬코드 kocom.py로 serial 및 socket 둘 다 지원하도록 바꿨습니다. kocom.conf에서 serial로 할지 socket으로 할지 등등 설정하시면 됩니다. 

(11.14 수정) Rese님이 지적하신 mqtt log 오류 수정

(11.13오후 수정) Rese님 요청으로, socket용 draft version도 올립니다. (압축파일 내 kocom.py를 대체하세요) serial 연결부분을 socket 연결로 바꾸고, read()-->recv(1), write()-->send()로만 딱 변경했습니다. ser2net python파일로 1분간 작동유무만 테스트하여, 장기적인 안정성은 테스트되지 않았습니다. python 소스코드 내에 소켓 연결할 ip/port 를 기입하도록 되어있으니 수정하셔서 사용하시면 됩니다.

(11.13수정) checksum 을 계산하다보니 아무래도 header는 aa55까지인 것 같습니다. 다시 수정하였습니다. python 소스코드도 수정되었습니다
