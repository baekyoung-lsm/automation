"""python -m attools.cli 로도 부를 수 있게 한다.

윈도우의 at.bat 이 이 자리로 부른다. 확장자 없는 실행 스크립트(at)를 py
런처에 물리는 것보다 이쪽이 확실하다.
"""

from . import main

raise SystemExit(main())
