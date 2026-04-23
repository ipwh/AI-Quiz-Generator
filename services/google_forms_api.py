# services/google_forms_api.py
# ---------------------------------------------------------
# Google Forms API service
# Supports: Quiz mode (with grading + explanation) and Survey mode
# ---------------------------------------------------------

from __future__ import annotations
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def _one_line(s) -> str:
    """Forms API display text - remove newlines."""
    if s is None:
        return ""
    s = str(s)
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def create_form(
    creds,
    title: str,
    df,
    quiz_mode: bool = True,
    points_per_question: int = 1,
    show_explanation: bool = True,
) -> dict:
    """
    Build a Google Form from a question DataFrame.

    Args:
        creds: Google OAuth credentials
        title: Form title
        df: DataFrame with columns: question, option_1..4, correct, explanation, qtype
        quiz_mode: True = Quiz (with answers+grading), False = plain survey
        points_per_question: Score per correct answer (quiz mode only)
        show_explanation: Show explanation as feedback when wrong (quiz mode only)

    Returns:
        dict with formId, editUrl, responderUrl
    """
    service = build("forms", "v1", credentials=creds, cache_discovery=False)

    try:
        form_title = _one_line(title) or "AI 生成題目"
        form = service.forms().create(body={"info": {"title": form_title}}).execute()
        form_id = form["formId"]

        requests_list = []

        # --------------------------------------------------
        # Step 1: Set quiz mode if requested
        # --------------------------------------------------
        if quiz_mode:
            requests_list.append({
                "updateSettings": {
                    "settings": {"quizSettings": {"isQuiz": True}},
                    "updateMask": "quizSettings.isQuiz",
                }
            })

        # --------------------------------------------------
        # Step 2: Build question items
        # --------------------------------------------------
        idx = 0
        for _, row in df.iterrows():
            q = _one_line(row.get("question", ""))
            if not q:
                continue

            qtype = str(row.get("qtype", "single")).strip()

            # Build options list
            if qtype == "true_false":
                options = ["True", "False"]
            else:
                options_raw = [
                    _one_line(row.get("option_1", "")),
                    _one_line(row.get("option_2", "")),
                    _one_line(row.get("option_3", "")),
                    _one_line(row.get("option_4", "")),
                ]
                options = [o for o in options_raw if o]
                if len(options) < 2:
                    options = [options_raw[0] or "Option A", "Option B"]

            # Resolve correct answer text
            corr = row.get("correct", "1")
            if isinstance(corr, list):
                corr_list = [str(x).strip() for x in corr]
            else:
                corr_list = [x.strip() for x in str(corr).split(",") if x.strip()]

            correct_value = None
            for c in corr_list:
                if c in {"1", "2", "3", "4"}:
                    i = int(c) - 1
                    if 0 <= i < len(options):
                        correct_value = options[i]
                        break
            if not correct_value:
                correct_value = options[0]

            # Build question structure
            choice_question = {
                "type": "RADIO",
                "options": [{"value": o} for o in options],
                "shuffle": False,
            }

            question_body: dict = {
                "required": True,
                "choiceQuestion": choice_question,
            }

            # Add grading only in quiz mode
            if quiz_mode:
                explanation = _one_line(row.get("explanation", ""))
                grading: dict = {
                    "pointValue": points_per_question,
                    "correctAnswers": {"answers": [{"value": correct_value}]},
                }
                # Show explanation as feedback when answer is wrong
                if show_explanation and explanation:
                    grading["whenWrong"] = {"text": explanation}
                question_body["grading"] = grading

            item_req = {
                "createItem": {
                    "item": {
                        "title": q,
                        "questionItem": {"question": question_body},
                    },
                    "location": {"index": idx},
                }
            }
            requests_list.append(item_req)
            idx += 1

        if not requests_list:
            raise ValueError("No valid questions to export.")

        # --------------------------------------------------
        # Step 3: Submit batchUpdate
        # --------------------------------------------------
        service.forms().batchUpdate(
            formId=form_id,
            body={"requests": requests_list},
        ).execute()

        info = service.forms().get(formId=form_id).execute()

        return {
            "formId": form_id,
            "editUrl": f"https://docs.google.com/forms/d/{form_id}/edit",
            "responderUrl": info.get("responderUri", ""),
        }

    except HttpError as e:
        raise e


# Keep old function name as alias for backward compatibility
def create_quiz_form(creds, title: str, df) -> dict:
    """Backward-compatible alias - always creates quiz mode form."""
    return create_form(creds, title, df, quiz_mode=True, show_explanation=True)
