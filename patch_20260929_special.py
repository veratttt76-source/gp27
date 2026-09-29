from pathlib import Path
import re

app_path = Path("src/app.py")
admin_path = Path("src/templates/admin.html")
eval_path = Path("src/templates/evaluation_form.html")

app = app_path.read_text(encoding="utf-8")
admin = admin_path.read_text(encoding="utf-8")
tpl = eval_path.read_text(encoding="utf-8")

def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"{label}: target not found")
    return text.replace(old, new, 1)

# 1) Existing users keep the previous behaviour: Economist/Admin start with the
# permission enabled unless the flag has already been explicitly stored.
app = replace_once(
    app,
    '        u.setdefault("department", "")\n',
    '        u.setdefault("department", "")\n        u.setdefault("special_criteria", u.get("role") in ("economist", "admin"))\n',
    "user special permission default",
)

# Live permission lookup. This is deliberately independent of role.
anchor = '''def find_user(d: dict, user_id):
    return next((u for u in d["users"] if str(u.get("id")) == str(user_id)), None)
'''
if anchor not in app:
    raise SystemExit("find_user anchor not found")
app = app.replace(
    anchor,
    anchor + '''

def can_edit_special_criteria(d: dict) -> bool:
    u = find_user(d, session.get("user_id"))
    return bool(u and u.get("special_criteria"))
''',
    1,
)

# New evaluation: special criteria may be filled only when the account permission is set.
app = replace_once(
    app,
    '''def evaluation_new():
    d = load_data()
''',
    '''def evaluation_new():
    d = load_data()
    can_special_criteria = can_edit_special_criteria(d)
''',
    "evaluation_new permission",
)
app = replace_once(
    app,
    '        update_answers_from_form(d, e, allow_regular=True, allow_special=False)\n',
    '        update_answers_from_form(d, e, allow_regular=True, allow_special=can_special_criteria)\n',
    "new evaluation special answers",
)

# Every evaluation_form render in evaluation_new needs the permission variable.
new_start = app.index('def evaluation_new():')
edit_start = app.index('def evaluation_edit(', new_start)
new_block = app[new_start:edit_start]
new_block = new_block.replace(
    'answers={}, is_new=True)',
    'answers={}, is_new=True, can_special_criteria=can_special_criteria)'
)
if 'can_special_criteria=can_special_criteria' not in new_block:
    raise SystemExit("evaluation_new render permission not injected")
app = app[:new_start] + new_block + app[edit_start:]

# Existing evaluation: use the same account permission instead of role.
app = replace_once(
    app,
    '''    role = session.get("role")
    manager_editable = role == "manager" and e.get("status") in ("draft", "returned")
''',
    '''    role = session.get("role")
    can_special_criteria = can_edit_special_criteria(d)
    manager_editable = role == "manager" and e.get("status") in ("draft", "returned")
''',
    "evaluation_edit permission",
)
app = replace_once(
    app,
    '                allow_special=(role in ("economist", "admin")),\n',
    '                allow_special=can_special_criteria,\n',
    "edit special answers",
)
app = replace_once(
    app,
    '        admin_editable=admin_editable,\n    )\n',
    '        admin_editable=admin_editable,\n        can_special_criteria=can_special_criteria,\n    )\n',
    "evaluation_edit render permission",
)

# Account administration: checkbox "Критерии специальные".
app = replace_once(
    app,
    '''                "department": request.form.get("department") or "",
            })
''',
    '''                "department": request.form.get("department") or "",
                "special_criteria": bool(request.form.get("special_criteria")),
            })
''',
    "new user special permission",
)
app = replace_once(
    app,
    '''                u["department"] = request.form.get("department") or ""
                password = request.form.get("password") or ""
''',
    '''                u["department"] = request.form.get("department") or ""
                u["special_criteria"] = bool(request.form.get("special_criteria"))
                password = request.form.get("password") or ""
''',
    "save user special permission",
)

