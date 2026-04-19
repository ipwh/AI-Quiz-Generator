import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def _one_line(s: str) -> str:
    """Google Forms API 的顯示文字不能含 newline；統一轉成單行。[1](https://issuetracker.google.com/issues/271891396?pli=1)"""
    if s is None:
        return ""
    s = str(s)
    # 將 \r\n \n \r 全部轉空格
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    # 壓縮多餘空白
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def create_quiz_form(creds, title: str, df):
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

            qtype = str(row.get("qtype", "single")).strip()
            if qtype not in {"single", "multiple", "true_false"}:
                qtype = "single"

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

            corr_vals = []
            for c in corr_list:
                if c not in {"1", "2", "3", "4"}:
                    continue
                i = int(c) - 1
                if 0 <= i < len(options):
                    v = options[i]
                    if v and v not in corr_vals:
                        corr_vals.append(v)

            if not corr_vals:
                corr_vals = [options[0]]

            explanation = _one_line(row.get("explanation", ""))

            choice_type = "CHECKBOX" if qtype == "multiple" else "RADIO"

            grading = {
                "pointValue": 1,
                "correctAnswers": {"answers": [{"value": v} for v in corr_vals]},
            }

            # 自動評分題的回饋要用 whenRight/whenWrong；generalFeedback 會出錯
            if explanation:
                grading["whenRight"] = {"text": explanation}
                grading["whenWrong"] = {"text": explanation}

            item_req = {
                "createItem": {
                    "item": {
                        "title": q,
                        "questionItem": {
                            "question": {
                                "required": True,
                                "choiceQuestion": {
                                    "type": choice_type,
                                    "options": [{"value": o} for o in options],
                                    "shuffle": False,
                                },
                                "grading": grading,
                            }
                        },
                    },
                    "location": {"index": idx},
                }
            }

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
