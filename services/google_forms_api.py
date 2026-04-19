from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def create_quiz_form(creds, title: str, df):
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

            qtype = str(row.get("qtype", "single")).strip()
            if qtype not in {"single", "multiple", "true_false"}:
                qtype = "single"

            if qtype == "true_false":
                options = ["對", "錯"]
            else:
                options_raw = [
                    str(row.get("option_1", "")).strip(),
                    str(row.get("option_2", "")).strip(),
                    str(row.get("option_3", "")).strip(),
                    str(row.get("option_4", "")).strip(),
                ]
                options = [o for o in options_raw if o]
                if len(options) < 2:
                    options = [options_raw[0] or "（選項A）", "（選項B）"]

            # correct 支援 "1,3" 或 list
            corr = row.get("correct", "1")
            if isinstance(corr, list):
                corr_list = [str(x).strip() for x in corr]
            else:
                corr_list = [x.strip() for x in str(corr).split(",") if x.strip()]

            # correct index -> value（只取有效）
            corr_vals = []
            for c in corr_list:
                if c not in {"1", "2", "3", "4"}:
                    continue
                i = int(c) - 1
                if 0 <= i < len(options):
                    v = options[i].strip()
                    if v and v not in corr_vals:
                        corr_vals.append(v)

            if not corr_vals:
                corr_vals = [options[0]]

            explanation = str(row.get("explanation", "")).strip()

            # choiceQuestion type
            if qtype == "multiple":
                choice_type = "CHECKBOX"
            else:
                choice_type = "RADIO"

            grading = {
                "pointValue": 1,
                "correctAnswers": {"answers": [{"value": v} for v in corr_vals]},
            }
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