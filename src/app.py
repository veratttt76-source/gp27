from __future__ import annotations
import json, os
from datetime import datetime
from functools import wraps
from pathlib import Path
from uuid import uuid4
from flask import Flask, flash, redirect, render_template, request, send_file, session, url_for
from tempfile import NamedTemporaryFile
from openpyxl import Workbook
from werkzeug.security import check_password_hash, generate_password_hash

BASE=Path(__file__).resolve().parent
DATA=BASE/"stim_bonus_data_v5.json"
HIDDEN=BASE/"stim_bonus_hidden_v1.json"
app=Flask(__name__); app.secret_key=os.environ.get("GP27_SECRET_KEY","gp27-local-change-me")
DEFAULT={"users":[{"login":"admin","password_hash":generate_password_hash("admin"),"role":"admin","department_id":None},{"login":"manager","password_hash":generate_password_hash("manager"),"role":"manager","department_id":"dep-1"},{"login":"accountant","password_hash":generate_password_hash("accountant"),"role":"accountant","department_id":None}],"departments":[{"id":"dep-1","name":"Подразделение 1"}],"positions":[{"id":"pos-1","name":"Должность 1","criteria":[{"id":"c1","name":"Критерий 1","points":2}]}],"evaluations":[]}

def load_data():
    if not DATA.exists(): save_data(DEFAULT)
    return json.loads(DATA.read_text(encoding="utf-8"))
def save_data(d): DATA.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
def hidden_ids():
    try: return set(json.loads(HIDDEN.read_text(encoding="utf-8"))) if HIDDEN.exists() else set()
    except Exception: return set()
def save_hidden(v): HIDDEN.write_text(json.dumps(sorted(v),ensure_ascii=False,indent=2),encoding="utf-8")
def auth(fn):
    @wraps(fn)
    def w(*a,**k):
        return fn(*a,**k) if session.get("role") else redirect(url_for("login"))
    return w
def roles(*ok):
    def deco(fn):
        @wraps(fn)
        def w(*a,**k):
            return fn(*a,**k) if session.get("role") in ok else redirect(url_for("dashboard"))
        return w
    return deco
def month_now(): return datetime.now().strftime("%Y-%m")
def status_name(s): return {"draft":"Черновик","submitted":"На проверке","returned":"На доработке","approved":"Утверждено"}.get(s,s)
def employment_name(s): return {"main":"Основная","part":"Совместительство"}.get(s,s)
app.jinja_env.globals.update(status_name=status_name,employment_name=employment_name)

def enrich(e,d):
    x=dict(e); x["department"]=next((z["name"] for z in d["departments"] if str(z["id"])==str(e.get("department_id"))),""); x["position"]=next((z["name"] for z in d["positions"] if str(z["id"])==str(e.get("position_id"))),"")
    x["total_points"]=sum(float(v or 0) for v in e.get("scores",{}).values()); p=float(e.get("planned_hours") or 0); f=float(e.get("actual_hours") or 0); x["normalized_points"]=x["total_points"]/(p*f) if p and f else 0
    price=e.get("point_price"); x["bonus_amount"]=x["normalized_points"]*float(price) if price not in (None,"") else None
    return x
def visible(d,m=None,dep=None,admin_can_see_hidden=True):
    h=hidden_ids(); out=[]
    for e in d["evaluations"]:
        if m and e.get("month")!=m: continue
        if dep and str(e.get("department_id"))!=str(dep): continue
        if session.get("role")=="manager" and str(e.get("department_id"))!=str(session.get("department_id")): continue
        if e["id"] in h and not(admin_can_see_hidden and session.get("role")=="admin"): continue
        out.append(enrich(e,d))
    return out
def report_rows(d,m,dep=None):
    h=hidden_ids()
    return [r for r in visible(d,m,dep,False) if r["id"] not in h]

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        d=load_data(); u=next((x for x in d["users"] if x["login"]==request.form.get("login")),None)
        if u and check_password_hash(u["password_hash"],request.form.get("password","")):
            session.clear(); session.update(login=u["login"],role=u["role"],department_id=u.get("department_id")); return redirect(url_for("dashboard"))
        flash("Неверный логин или пароль")
    return render_template("login.html")