# Admin UI. Do not alter any other account fields.
admin = replace_once(
    admin,
    '<th>Логин</th><th>Имя</th><th>Роль</th><th>Подразделение</th><th>Новый пароль</th><th></th>',
    '<th>Логин</th><th>Имя</th><th>Роль</th><th>Подразделение</th><th>Критерии специальные</th><th>Новый пароль</th><th></th>',
    "admin users header",
)
row_department = '''</select></td><td><input form="user-{{ u.id }}" type="password" name="password" placeholder="не менять"></td>'''
row_replacement = '''</select></td><td><label class="check"><input form="user-{{ u.id }}" type="checkbox" name="special_criteria" {% if u.special_criteria %}checked{% endif %}> Разрешено</label></td><td><input form="user-{{ u.id }}" type="password" name="password" placeholder="не менять"></td>'''
admin = replace_once(admin, row_department, row_replacement, "existing user checkbox")

new_user_department = '''</select><select name="department"><option value="">— подразделение —</option>{% for dep in data.departments %}<option value="{{ dep }}">{{ dep }}</option>{% endfor %}</select><button class="btn primary" name="action" value="add">Добавить</button>'''
new_user_replacement = '''</select><select name="department"><option value="">— подразделение —</option>{% for dep in data.departments %}<option value="{{ dep }}">{{ dep }}</option>{% endfor %}</select><label class="check"><input type="checkbox" name="special_criteria"> Критерии специальные</label><button class="btn primary" name="action" value="add">Добавить</button>'''
admin = replace_once(admin, new_user_department, new_user_replacement, "new user checkbox")

# Evaluation UI: special block is governed by the new permission, not by role.
tpl = tpl.replace('Заполняет Экономист', 'Критерии специальные')
old_disabled = "{% set disabled = (g.special and session.get('role')=='manager') or (not is_new and session.get('role')=='manager' and not manager_editable) %}"
new_disabled = "{% set disabled = (g.special and not can_special_criteria) or (not is_new and session.get('role')=='manager' and not manager_editable) %}"
tpl = replace_once(tpl, old_disabled, new_disabled, "special criteria template permission")

# 2) Employee selector: keep the department in option data/value logic, but show only FIO.
# The previous 29 Sep patch renders "FIO — Department"; remove only the visible department.
patterns = [
    ('>{{ employee.fio }} — {{ employee.department }}</option>', '>{{ employee.fio }}</option>'),
    ('>{{ employee.name }} — {{ employee.department }}</option>', '>{{ employee.name }}</option>'),
    ('>{{ employee.fio }} - {{ employee.department }}</option>', '>{{ employee.fio }}</option>'),
    ('>{{ employee.name }} - {{ employee.department }}</option>', '>{{ employee.name }}</option>'),
]
fio_changed = False
for old, new in patterns:
    if old in tpl:
        tpl = tpl.replace(old, new)
        fio_changed = True

# Fallback for whitespace/newline around the dash, preserving all option attributes.
if not fio_changed:
    new_tpl, count = re.subn(
        r'>\s*\{\{\s*employee\.(fio|name)\s*\}\}\s*[—-]\s*\{\{\s*employee\.department\s*\}\}\s*</option>',
        lambda m: '>{{ employee.' + m.group(1) + ' }}</option>',
        tpl,
    )
    if count:
        tpl = new_tpl
        fio_changed = True

if not fio_changed:
    raise SystemExit("employee visible FIO-department option target not found")

# Safety checks: the old role rule must be gone from the special criteria controls.
if 'allow_special=(role in ("economist", "admin"))' in app:
    raise SystemExit("old role-based special criteria write permission still present")
if "(g.special and session.get('role')=='manager')" in tpl:
    raise SystemExit("old manager-only special criteria UI restriction still present")
if "special_criteria" not in admin or "special_criteria" not in app:
    raise SystemExit("special criteria permission checkbox/state missing")

app_path.write_text(app, encoding="utf-8")
admin_path.write_text(admin, encoding="utf-8")
eval_path.write_text(tpl, encoding="utf-8")

print("OK: only 29 Sep special-permission and FIO-display corrections applied")
