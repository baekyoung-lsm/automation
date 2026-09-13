@echo off
rem 윈도우에서 더블클릭·끌어놓기로 쓰는 자리. 터미널을 몰라도 쓰게 하려는 것이다.
rem   그냥 더블클릭        -> 브라우저 화면(at ui)이 뜬다
rem   폴더·파일을 끌어놓기 -> 그것으로 할 만한 명령을 알려 준다
rem   at.bat file sweep .  -> 터미널에서 쓰듯 그대로 넘긴다
rem 이 파일 옆에 attools 폴더가 있으면 그것으로, 없으면 at.pyz 로 돌린다.
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
set "HERE=%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (where python3 >nul 2>nul && set "PY=python3")
if not defined PY goto nopython

if exist "%HERE%attools\cli\__init__.py" goto source
if exist "%HERE%at.pyz" goto bundle
goto nofiles

:source
set "PYTHONPATH=%HERE%"
if "%~1"=="" ("%PY%" -m attools.cli ui) else ("%PY%" -m attools.cli %*)
goto done

:bundle
if "%~1"=="" ("%PY%" "%HERE%at.pyz" ui) else ("%PY%" "%HERE%at.pyz" %*)
goto done

:nopython
echo.
echo 파이썬을 찾지 못했습니다. attools 는 파이썬 3.10 이상에서 돕니다.
echo   https://www.python.org/downloads/ 에서 받아 설치해 주세요.
echo   설치 화면 아래의 "Add python.exe to PATH" 를 켜 주셔야 합니다.
echo.
pause
exit /b 1

:nofiles
echo.
echo at.pyz 를 찾지 못했습니다.
echo   이 파일(at.bat)과 at.pyz 를 같은 폴더에 두어 주세요.
echo.
pause
exit /b 1

:done
echo.
pause
