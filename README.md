# ExcelNamuViewer (ExcelView)

엑셀 처럼 위장된 나무위키 뷰어. PySide6 + QtWebEngine 으로 구현.

- namu.wiki 페이지의 전체 시각 구조를 좌표 기반으로 엑셀 셀 그리드에 매핑
- 이미지는 셀에 `📷 [사진 보기]` placeholder 로 표시 → 더블 클릭하면 별도 다이얼로그로 사진 표시
- 인라인 링크 더블 클릭 시 해당 문서로 이동
- 각주 `[1]`, `[2]` 셀 단일 클릭 시 toolTip 으로 본문 표시
- 광고 컨테이너 자동 차단
- 좌우 스크롤 차단 + 윈도우 폭 따라 자동 줄바꿈
- 리본 좌상단 `◀` 또는 `Alt+←` / `Backspace` 로 뒤로 가기

## 빠른 실행 (Windows)

Python 3.10+ 가 설치된 상태에서:

```cmd
run.bat
```

처음 실행 시 자동으로 `.venv` 생성 + PySide6 설치 (약 250MB, 1회).
이후엔 즉시 실행됨.

## 수동 실행

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## 단일 .exe 로 빌드

```cmd
.venv\Scripts\pip install -r requirements-build.txt
.venv\Scripts\pyinstaller --noconfirm ExcelView.spec
```

→ `dist\ExcelView.exe` (약 245MB, self-contained).
다른 PC 에서도 그 .exe 하나만 더블클릭하면 동작 (Windows 10/11 x64).

## 사용법

1. 실행 후 우상단 검색박스에 나무위키 문서 제목 입력 + Enter
   - 예: `악어`, `리누스 토르발스`, `Qt`
   - 일반 URL (`https://...`) / 로컬 파일 경로도 그대로 입력 가능
2. 약 5초 대기 후 페이지가 셀에 채워짐
3. 셀 동작
   - 파란 밑줄 셀 = 링크 → **더블클릭**해서 이동
   - 회색 밑줄 `[N]` = 각주 → **단일클릭**해서 toolTip
   - 📷 셀 = 이미지 → **더블클릭**해서 사진 팝업

## 단축키

| 단축키 | 기능 |
|---|---|
| `Enter` (검색박스) | 페이지 로드 |
| `Alt+←` / `Backspace` | 뒤로 가기 |
| `Ctrl+D` | namu.wiki 원본 페이지를 별창에 표시 (디버그) |

## 디렉토리 구조

```
ExcelView/
├── main.py                 # 엔트리
├── excelview/
│   ├── mainwindow.py       # 메인 윈도우 조립
│   ├── ribbonbar.py        # 엑셀 풍 리본 + 검색박스 + 뒤로 버튼
│   ├── formulabar.py       # 이름박스 + fx + 수식 입력줄
│   ├── sheetview.py        # 셀 그리드 (좌표 매핑, 링크/각주/이미지 처리)
│   ├── sheettabbar.py      # Sheet1/2/3 탭
│   ├── statusbar.py        # 그린 상태바 + 줌
│   ├── namuloader.py       # QtWebEngine 으로 namu.wiki 로드 + 토큰 추출
│   ├── namuformatter.py    # positioned tokens → 셀 매트릭스
│   └── imagedialog.py      # 이미지 미리보기 다이얼로그
├── resources/excel.qss     # 엑셀 룩 스타일시트
├── ExcelView.spec          # PyInstaller 빌드 spec
├── requirements.txt        # 실행 의존성
├── requirements-build.txt  # 빌드 의존성 (pyinstaller 포함)
└── run.bat                 # 원클릭 실행
```

## 라이선스 / 주의

- 본 프로그램은 학습/실험 목적의 뷰어이며 namu.wiki 콘텐츠 자체에는 namu.wiki 의 라이선스(CC BY-NC-SA 2.0 KR) 가 적용됩니다.
- namu.wiki 의 봇 차단 정책에 따라 일부 환경에서는 페이지가 로드되지 않을 수 있습니다.
