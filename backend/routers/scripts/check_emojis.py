import os
import re
import sqlite3

ROOT = os.getcwd()
SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", ".pytest_cache"}
TEXT_EXT = (".py", ".js", ".html", ".css", ".md", ".json", ".txt")
DB_EXT = (".db", ".sqlite", ".sqlite3")
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]")


def codes(text):
    return " ".join("U+%04X" % ord(c) for c in EMOJI.findall(text))


found = 0

print("== FILES ==")
for folder, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for name in files:
        path = os.path.join(folder, name)
        if name.lower().endswith(TEXT_EXT):
            with open(path, encoding="utf-8", errors="ignore") as f:
                for number, line in enumerate(f, 1):
                    if EMOJI.search(line):
                        found += 1
                        print(os.path.relpath(path, ROOT) + " line " + str(number) + "  " + codes(line))

print("== DATABASE ==")
for folder, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for name in files:
        if not name.lower().endswith(DB_EXT):
            continue
        path = os.path.join(folder, name)
        print("Database file: " + os.path.relpath(path, ROOT))
        con = sqlite3.connect(path)
        tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        for table in tables:
            cols = [c[1] for c in con.execute('pragma table_info("%s")' % table)]
            for row in con.execute('select * from "%s"' % table):
                for col, val in zip(cols, row):
                    if isinstance(val, str) and EMOJI.search(val):
                        found += 1
                        print("  table " + table + ", column " + col + ", first value " + ascii(row[0]) + "  " + codes(val))
            if "subject" in table.lower():
                print("  Rows in table " + table + ":")
                for row in con.execute('select * from "%s" limit 40' % table):
                    print("   ", ascii(row))
        con.close()

print("")
if found == 0:
    print("DONE: no emojis found.")
else:
    print("DONE: emojis found = " + str(found))