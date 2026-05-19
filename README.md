# ExcelNamuViewer (ExcelView)

엑셀 처럼 위장된 나무위키 뷰어. PySide6 + QtWebEngine 으로 구현.

---

## ⬇️ 바로 다운로드 (빌드 불필요)

> **소스 빌드 / Python 설치 없이 즉시 사용할 수 있습니다.**
>
> 👉 **[GitHub Releases 페이지](https://github.com/summer21000/ExcelNamuViewer/releases/latest)** 에서 최신 `ExcelView.exe` (≈245 MB) 를 다운로드 → **더블클릭만 하면 실행**
>
> - Windows 10 / 11 (64bit) 에서 바로 동작
> - Python, pip, git clone 모두 불필요 — 단일 실행 파일
>
> ⏳ **첫 실행은 10~20초 정도 화면이 안 뜰 수 있습니다.** `--onefile` 압축 해제 + Qt WebEngine 초기화에 시간이 걸립니다. 두 번째 실행부터는 빠릅니다.

---

- namu.wiki 페이지의 전체 시각 구조를 좌표 기반으로 엑셀 셀 그리드에 매핑
- 이미지는 셀에 `📷 [사진 보기]` placeholder 로 표시 → 더블 클릭 시 별창에 사진 표시
- 인라인 링크 더블 클릭으로 이동 + 우클릭 → "새 시트로 열기" 지원
- 각주 `[1]`, `[2]` 셀 단일 클릭 시 toolTip 으로 본문 표시
- 광고 컨테이너 자동 차단
- 좌우 스크롤 차단 + 윈도우 폭 따라 자동 줄바꿈
- 모든 시트 **첫 행 frozen** (스크롤 내려도 헤더/제목 고정)
- **Sheet1 = 위장 시트** (주간 업무 진행 현황) — 사무실에서 일하는 척 할 때 `Ctrl+Z` 한 방으로 점프

## 빠른 실행 (Windows)

Python 3.10+ 가 설치된 상태에서:

```cmd
run.bat
```

처음 실행 시 자동으로 `.venv` 생성 + PySide6 설치 (약 250MB, 1회).
이후엔 즉시 실행됨.

> ⏳ **시작 시 PySide6 / Qt WebEngine 로드에 5~15초 정도 걸립니다.** 창이 바로 안 뜨더라도 잠깐 기다려주세요.

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

> ⏳ 빌드된 `.exe` 의 **첫 실행은 10~20초** 정도 걸립니다 (`--onefile` 압축 해제 + Qt WebEngine 초기화). 두 번째 실행부터는 빨라집니다.

## 사용법

> 💡 **빌드 없이 즉시 쓰고 싶다면** → [Releases 페이지](https://github.com/summer21000/ExcelNamuViewer/releases/latest) 에서 `ExcelView.exe` 다운로드 → 더블클릭.
> ⏳ 첫 실행은 압축 해제 + Qt WebEngine 초기화로 **10~20초** 정도 검은 화면일 수 있습니다.

1. 실행하면 **Sheet1 (위장 시트)** 가 먼저 보임. 일하는 척 하기 좋은 빈 양식이 떠있음.
2. 본격 사용하려면 우상단 검색박스에 나무위키 문서 제목 입력 + Enter
   - 예: `악어`, `리누스 토르발스`, `Qt`
   - 일반 URL (`https://...`) / 로컬 파일 경로도 그대로 입력 가능
3. 자동으로 Sheet2 (작업 영역) 로 전환 + 페이지 로드 (약 5초)
4. 셀 동작
   - **파란 밑줄 셀** = 링크 → **더블클릭**해서 이동 / **우클릭 → 새 시트로 열기**
   - **회색 밑줄 `[N]`** = 각주 → **단일클릭**해서 toolTip
   - **📷 셀** = 이미지 → **더블클릭**해서 사진 팝업

### 위장 모드 (사무실 생존)

- **`Ctrl+Z`** 어떤 시트/화면에서든 즉시 **Sheet1 (위장 시트)** 으로 점프
- 위장 시트의 헤더는 frozen 처리되어 스크롤해도 그대로 보임
- 검색박스에 텍스트 치고 Enter 하면 자동으로 작업 시트(Sheet2~) 로 전환되며 위장 시트는 그대로 유지됨
- 위장 시트의 셀(헤더 포함)은 **직접 더블클릭으로 편집 가능** — 회사/업무에 맞게 항목 커스터마이즈
- **`Ctrl+S`** 로 명시 저장. 시트 전환 / 프로그램 종료 시에도 자동 저장
- 저장 위치: 프로그램과 같은 폴더의 `ExcelViewAPPDATA\decoy_sheet1.json`. 다음 실행 시 자동 복원

## 단축키

| 단축키 | 기능 |
|---|---|
| `Enter` (검색박스) | 페이지 로드 |
| `Ctrl+Z` | Sheet1 (위장 시트) 로 즉시 점프 |
| `Ctrl+S` | 위장 시트 저장 (Sheet1 에서만 동작) |
| `Alt+←` / `Backspace` | 뒤로 가기 |
| `Ctrl+D` | namu.wiki 원본 페이지를 별창에 표시 (디버그) |

## 시트 구성

| 시트 | 용도 |
|---|---|
| **Sheet1** | 위장 시트 (주간 업무 진행 현황 헤더 + 빈 양식). 시작 시 기본 표시 |
| **Sheet2** | namu.wiki 작업 시트 — 첫 검색 시 자동 활성화 |
| **Sheet3+** | 우클릭 → "새 시트로 열기" 또는 추가 검색 시 동적 생성 |

## 디렉토리 구조

```
ExcelView/
├── main.py                 # 엔트리
├── excelview/
│   ├── mainwindow.py       # 메인 윈도우 + 시트별 상태 관리
│   ├── ribbonbar.py        # 엑셀 풍 리본 + 검색박스 + 뒤로 버튼
│   ├── formulabar.py       # 이름박스 + fx + 수식 입력줄
│   ├── sheetview.py        # 셀 그리드 + frozen top row + 우클릭 메뉴
│   ├── sheettabbar.py      # Sheet1/2/... 동적 탭
│   ├── statusbar.py        # 그린 상태바 + 줌
│   ├── namuloader.py       # QtWebEngine 으로 namu.wiki 로드 + 토큰 추출
│   ├── namuformatter.py    # positioned tokens → 셀 매트릭스 (단어/punctuation 처리)
│   ├── imagedialog.py      # 이미지 미리보기 (520x400 고정)
│   └── decoysheets.py      # 위장 시트 데이터
├── resources/excel.qss     # 엑셀 룩 스타일시트
├── ExcelView.spec          # PyInstaller 빌드 spec
├── requirements.txt        # 실행 의존성
├── requirements-build.txt  # 빌드 의존성 (pyinstaller 포함)
└── run.bat                 # 원클릭 실행
```

## 라이선스 / 주의

- 본 프로그램은 학습/실험 목적의 뷰어이며 namu.wiki 콘텐츠 자체에는 namu.wiki 의 라이선스(CC BY-NC-SA 2.0 KR) 가 적용됩니다.
- namu.wiki 의 봇 차단 정책에 따라 일부 환경에서는 페이지가 로드되지 않을 수 있습니다.
