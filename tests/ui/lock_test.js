/* Lock-screen functional test: loads the real webapp.html into jsdom and
 * clicks/types through every interaction the owner reported broken. */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(path.join(
  __dirname, "..", "..", "copcat", "webapp.html"), "utf-8");

const requests = [];
const dom = new JSDOM(html, {
  runScripts: "dangerously",
  url: "http://localhost:8060/",
  beforeParse(window) {
    window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
    window.fetch = async (url, opts) => {
      requests.push({ url: String(url), method: (opts && opts.method) || "GET",
                      headers: (opts && opts.headers) || {},
                      body: opts && opts.body
                        ? new URLSearchParams(
                            typeof opts.body === "string"
                              ? opts.body : [...opts.body].map(
                                ([k, v]) => [k, String(v)])).toString()
                        : "" });
      const u = String(url);
      if (u.endsWith("/api/auth/mode"))
        return { ok: true, status: 200, json: async () => ({ mode: "code" }) };
      if (u.endsWith("/api/auth/request"))
        return { ok: true, status: 200, json: async () => ({ sent: true }) };
      if (u.endsWith("/api/auth/verify"))
        return { ok: true, status: 200, json: async () => ({ session: "tok.abc" }) };
      if (u.endsWith("/api/jobs") && (!opts || !opts.method))
        return { ok: true, status: 200, json: async () => ({ jobs: [] }) };
      if (u.endsWith("/api/stats"))
        return { ok: true, status: 200, json: async () => ({ jobs: 0, submissions: 0, needs_review: 0, graded: 0 }) };
      return { ok: true, status: 200, json: async () => ({}) };
    };
  },
});
const { window } = dom;
const { document } = window;

const errors = [];
window.addEventListener("error", e => errors.push(String(e.error || e.message)));

const results = [];
const check = (name, cond) => {
  results.push(`${cond ? "PASS" : "FAIL"}  ${name}`);
  if (!cond) process.exitCode = 1;
};
const visible = id => !document.getElementById(id).classList.contains("hidden");
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  await sleep(150);   // let boot fetch + handlers settle

  // 1. lock screen is shown in code mode, code entry is the default tab
  check("lock screen visible on load (code mode)",
    !document.getElementById("lock").classList.contains("hidden") &&
    document.getElementById("lock").offsetParent !== undefined);
  check("code entry visible by default", visible("codeEntry"));
  check("key entry hidden by default", !visible("keyEntry"));
  check("request link visible in code mode", visible("reqlink"));

  // 2. tab: Access key switches to the plain key input
  document.getElementById("tab_key").click();
  check("Access key tab switches to key entry", visible("keyEntry"));
  check("key entry is a plain input (no boxed row)",
    !!document.querySelector("#keyEntry > input#key_input"));
  check("code entry hidden while on key tab", !visible("codeEntry"));
  check("request link hidden on key tab", !visible("reqlink"));

  // 3. tab: back to Access code
  document.getElementById("tab_code").click();
  check("Access code tab switches back", visible("codeEntry") && !visible("keyEntry"));
  check("request link visible again", visible("reqlink"));

  // 4. request link opens the request panel and sends the note
  const link = document.querySelector("#reqlink a");
  link.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  check("request panel opens on link click", visible("reqpanel"));
  document.getElementById("req_note").value = "Talha — owner";
  document.getElementById("reqbtn").click();
  await sleep(80);
  const req = requests.find(r => r.url.endsWith("/api/auth/request"));
  check("request POST fired with note", !!req && req.body.includes("Talha"));
  check("success message shown", visible("reqmsg"));

  // 5. code boxes: typing auto-advances to the next box
  const boxes = [...document.querySelectorAll("#codeEntry input")];
  boxes.forEach(b => (b.value = ""));
  boxes[0].focus();
  boxes[0].value = "4";
  boxes[0].dispatchEvent(new window.Event("input", { bubbles: true }));
  check("typing a digit advances focus to box 2",
    document.activeElement === boxes[1]);
  for (let i = 1; i < 6; i++) {
    boxes[i].value = String(i);
    boxes[i].dispatchEvent(new window.Event("input", { bubbles: true }));
  }
  await sleep(60);

  // 6. six digits trigger verification and a session unlocks the workspace
  const verify = requests.find(r => r.url.endsWith("/api/auth/verify"));
  check("verify fired with the entered code", !!verify && verify.body.includes("code=412345"));
  await sleep(100);
  check("workspace unlocked after code", document.getElementById("app").classList.contains("on"));
  check("session persisted", window.localStorage.getItem("copcat_session") === "tok.abc");

  check("no runtime JS errors during the whole flow", errors.length === 0);
  if (errors.length) console.log("errors:", errors);

  console.log(results.join("\n"));
  window.close();
})().catch(e => { console.error("HARNESS ERROR", e); process.exit(1); });
