import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def _one_line(s: str) -> str:
    """Forms API 顯示文字避免換行。"""
    if s is None:
        return ""
    s = str(s)
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def create_quiz_form(creds, title: str, df):
    """
    建立 Google Form Quiz（只匯出題幹+選項+答案）。
    注意：不匯出 explanation 與 needs_review（老師備註不出到學生表單）。
    """
    service = build("forms", "v1", credentials=creds, cache_discovery=False)

    try:
        title = _one_line(title)
        form = service.forms().create(body={"info": {"title": title}}).execute()
        form_id = form["formId"]

        requests = []
        requests.append({
            "updateSettings": {
                "settings": {"quizSettings": {"isQuiz": True}},
                "updateMask": "quizSettings.isQuiz",
            }
        })

        idx = 0
        for _, row in df.iterrows():
            q = _one_line(row.get("question", ""))
            if not q:
                continue

            # ✅ 本版只做 single（RADIO 4選1 / true_false 可當成 2選1）
            qtype = str(row.get("qtype", "single")).strip()
            if qtype == "true_false":
                options = ["對", "錯"]
            else:
                options_raw = [
                    _one_line(row.get("option_1", "")),
                    _one_line(row.get("option_2", "")),
                    _one_line(row.get("option_3", "")),
                    _one_line(row.get("option_4", "")),
                ]
                options = [o for o in options_raw if o]
                if len(options) < 2:
                    options = [options_raw[0] or "（選項A）", "（選項B）"]

            corr = row.get("correct", "1")
            if isinstance(corr, list):
                corr_list = [str(x).strip() for x in corr]
            else:
                corr_list = [x.strip() for x in str(corr).split(",") if x.strip()]

            # single：只取第一個有效答案
            correct_value = None
            for c in corr_list:
                if c in {"1", "2", "3", "4"}:
                    i = int(c) - 1
                    if 0 <= i < len(options):
                        correct_value = options[i]
                        break
            if not correct_value:
                correct_value = options[0]

            item_req = {
                "createItem": {
                    "item": {
                        "title": q,
                        "questionItem": {
                            "question": {
                                "required": True,
                                "choiceQuestion": {
                                    "type": "RADIO",
                                    "options": [{"value": o} for o in options],
                                    "shuffle": False,
                                },
                                "grading": {
                                    "pointValue": 1,
                                    "correctAnswers": {"answers": [{"value": correct_value}]},
                                },
                            }
                        },
                    },
                    "location": {"index": idx},
                }
            }

            # ✅ 不輸出 explanation / needs_review：因此不設 whenRight/whenWrong
            requests.append(item_req)
            idx += 1

        service.forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()
        info = service.forms().get(formId=form_id).execute()

        return {
            "formId": form_id,
            "editUrl": f"https://docs.google.com/forms/d/{form_id}/edit",
            "responderUrl": info.get("responderUri"),
        }

    except HttpError as e:
        raise e
