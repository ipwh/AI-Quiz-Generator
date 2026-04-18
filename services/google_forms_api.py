from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def create_quiz_form(creds, title: str, df):
    """
    使用 Google Forms API 建立 Quiz 表單：
    1) create form
    2) batchUpdate：設定 isQuiz + 逐題 createItem
    回傳：formId, editUrl, responderUrl(如 API 有提供)
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

            if correct_index >= 0 and correct_index < len(options_raw) and options_raw[correct_index].strip():
                correct_value = options_raw[correct_index].strip()
            else:
                correct_value = options[0]

            explanation = str(row.get("explanation", "")).strip()

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

            if explanation:
                item_req["createItem"]["item"]["questionItem"]["question"]["grading"]["generalFeedback"] = {
                    "text": explanation
                }

            requests.append(item_req)
            idx += 1

        service.forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()

        info = service.forms().get(formId=form_id).execute()
        responder_url = info.get("responderUri")  # 不一定存在

        return {
            "formId": form_id,
            "editUrl": f"https://docs.google.com/forms/d/{form_id}/edit",
            "responderUrl": responder_url,
        }

    except HttpError as e:
        raise e
