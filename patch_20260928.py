from pathlib import Path

app_path = Path("src/app.py")
tpl_path = Path("src/templates/evaluation_form.html")
admin_path = Path("src/templates/admin.html")

app = app_path.read_text(encoding="utf-8")

replacements = [
(
'    for key in ("users", "departments", "employments", "funding_types", "groups", "positions", "evaluations", "audit"):\n',
'    for key in ("users", "departments", "employments", "funding_types", "groups", "positions", "evaluations", "audit", "employees"):\n'
),
(
'    d["schema_version"] = 6\n\n    # Keep old archives compatible with the new hidden flag.\n',
'''    d["schema_version"] = 6

    # Employee directory. Existing databases are initialized from employee names already present in evaluations.
    if not d.get("employees"):
        d["employees"] = sorted({
            (e.get("employee") or "").strip()
            for e in d.get("evaluations", [])
            if (e.get("employee") or "").strip()
        }, key=str.lower)

    # Keep old archives compatible with the new hidden flag.
'''
),
(
'        department = session.get("department") if session.get("role") == "manager" else (request.form.get("department") or "")\n',
'        department = (request.form.get("department") or default_department or "").strip()\n'
),
(
'''        if not e["employee"]:
            flash("Укажите ФИО работника", "error")
            return render_template("evaluation_form.html", data=d, e=e, groups=evaluation_groups(d, e["position_id"]), answers={}, is_new=True)
''',
'''        if not e["employee"]:
            flash("Выберите ФИО работника", "error")
            return render_template("evaluation_form.html", data=d, e=e, groups=evaluation_groups(d, e["position_id"]), answers={}, is_new=True)
        if e["employee"] not in d.get("employees", []):
            flash("Выберите работника из справочника ФИО", "error")
            return render_template("evaluation_form.html", data=d, e=e, groups=evaluation_groups(d, e["position_id"]), answers={}, is_new=True)
'''
),
(
'        if role == "manager" and raw.get("department") != session.get("department"):\n            continue\n',
'''        if role == "manager" and raw.get("department") != session.get("department") and str(raw.get("manager_id")) != str(session.get("user_id")):
            continue
'''
),
(
'''def check_eval_access(e: dict):
    if session.get("role") == "manager" and e.get("department") != session.get("department"):
        return False
''',
'''def check_eval_access(e: dict):
    if session.get("role") == "manager" and e.get("department") != session.get("department") and str(e.get("manager_id")) != str(session.get("user_id")):
        return False
'''
),
(
'''        if can_edit_core:
            if role != "manager":
                e["department"] = request.form.get("department") or e.get("department", "")
            e["employee"] = (request.form.get("employee") or e.get("employee", "")).strip()
''',
'''        if can_edit_core:
            e["department"] = request.form.get("department") or e.get("department", "")
            e["employee"] = (request.form.get("employee") or e.get("employee", "")).strip()
            if role == "manager" and e["employee"] not in d.get("employees", []):
                flash("Выберите работника из справочника ФИО", "error")
                return redirect(url_for("evaluation_edit", eid=eid))
'''
),
(
'    lists = {"departments": "Подразделение", "employments": "Занятость", "funding_types": "Источник финансирования"}\n',
'    lists = {"departments": "Подразделение", "employments": "Занятость", "funding_types": "Источник финансирования", "employees": "ФИО работника"}\n'
)
]

for old, new in replacements:
    if old not in app:
        raise SystemExit("app patch target not found:\n" + old[:160])
    app = app.replace(old, new, 1)

# Managers must continue seeing/printing/exporting forms they themselves created after changing department.
forced = '''    if session.get("role") == "manager":
        f["department"] = session.get("department") or ""
'''
if app.count(forced) < 3:
    raise SystemExit("manager department filter targets not found")
app = app.replace(forced, "")

app_path.write_text(app, encoding="utf-8")

