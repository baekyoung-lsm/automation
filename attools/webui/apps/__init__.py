"""화면 목록. 새 화면을 만들면 여기 한 줄 더한다."""

from __future__ import annotations


def all_apps():
    from . import (dev_app, doc_app, files_app, git_app, json_app, keys_app,
                   life_app, novel_app, sheet_app, text_app)

    return [files_app.make(), text_app.make(), sheet_app.make(),
            doc_app.make(), novel_app.make(), keys_app.make(),
            life_app.make(), dev_app.make(), json_app.make(), git_app.make()]