@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/")
@auth
def dashboard():
    d=load_data(); m=request.args.get("month") or month_now(); dep=request.args.get("department_id") or None; rows=visible(d,m,dep); q=(request.args.get("q") or "").strip().lower()
    if q: rows=[r for r in rows if q in r["employee_name"].lower()]
    totals=report_rows(d,m,dep); summary={"cnt":len(totals),"points":sum(r["total_points"] for r in totals),"bonus":sum(r["bonus_amount"] or 0 for r in totals)}
    return render_template("dashboard.html",rows=rows,summary=summary,month=m,deps=d["departments"],hidden=hidden_ids(),q=q)

@app.route("/evaluation/new",methods=["GET","POST"])
@auth
@roles("manager","admin")
def new_eval():
    d=load_data()
    if request.method=="POST":
        pos=next(x for x in d["positions"] if x["id"]==request.form["position_id"])
        dep_id=session.get("department_id") if session["role"]=="manager" else request.form["department_id"]
        e={"id":uuid4().hex,"month":request.form["month"],"department_id":dep_id,"employee_name":request.form["employee_name"].strip(),"position_id":request.form["position_id"],"employment_type":request.form["employment_type"],"planned_hours":float(request.form["planned_hours"] or 0),"actual_hours":float(request.form["actual_hours"] or 0),"scores":{c["id"]:int(request.form.get("score_"+c["id"],0)) for c in pos["criteria"]},"status":"draft","return_comment":"","point_price":None}
        d["evaluations"].append(e); save_data(d); return redirect(url_for("edit_eval",eid=e["id"]))
    return render_template("evaluation.html",e=None,raw=None,data=d,month=request.args.get("month") or month_now(),is_hidden=False)

@app.route("/evaluation/<eid>",methods=["GET","POST"])
@auth
def edit_eval(eid):
    d=load_data(); e=next((x for x in d["evaluations"] if x["id"]==eid),None)
    if not e: return "Не найдено",404
    if session["role"]=="manager" and str(e["department_id"])!=str(session.get("department_id")): return "Нет доступа",403
    if request.method=="POST":
        a=request.form.get("action","save")
        can_edit_form = session["role"] in ("accountant","admin") or e.get("status") in ("draft","returned")
        if a=="delete" and session["role"]=="admin":
            d["evaluations"]=[x for x in d["evaluations"] if x["id"]!=eid]; save_data(d); h=hidden_ids(); h.discard(eid); save_hidden(h); return redirect(url_for("dashboard"))
        if a=="hide" and session["role"]=="admin":
            h=hidden_ids(); h.remove(eid) if eid in h else h.add(eid); save_hidden(h); return redirect(url_for("edit_eval",eid=eid))
        if a=="return" and session["role"] in ("accountant","admin"): e["status"]="returned"; e["return_comment"]=request.form.get("return_comment","").strip()
        elif a=="approve" and session["role"] in ("accountant","admin"): e["status"]="approved"
        elif a=="submit" and session["role"] in ("manager","admin"): e["status"]="submitted"
        if can_edit_form:
            for k in ("employee_name","employment_type","position_id"):
                if k in request.form: e[k]=request.form[k]
            for k in ("planned_hours","actual_hours"):
                if k in request.form: e[k]=float(request.form[k] or 0)
        pos=next((x for x in d["positions"] if x["id"]==e["position_id"]),None)
        if pos and can_edit_form: e["scores"]={c["id"]:int(request.form.get("score_"+c["id"],e.get("scores",{}).get(c["id"],0))) for c in pos["criteria"]}
        if session["role"] in ("accountant","admin") and "point_price" in request.form: e["point_price"]=float(request.form["point_price"] or 0)
        save_data(d); flash("Сохранено")
    return render_template("evaluation.html",e=enrich(e,d),raw=e,data=d,month=e["month"],is_hidden=eid in hidden_ids())

@app.route("/accounting")
@auth
@roles("accountant","admin")
def accounting():
    d=load_data(); m=request.args.get("month") or month_now(); dep=request.args.get("department_id") or None
    return render_template("accounting.html",rows=visible(d,m,dep),month=m,dep=dep,deps=d["departments"])
@app.post("/accounting/bulk")
@auth
@roles("accountant","admin")
def accounting_bulk():
    d=load_data()
    for e in d["evaluations"]:
        k="price_"+e["id"]
        if k in request.form:
            try: e["point_price"]=float(request.form[k].replace(",","."))
            except ValueError: pass
            if e["status"]=="submitted": e["status"]="approved"
    save_data(d); return redirect(url_for("accounting",month=request.form.get("month"),department_id=request.form.get("department_id")))

