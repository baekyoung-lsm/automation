@echo off
rem 새 기능을 받아 오는 자리. 어떻게 받았는지에 따라 갈린다.
rem   git 으로 받았으면  -> git pull 로 그 자리에서 최신이 된다
rem   at.pyz 를 받았으면 -> 새 at.pyz 로 덮어쓰면 된다 (지울 것은 없다)
chcp 65001 >nul
setlocal
set "HERE=%~dp0"

if exist "%HERE%.git" goto pull

echo.
echo 이 폴더는 git 으로 받은 것이 아닙니다.
echo   새 기능은 새 at.pyz 를 받아 이 파일 옆의 at.pyz 에 덮어쓰면 들어옵니다.
echo   따로 지울 것은 없습니다.
echo.
echo 설정과 되돌리기 기록은 사용자 폴더 아래 .attools 에 따로 있어
echo 덮어써도 그대로 남습니다.
echo.
pause
exit /b 0

:pull
where git >nul 2>nul
if errorlevel 1 (
  echo.
  echo git 을 찾지 못했습니다. https://git-scm.com/download/win 에서 받아 주세요.
  echo.
  pause
  exit /b 1
)
git -C "%HERE%." pull
echo.
pause
