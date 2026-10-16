"""C++ audit golden test: a renamed copy is flagged, an unrelated solution
is clean, and mixed Python+C++ batches audit without error."""

from copcat.channels import build_submission
from copcat.models import AuditConfig
from copcat.audit import run_audit

A_CPP = """#include <iostream>
#include <string>
using namespace std;
// computes the sum of array elements
int arraySum(int arr[], int n) {
    int total = 0;
    for (int i = 0; i < n; i++) {
        total += arr[i];
    }
    return total;
}
// largest element in the array
int arrayMax(int arr[], int n) {
    int best = arr[0];
    for (int i = 1; i < n; i++) {
        if (arr[i] > best) {
            best = arr[i];
        }
    }
    return best;
}
// linear search: index of key or -1
int arrayFind(int arr[], int n, int key) {
    for (int i = 0; i < n; i++) {
        if (arr[i] == key) {
            return i;
        }
    }
    return -1;
}
int main() {
    int data[5] = {4, 8, 15, 16, 23};
    cout << arraySum(data, 5) << endl;
    cout << arrayMax(data, 5) << endl;
    cout << arrayFind(data, 5, 15) << endl;
    return 0;
}
"""

# same logic, identifiers renamed, comments rewritten
B_CPP = """#include <iostream>
#include <string>
using namespace std;
// adds every element of the array
int arraySum(int values[], int count) {
    int sum = 0;
    for (int idx = 0; idx < count; idx++) {
        sum += values[idx];
    }
    return sum;
}
// biggest element of the array
int arrayMax(int values[], int count) {
    int winner = values[0];
    for (int idx = 1; idx < count; idx++) {
        if (values[idx] > winner) {
            winner = values[idx];
        }
    }
    return winner;
}
// linear search: position of key or -1
int arrayFind(int values[], int count, int key) {
    for (int idx = 0; idx < count; idx++) {
        if (values[idx] == key) {
            return idx;
        }
    }
    return -1;
}
int main() {
    int nums[5] = {4, 8, 15, 16, 23};
    cout << arraySum(nums, 5) << endl;
    cout << arrayMax(nums, 5) << endl;
    cout << arrayFind(nums, 5, 15) << endl;
    return 0;
}
"""

C_CPP = """#include <iostream>
#include <string>
using namespace std;
// reverse a word character by character
string reverseWord(string word) {
    string rev = "";
    for (int k = word.size() - 1; k >= 0; k--) {
        rev += word[k];
    }
    return rev;
}
// count vowels inside a word
int countVowels(string word) {
    int count = 0;
    for (int k = 0; k < word.size(); k++) {
        char c = word[k];
        if (c == 'a' || c == 'e' || c == 'i' || c == 'o' || c == 'u') {
            count++;
        }
    }
    return count;
}
// shout a word in uppercase
string shoutWord(string word) {
    string loud = "";
    for (int k = 0; k < word.size(); k++) {
        loud += (word[k] >= 'a' && word[k] <= 'z') ? word[k] - 32 : word[k];
    }
    return loud;
}
int main() {
    cout << reverseWord("copcat") << endl;
    cout << countVowels("copcat") << endl;
    cout << shoutWord("copcat") << endl;
    return 0;
}
"""

PY_SRC = "print(sum([1, 2, 3]))\n"


def _subs(tmp_path):
    cfg = AuditConfig()
    out = []
    for name, src in (("ali_bscs30101_a.cpp", A_CPP),
                      ("sara_bscs30102_b.cpp", B_CPP),
                      ("omar_bscs30103_c.cpp", C_CPP),
                      ("zain_bscs30104_p.py", PY_SRC)):
        p = tmp_path / name
        p.write_text(src, encoding="utf-8")
        out.append(build_submission(name.rsplit(".", 1)[0].split("_")[-1],
                                    name, str(p), src, cfg))
    return cfg, out


def test_channel_dispatch_and_lang(tmp_path):
    _cfg, subs = _subs(tmp_path)
    by_name = {s.filename: s for s in subs}
    assert by_name["ali_bscs30101_a.cpp"].lang == "cpp"
    assert by_name["zain_bscs30104_p.py"].lang == "python"
    cpp = by_name["ali_bscs30101_a.cpp"]
    assert cpp.tokens and "arraySum" in cpp.tokens
    assert cpp.canonical_tokens.count("ID") >= 4       # identifiers collapsed


def test_cpp_audit_flags_renamed_copy(tmp_path):
    tmp = tmp_path / "batch"
    tmp.mkdir()
    for name, src in (("ali_bscs30101_a.cpp", A_CPP),
                      ("sara_bscs30102_b.cpp", B_CPP),
                      ("omar_bscs30103_c.cpp", C_CPP),
                      ("zain_bscs30104_p.py", PY_SRC)):
        (tmp / name).write_text(src, encoding="utf-8")
    pairs = run_audit(str(tmp), AuditConfig(), str(tmp_path / "out"),
                      workers=1)
    by_pair = {(p.roll_a, p.roll_b): p for p in pairs}
    ab = by_pair.get(("BSCS30101", "BSCS30102")) or \
        by_pair.get(("BSCS30102", "BSCS30101"))
    assert ab is not None, "renamed copy pair missing from results"
    assert ab.scores["ast"][0] >= 0.6, "rename-invariant channel missed the copy"
    assert ab.blended >= 0.45 and ab.flag != "CLEAN"

    ac = by_pair.get(("BSCS30101", "BSCS30103")) or \
        by_pair.get(("BSCS30103", "BSCS30101"))
    bc = by_pair.get(("BSCS30102", "BSCS30103")) or \
        by_pair.get(("BSCS30103", "BSCS30102"))
    assert ac.blended < 0.45 and bc.blended < 0.45
    assert ac.flag == "CLEAN" and bc.flag == "CLEAN"
