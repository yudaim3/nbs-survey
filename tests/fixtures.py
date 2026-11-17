"""Complete synthetic answers, used only by tests."""
def complete_answers(schema, overrides=None):
    answers = {}
    for q in schema['questions']:
        if q['type'] == 'text':
            answers[q['id']] = 'テスト用の回答です。'
        elif q['type'] == 'single':
            answers[q['id']] = q['options'][1] if q['id'] in ('q1', 'q2') else q['options'][0]
        elif q['type'] == 'multi':
            answers[q['id']] = ['特になし'] if '特になし' in q['options'] else [q['options'][0]]
        else:
            answers[q['id']] = {option: '4' if q['type'] == 'rating' else '2' for option in q['options']}
    for key, value in (overrides or {}).items():
        if isinstance(value, dict):
            answers[key].update(value)
        else:
            answers[key] = value
    return answers
