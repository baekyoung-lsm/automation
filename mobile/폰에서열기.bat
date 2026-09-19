@echo off
rem 폰에서 이 화면을 열려고 잠깐 띄우는 자리. 터미널을 몰라도 쓰게 하려는 것이다.
rem   더블클릭 -> 같은 와이파이에 붙은 폰이 열 수 있는 주소를 알려 준다
rem   창을 닫으면 서버도 꺼진다. 폰에 한 번 «앱 설치» 해 두면 그 뒤로는
rem   이 창을 켜지 않아도 오프라인으로 돈다.
chcp 65001 >nul
setlocal
set "HERE=%~dp0"
set "PORT=8000"

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (where python3 >nul 2>nul && set "PY=python3")
if not defined PY goto nopython

echo.
echo  폰 브라우저에서 아래 주소 가운데 하나를 여세요.
echo.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  for /f "tokens=1" %%b in ("%%a") do echo     http://%%b:%PORT%/
)
echo.
echo  그 다음 브라우저 메뉴에서 «앱 설치»(또는 홈 화면에 추가)를 누르면
echo  런처에 아이콘이 생기고 주소창 없이 전체 화면으로 돕니다.
echo.
echo  이 창을 닫으면 서버가 꺼집니다. Ctrl+C 로도 끕니다.
echo  같은 공유기에 붙은 다른 기기도 열 수 있으니 다 쓰면 닫아 주세요.
echo.
cd /d "%HERE%"
"%PY%" -m http.server %PORT% --bind 0.0.0.0
goto done

:nopython
echo.
echo 파이썬을 찾지 못했습니다. 파이썬 3.10 이상이 있어야 띄울 수 있습니다.
echo   https://www.python.org/downloads/ 에서 받아 설치해 주세요.
echo   설치 화면 아래의 "Add python.exe to PATH" 를 켜 주셔야 합니다.
echo.
pause
exit /b 1

:done
echo.
pause
