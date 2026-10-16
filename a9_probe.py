import zipfile, re, itertools, sys
sys.path.insert(0, r"D:\Semester 07\Projects\copcat")
from copcat.normal import fingerprint, containment

zf = zipfile.ZipFile(r"C:\Users\Talha Qureshi\Downloads\assignment9\a9.zip")

def cpp_tokens(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)      # block comments
    src = re.sub(r"^[ \t]*#.*$", " ", src, flags=re.M)     # preprocessor
    src = re.sub(r"//.*", " ", src)                        # line comments
    src = re.sub(r'"(?:\\.|[^"\\])*"', " STR ", src)       # strings
    src = re.sub(r"'(?:\\.|[^'\\])*'", " CHR ", src)       # chars
    return re.findall(r"[A-Za-z_]\w*|\d+(?:\.\d+)?|\S", src)

files = {}
for n in zf.namelist():
    if n.lower().endswith(".cpp"):
        roll = re.search(r"(bscs\d+)", n, re.I)
        task = re.search(r"task(\d+)", n, re.I)
        if roll and task:
            files.setdefault("task" + task.group(1), {})[
                roll.group(1).lower()] = cpp_tokens(
                    zf.read(n).decode("utf-8", "replace"))

for task, subs in sorted(files.items()):
    scores = []
    for (ra, ta), (rb, tb) in itertools.combinations(subs.items(), 2):
        if len(ta) < 30 or len(tb) < 30:
            continue
        s = max(containment(fingerprint(ta, 8, 4), fingerprint(tb, 8, 4)),
                containment(fingerprint(tb, 8, 4), fingerprint(ta, 8, 4)))
        scores.append((round(100 * s, 1), ra, rb))
    scores.sort(reverse=True)
    print("=== {} ({} students, {} pairs) - top 8 token containment:".format(
        task, len(subs), len(scores)))
    for s, a, b in scores[:8]:
        print("    {:5.1f}%  {} vs {}".format(s, a, b))
    print("    pairs >= 45%:", sum(1 for s, _a, _b in scores if s >= 45))
    print()
