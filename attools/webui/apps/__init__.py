"""화면 목록. 새 화면을 만들면 여기 한 줄 더한다."""

from __future__ import annotations


def all_apps():
    from . import files_app

    return [files_app.make()]
