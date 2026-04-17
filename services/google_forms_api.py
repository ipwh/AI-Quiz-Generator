from googleapiclient.discovery import build


def create_quiz_form(creds, title: str, df):
    """使用 Google Forms API 建立 Quiz 表單。

    依 Google Forms API 指引：先 create form，再 batchUpdate 設 isQuiz 與加入 items。
    """
    service = build('forms', 'v1', credentials=creds, cache_discovery=False)

    # 1) create form
    form = service.forms().create(body={'info': {'title': title}}).execute()
    form_id = form['formId']

    # 2) build requests
    requests = []

    # set quiz
    requests.append({
        'updateSettings': {
            'settings': {'quizSettings': {'isQuiz': True}},
            'updateMask': 'quizSettings.isQuiz'
        }
    })

    # create items
    idx = 0
    for _, row in df.iterrows():
        q = str(row.get('question','')).strip()
        if not q:
            continue
        options = [
            str(row.get('option_1','')).strip(),
            str(row.get('option_2','')).strip(),
            str(row.get('option_3','')).strip(),
            str(row.get('option_4','')).strip(),
        ]
        correct = str(row.get('correct','1')).strip()
        if correct not in {'1','2','3','4'}:
            correct = '1'
        correct_index = int(correct) - 1
        correct_value = options[correct_index]

        # choice question with grading
        item_req = {
            'createItem': {
                'item': {
                    'title': q,
                    'questionItem': {
                        'question': {
                            'choiceQuestion': {
                                'type': 'RADIO',
                                'options': [{'value': o} for o in options],
                                'shuffle': False,
                            },
                            'grading': {
                                'pointValue': 1,
                                'correctAnswers': {
                                    'answers': [{'value': correct_value}]
                                }
                            }
                        }
                    }
                },
                'location': {'index': idx}
            }
        }
        requests.append(item_req)
        idx += 1

    service.forms().batchUpdate(formId=form_id, body={'requests': requests}).execute()

    # 3) fetch URLs
    info = service.forms().get(formId=form_id).execute()
    return {
        'formId': form_id,
        'editUrl': f"https://docs.google.com/forms/d/{form_id}/edit",
        'responderUrl': info.get('responderUri', f"https://docs.google.com/forms/d/e/{form_id}/viewform")
    }
