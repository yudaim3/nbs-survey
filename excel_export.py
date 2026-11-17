"""Create the six-sheet survey export with the public openpyxl package."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import math
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

JST = timezone(timedelta(hours=9))
INVALID_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')


def excel_time(iso):
    return datetime.fromisoformat(iso).astimezone(JST).replace(tzinfo=None)


def chunks(value, size=300):
    parts, part, lines = [], '', 0
    for char in str(value):
        part += char
        lines += char == '\n'
        if len(part) >= size or lines >= 12:
            parts.append(part)
            part, lines = '', 0
    if part:
        parts.append(part)
    return parts or ['']


def put(cell, value):
    if isinstance(value, str):
        # Keep untrusted answers as literal strings, including =, +, -, @ and Excel error names.
        cell.value = INVALID_XML.sub(lambda m: f'\\u{ord(m[0]):04x}', value)
        cell.data_type = 's'
    else:
        cell.value = value


def export_workbook(data):
    schema, responses, event, summary = (data[key] for key in ('schema', 'responses', 'event', 'summary'))
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.creator = 'NBS WORKATION'

    def sheet(name, title, headers, rows, widths):
        ws = wb.create_sheet(name)
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.sheet_properties.tabColor = '087AA5'
        ws.freeze_panes = 'A5'
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))
        put(ws.cell(2, 1), title)
        ws.cell(2, 1).font = Font(name='Yu Gothic', size=15, bold=True, color='193C50')
        ws.cell(2, 1).alignment = Alignment(vertical='center', wrap_text=True)
        ws.row_dimensions[2].height = 42
        for column, (label, width) in enumerate(zip(headers, widths), 1):
            cell = ws.cell(4, column)
            put(cell, label)
            cell.font = Font(name='Yu Gothic', size=10, bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='087AA5')
            cell.alignment = Alignment(vertical='center', wrap_text=True)
            ws.column_dimensions[get_column_letter(column)].width = width
        ws.row_dimensions[4].height = 32
        for row_index, row in enumerate(rows, 5):
            lines = 1
            for column, value in enumerate(row, 1):
                cell = ws.cell(row_index, column)
                put(cell, value)
                cell.font = Font(name='Yu Gothic', size=10, color='193C50')
                cell.alignment = Alignment(vertical='top', wrap_text=True)
                if row_index % 2 == 0:
                    cell.fill = PatternFill('solid', fgColor='EAF6FC')
                if isinstance(value, datetime):
                    cell.number_format = 'yyyy-mm-dd hh:mm:ss'
                if isinstance(value, str):
                    lines = max(lines, sum(max(1, math.ceil(len(line) / max(7, widths[column-1] / 2.1)))
                                           for line in value.split('\n')))
            ws.row_dimensions[row_index].height = min(405, max(26, lines * 16 + 8))
        ws.auto_filter.ref = f'A4:{get_column_letter(len(headers))}{max(4, len(rows)+4)}'
        ws.print_title_rows = '1:4'
        ws.print_options.horizontalCentered = True
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        return ws

    questions = summary['questions']
    basics = [
        ['開催名', event['title'], ''],
        ['実施期間', ' ～ '.join(v for v in (event['start'], event['end']) if v), ''],
        ['実施場所', event['place'], ''],
        ['回答件数', summary['total'], '受付件数を集計（必須化前の氏名未入力の回答も含む）'],
        ['全体満足度（平均）', questions['q1']['average'], f"5点満点・有効回答 {questions['q1']['answered']} 件"],
        ['仕事のしやすさ（平均）', questions['q2']['average'], f"5点満点・有効回答 {questions['q2']['answered']} 件"],
        ['コミュニケーション改善の割合', summary['communication_rate'], f"Q5の肯定的2区分 / 有効回答 {questions['q5']['answered']} 件"],
        ['出力日時', excel_time(data['exported_at']), '日本時間'],
        ['集計方法', '出力時点の確定値', '空欄は未回答。割合の分母は各設問の有効回答数。'],
        ['回答の取扱い', '1送信を1件として集計', 'ログインなしのため、同一人物の別送信は自動で判別しません。'],
        ['', '', ''], ['設問・選択肢', '人数', '有効回答に対する割合'],
    ]
    for q in schema['questions']:
        if q['type'] == 'single':
            item = questions[q['id']]
            basics.append([q['title'], None, None])
            basics.extend([option, count, count / item['answered'] if item['answered'] else None]
                          for option, count in item['counts'].items())
            basics.append(['未回答', item['missing'], None])
    basics.extend([['', '', ''], ['Q12 必要な水回り', '人数', '集計区分']])
    for row in questions['q12']['rows']:
        basics.extend([row['label'], count, value] for value, count in row['counts'].items())
        basics.append([row['label'], row['missing'], '未回答'])
    main = sheet('集計サマリー', f"{event['title']} アンケート集計", ['項目', '結果', '補足'], basics, [56, 58, 65])
    main['B9'].number_format = main['B10'].number_format = '0.00'
    main['B11'].number_format = '0.0%'
    for index, row in enumerate(basics, 5):
        if isinstance(row[2], (int, float)):
            main.cell(index, 3).number_format = '0.0%'

    equipment = [[r[key] for key in ('label', 'answered', 'average', 'low', 'missing')]
                 for r in questions['q7']['rows']]
    eq = sheet('設備評価', 'Q7 設備・環境の評価', ['設備・環境', '有効回答数', '平均（5点満点）', '低評価（1〜2）', '未回答'], equipment, [35, 18, 22, 22, 18])
    for index in range(5, 5 + len(equipment)):
        eq.cell(index, 3).number_format = '0.00'

    multis = []
    for q in schema['questions']:
        if q['type'] == 'multi':
            item = questions[q['id']]
            multis.extend([f"Q{q['number']}", q['title'], option, count,
                           count / item['answered'] if item['answered'] else None, item['answered']]
                          for option, count in sorted(item['counts'].items(), key=lambda pair: -pair[1]))
    mu = sheet('複数選択集計', '複数選択の集計（割合の合計は100%を超える場合があります）',
               ['設問', '質問内容', '選択肢', '選択件数', '選択割合', '有効回答数'], multis, [10, 55, 48, 15, 15, 18])
    for index in range(5, 5 + len(multis)):
        mu.cell(index, 5).number_format = '0.0%'

    texts = []
    for response in responses:
        for q in schema['questions']:
            value = response['answers'].get(q['id']) if q['type'] == 'text' else response['other'].get(q['id'])
            if value:
                parts = chunks(value)
                texts.extend([response['id'], response['name'], f"Q{q['number']}" + ('' if q['type'] == 'text' else ' その他'),
                              q['title'], index, len(parts), part] for index, part in enumerate(parts, 1))
    sheet('自由記述一覧', '自由記述の原文（長文は同じ受付ID・設問の連番で続きます）',
          ['受付ID', '回答者名', '設問', '質問内容', '連番', '分割数', '回答原文'], texts, [40, 22, 16, 52, 10, 10, 100])

    raw = []
    for response in responses:
        for q in schema['questions']:
            answer = response['answers'].get(q['id'])
            prefix = [response['id'], excel_time(response['created_at']), response['name'], f"Q{q['number']}"]
            if q['type'] == 'single':
                raw.append(prefix + [q['title'], answer])
            elif q['type'] == 'multi':
                raw.extend(prefix + [option, None if answer is None else int(option in answer)] for option in q['options'])
            elif q['type'] in ('rating', 'count'):
                for option in q['options']:
                    value = (answer or {}).get(option)
                    raw.append(prefix + [option, value if value in (None, '6以上') else int(value)])
    sheet('回答データ', '回答データ（複数選択は選択1・未選択0、未回答は空欄）',
          ['受付ID', '受付日時（日本時間）', '回答者名', '設問', '項目', '回答'], raw, [40, 30, 22, 10, 58, 50])

    types = dict(text='自由記述', single='単一選択', multi='複数選択', rating='5段階評価', count='必要数')
    rows = []
    for q in schema['questions']:
        condition = (f"最大{q['max']}つ" if q.get('max') else
                     '「特になし」は他の項目と同時選択不可' if q['id'] == 'q8' else
                     '1・2・3・4・5・6以上。6以上を6として平均計算しない。' if q['id'] == 'q12' else '')
        rows.append([f"Q{q['number']}", schema['sections'][q['section']-1], q['title'],
                     types[q['type']], '\n'.join(q.get('options', [])), condition])
    sheet('設問一覧', 'アンケートの設問と選択肢', ['設問', 'セクション', '質問内容', '回答形式', '項目・選択肢', '条件'], rows, [10, 42, 64, 18, 58, 48])
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
