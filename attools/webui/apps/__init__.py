"""화면 목록. 새 화면을 만들면 여기 한 줄 더한다.

여기 적은 차례가 런처에 나오는 차례다. 같은 section 끼리 붙여 둔다.
"""

from __future__ import annotations


def all_apps():
    from . import (dev_app, doc_app, files_app, git_app, json_app, keys_app,
                   letters_app, life_app, novel_app, sheet_app, text_app)

    return [
        files_app.make(), text_app.make(), sheet_app.make(),   # 파일과 표
        doc_app.make(), novel_app.make(), letters_app.make(),  # 글
        dev_app.make(), json_app.make(), git_app.make(),       # 개발
        keys_app.make(), life_app.make(),                      # 그 밖
    ]
