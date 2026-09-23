from pathlib import Path

path = Path("src/app.py")
text = path.read_text(encoding="utf-8")

old = '''        elif action == "approve" and role in ("economist", "admin") and e.get("status") in ("sent", "approved"):
            missing_special = validate_required_answers(d, e, include_special=True)
            if missing_special:
                flash(f"Нельзя утвердить: не заполнены критерии Приложения №25 ({len(missing_special)}).", "error")
            else:
                e["status"] = "approved"
                e["return_comment"] = ""
                recalc(e)
                audit(d, f"Анкета рассчитана и утверждена: {e['employee']}")
'''

new = '''        elif action == "approve" and role in ("economist", "admin") and e.get("status") in ("sent", "approved"):
            e["status"] = "approved"
            e["return_comment"] = ""
            recalc(e)
            audit(d, f"Анкета рассчитана и утверждена: {e['employee']}")
'''

if old not in text:
    raise SystemExit("Appendix 25 approval block not found; no changes made")

text = text.replace(old, new, 1)

forbidden = "Нельзя утвердить: не заполнены критерии Приложения №25"
if forbidden in text:
    raise SystemExit("Appendix 25 approval restriction still present")

path.write_text(text, encoding="utf-8")
print("OK: economist can approve without completing Appendix 25")