def xlsx(rows,title):
    wb=Workbook(); ws=wb.active; ws.title="Ведомость"; ws.append([title]); ws.append(["ФИО","Должность","План","Факт","Баллы","Расчётный балл","Цена балла","Выплата"])
    for r in rows: ws.append([r["employee_name"],r["position"],r["planned_hours"],r["actual_hours"],r["total_points"],r["normalized_points"],r.get("point_price"),r.get("bonus_amount")])
    tmp=NamedTemporaryFile(prefix="gp27_",suffix=".xlsx",delete=False); tmp.close(); wb.save(tmp.name); return send_file(tmp.name,as_attachment=True,download_name="gp27.xlsx")
@app.route("/export/manager.xlsx")
@auth
def export_manager_xlsx():
    d=load_data(); m=request.args.get("month") or month_now(); dep=session.get("department_id") if session["role"]=="manager" else None; return xlsx(report_rows(d,m,dep),"Ведомость ГП27")
@app.route("/export/accounting.xlsx")
@auth
@roles("accountant","admin")
def export_accounting_xlsx():
    d=load_data(); m=request.args.get("month") or month_now(); return xlsx(report_rows(d,m,request.args.get("department_id") or None),"Расчётная ведомость ГП27")
@app.route("/print/manager")
@auth
def print_manager():
    d=load_data(); m=request.args.get("month") or month_now(); dep=session.get("department_id") if session["role"]=="manager" else None; return render_template("print_manager.html",rows=report_rows(d,m,dep),month=m)
@app.route("/print/accounting")
@auth
@roles("accountant","admin")
def print_accounting():
    d=load_data(); m=request.args.get("month") or month_now(); return render_template("print_accounting.html",rows=report_rows(d,m,request.args.get("department_id") or None),month=m)
@app.route("/admin",methods=["GET","POST"])
@auth
@roles("admin")
def admin_panel():
    d=load_data()
    if request.method=="POST":
        action=request.form.get("action")
        if action=="add_department":
            name=request.form.get("name","").strip()
            if name: d["departments"].append({"id":"dep-"+uuid4().hex[:8],"name":name})
        elif action=="add_position":
            name=request.form.get("name","").strip()
            if name: d["positions"].append({"id":"pos-"+uuid4().hex[:8],"name":name,"criteria":[]})
        elif action=="add_criterion":
            p=next((x for x in d["positions"] if x["id"]==request.form.get("position_id")),None); name=request.form.get("name","").strip()
            if p and name: p["criteria"].append({"id":"c-"+uuid4().hex[:8],"name":name,"points":2})
        elif action=="edit_criterion":
            p=next((x for x in d["positions"] if x["id"]==request.form.get("position_id")),None); criterion=next((x for x in p["criteria"] if x["id"]==request.form.get("criterion_id")),None) if p else None
            if criterion:
                criterion["name"]=request.form.get("name",criterion["name"]).strip() or criterion["name"]
                try: criterion["points"]=float(request.form.get("points",criterion.get("points",2)))
                except ValueError: pass
        elif action=="delete_criterion":
            p=next((x for x in d["positions"] if x["id"]==request.form.get("position_id")),None)
            if p: p["criteria"]=[x for x in p["criteria"] if x["id"]!=request.form.get("criterion_id")]
        elif action=="add_user":
            login=request.form.get("login","").strip(); password=request.form.get("password",""); role=request.form.get("role")
            if login and password and role in ("manager","accountant","admin") and not any(x["login"]==login for x in d["users"]):
                d["users"].append({"login":login,"password_hash":generate_password_hash(password),"role":role,"department_id":request.form.get("department_id") or None})
        elif action=="reset_password":
            u=next((x for x in d["users"] if x["login"]==request.form.get("login")),None); password=request.form.get("password","")
            if u and password: u["password_hash"]=generate_password_hash(password)
        save_data(d); flash("Настройки сохранены"); return redirect(url_for("admin_panel"))
    return render_template("admin.html",data=d)

if __name__=="__main__": app.run(host="127.0.0.1",port=5000,debug=False)