tpl = tpl_path.read_text(encoding="utf-8")
old = '''    <label>ФИО<input name="employee" value="{{ e.employee }}" required {% if not is_new and session.get('role')=='manager' and not manager_editable %}disabled{% endif %}></label>
    <label>Подразделение<select name="department" {% if session.get('role')=='manager' or (not is_new and session.get('role')=='manager' and not manager_editable) %}disabled{% endif %}>{% for dep in data.departments %}<option value="{{ dep }}" {% if e.department==dep %}selected{% endif %}>{{ dep }}</option>{% endfor %}</select></label>
'''
new = '''    <label>Быстрый поиск ФИО<input type="search" id="employee_search" placeholder="Начните вводить ФИО" autocomplete="off" {% if not is_new and session.get('role')=='manager' and not manager_editable %}disabled{% endif %}></label>
    <label>ФИО<select name="employee" id="employee_select" required {% if not is_new and session.get('role')=='manager' and not manager_editable %}disabled{% endif %}>
      <option value="">— выберите работника —</option>
      {% for employee in data.employees %}<option value="{{ employee }}" {% if e.employee==employee %}selected{% endif %}>{{ employee }}</option>{% endfor %}
      {% if e.employee and e.employee not in data.employees %}<option value="{{ e.employee }}" selected>{{ e.employee }}</option>{% endif %}
    </select></label>
    <label>Подразделение<select name="department" {% if not is_new and session.get('role')=='manager' and not manager_editable %}disabled{% endif %}>{% for dep in data.departments %}<option value="{{ dep }}" {% if e.department==dep %}selected{% endif %}>{{ dep }}</option>{% endfor %}</select></label>
'''
if old not in tpl:
    raise SystemExit("evaluation form employee/department block not found")
tpl = tpl.replace(old, new, 1)

script = '''
<script>
(function () {
  const search = document.getElementById('employee_search');
  const select = document.getElementById('employee_select');
  if (!search || !select) return;
  const source = Array.from(select.options).map(o => ({value: o.value, text: o.text, selected: o.selected}));
  search.addEventListener('input', function () {
    const q = search.value.trim().toLowerCase();
    const current = select.value;
    select.innerHTML = '';
    source.forEach(function (item, index) {
      if (index === 0 || !q || item.text.toLowerCase().includes(q) || item.value === current) {
        const option = document.createElement('option');
        option.value = item.value;
        option.textContent = item.text;
        if (item.value === current) option.selected = true;
        select.appendChild(option);
      }
    });
  });
})();
</script>
'''
if "{% endblock %}" not in tpl:
    raise SystemExit("evaluation form endblock not found")
tpl = tpl.replace("{% endblock %}", script + "{% endblock %}", 1)
tpl_path.write_text(tpl, encoding="utf-8")

admin = admin_path.read_text(encoding="utf-8")
needle = '''<div class="admin-grid">
<section class="card"><h2>Подразделения</h2>{% set target='departments' %}{% set items=data.departments %}{% include '_simple_list.html' %}</section>
'''
insert = '''<section class="card"><h2>ФИО работников</h2><p class="hint">Справочник используется Руководителем при выборе работника в анкете.</p>{% set target='employees' %}{% set items=data.employees %}{% include '_simple_list.html' %}</section>

<div class="admin-grid">
<section class="card"><h2>Подразделения</h2>{% set target='departments' %}{% set items=data.departments %}{% include '_simple_list.html' %}</section>
'''
if needle not in admin:
    raise SystemExit("admin insertion target not found")
admin = admin.replace(needle, insert, 1)
admin_path.write_text(admin, encoding="utf-8")

# Adapt smoke test to the new required employee directory and verify manager department override.
smoke_path = Path("src/test_smoke.py")
smoke = smoke_path.read_text(encoding="utf-8")
old = '''        d = gp.load_data()
        g1 = gp.find_group(d, gp.find_position(d, 1)['group_id'])
'''
new = '''        d = gp.load_data()
        d.setdefault('employees', []).append('Тестовый Работник')
        gp.save_data(d)
        d = gp.load_data()
        g1 = gp.find_group(d, gp.find_position(d, 1)['group_id'])
'''
if old not in smoke:
    raise SystemExit("smoke employee directory insertion target not found")
smoke = smoke.replace(old, new, 1)

old = """            'funding': 'ОМС',
            'plan': '182',
"""
new = """            'funding': 'ОМС',
            'department': 'Детское поликлиническое отделение',
            'plan': '182',
"""
if old not in smoke:
    raise SystemExit("smoke department field target not found")
smoke = smoke.replace(old, new, 1)

old = "        assert e['department'] == 'Поликлиническое отделение'\n"
new = """        assert e['department'] == 'Детское поликлиническое отделение'
        assert c.get(f'/evaluation/{eid}').status_code == 200
"""
if old not in smoke:
    raise SystemExit("smoke department assertion target not found")
smoke = smoke.replace(old, new, 1)

smoke_path.write_text(smoke, encoding="utf-8")

print("OK: employee directory + manager department override applied")
