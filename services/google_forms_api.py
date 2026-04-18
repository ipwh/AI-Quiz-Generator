from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def create_quiz_form(creds, title: str, df):
    """
    Google Forms API 建立 Quiz 表單：
    1) create form
    2) batchUpdate：設定 isQuiz + 逐題 createItem
    """
    service = build("forms", "v1", credentials=creds, cache_discovery=False)

    try:
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
            q = str(row.get("question", "")).strip()
            if not q:
                continue

            options_raw = [
                str(row.get("option_1", "")).strip(),
                str(row.get("option_2", "")).strip(),
                str(row.get("option_3", "")).strip(),
                str(row.get("option_4", "")).strip(),
            ]
            options = [o for o in options_raw if o]
            if len(options) < 2:
                options = [options_raw[0] or "（選項A）", "（選項B）"]

            correct = str(row.get("correct", "1")).strip()
            if correct not in {"1", "2", "3", "4"}:
                correct = "1"
            correct_index = int(correct) - 1

            if 0 <= correct_index < len(options_raw) and options_raw[correct_index].strip():
                correct_value = options_raw[correct_index].strip()
            else:
                correct_value = options[0]

            explanation = str(row.get("explanation", "")).strip()

            grading = {
                "pointValue": 1,
                "correctAnswers": {"answers": [{"value": correct_value}]},
            }

            # ✅ 修正：自動評分多項選擇題不能用 generalFeedback
            # 要用 whenRight / whenWrong 提供回饋 [5](https://developers.google.cn/workspace/forms/api/guides/setup-grading?hl=en)[4](https://googleapis.dev/dotnet/Google.Apis.Forms.v1/latest/api/Google.Apis.Forms.v1.Data.Grading.html)
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
                                    "type": "RADIO",
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
        responder_url = info.get("responderUri")  # 可能存在也可能沒有 [9](https://developers.google.com/workspace/forms/api/reference/rest/v1/forms)

        return {
            "formId": form_id,
            "editUrl": f"https://docs.google.com/forms/d/{form_id}/edit",
            "responderUrl": responder_url,
        }

    except HttpError as e:
        raise e
