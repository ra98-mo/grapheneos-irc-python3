"use strict";
const $ = (id) => document.getElementById(id);
let token = null, nick = "", current = "", es = null;
const bufs = {};
const unread = {};
const names = {};

function buf(t) { return bufs[t] || (bufs[t] = []); }
function add(t, line) {
  buf(t).push(line);
  if (buf(t).length > 300) buf(t).shift();
  if (t === current) render1(line); else { unread[t] = true; tabs(); }
}
function render1(l) {
  const d = document.createElement("div");
  d.className = "m";
  const ts = document.createElement("span");
  ts.className = "t";
  ts.textContent = new Date(l.ts * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
  d.appendChild(ts);
  const body = document.createElement("span");
  if (l.nick) {
    const n = document.createElement("span");
    n.className = "n"; n.textContent = l.action ? "* " + l.nick + " " : "<" + l.nick + "> ";
    d.appendChild(n); body.textContent = l.text;
  } else { body.className = "s"; body.textContent = l.text; }
  d.appendChild(body);
  const log = $("log");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
  log.appendChild(d);
  if (atBottom) log.scrollTop = log.scrollHeight;
}
function msgLine(ev, text) {
  const a = text.startsWith("\x01ACTION ");
  return {ts: ev.ts, nick: ev.nick, text: a ? text.slice(8) : text, action: a};
}
function tabs() {
  const ul = $("tabs"); ul.textContent = "";
  Object.keys(bufs).forEach((t) => {
    const li = document.createElement("li");
    li.textContent = t + (unread[t] ? " •" : "");
    if (t === current) li.className = "active";
    li.onclick = () => { switchTo(t); $("side").classList.remove("open"); };
    ul.appendChild(li);
  });
}
function users() {
  const ul = $("users"); ul.textContent = "";
  (names[current] || []).forEach((u) => {
    const li = document.createElement("li");
    li.textContent = u;
    li.onclick = () => { if (u !== nick) { switchTo(u); $("side").classList.remove("open"); } };
    ul.appendChild(li);
  });
}
function switchTo(t) {
  current = t; buf(t); unread[t] = false;
  $("title").textContent = t;
  $("log").textContent = "";
  buf(t).forEach(render1);
  $("log").scrollTop = $("log").scrollHeight;
  tabs(); users();
}
function sys(text) { add(current || "*status*", {ts: Date.now() / 1000, text}); }

function onEvent(ev) {
  switch (ev.type) {
    case "welcome": nick = ev.nick; buf("*status*"); switchTo("*status*"); sys("Connected as " + nick + ". Try /join #lobby or /help"); break;
    case "joined":
      buf(ev.channel); ev.history.forEach((h) => buf(ev.channel).push(msgLine(h, h.text)));
      add(ev.channel, {ts: ev.ts, text: "Joined " + ev.channel + (ev.topic ? " - " + ev.topic : "")});
      switchTo(ev.channel); break;
    case "parted": delete bufs[ev.channel]; delete names[ev.channel];
      switchTo(Object.keys(bufs)[0] || "*status*"); break;
    case "join": if (ev.nick !== nick) add(ev.channel, {ts: ev.ts, text: ev.nick + " joined"}); break;
    case "part": case "quit": add(ev.channel, {ts: ev.ts, text: ev.nick + " left"}); break;
    case "names": names[ev.channel] = ev.users; if (ev.channel === current) users(); break;
    case "message": add(ev.target, msgLine(ev, ev.text)); break;
    case "pm": { const peer = ev.nick === nick ? ev.to : ev.nick; add(peer, msgLine(ev, ev.text)); break; }
    case "topic": add(ev.channel, {ts: ev.ts, text: ev.nick + " set topic: " + ev.topic}); break;
    case "nick":
      if (ev.mine) { nick = ev.new; sys("You are now " + nick); }
      else Object.keys(names).forEach((c) => { if (names[c].includes(ev.old)) add(c, {ts: ev.ts, text: ev.old + " is now " + ev.new}); });
      break;
    case "info": sys(ev.text); break;
  }
}
async function post(path, data) {
  const r = await fetch(path, {method: "POST", body: JSON.stringify(data)});
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || "error");
  return j;
}
$("login").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const j = await post("/api/connect", {nick: $("nick").value.trim()});
    token = j.token;
    $("login").hidden = true; $("app").hidden = false;
    es = new EventSource("/api/events?token=" + encodeURIComponent(token));
    es.onmessage = (m) => onEvent(JSON.parse(m.data));
    es.onerror = () => { if (es.readyState === 2) sys("Disconnected. Reload to reconnect."); };
  } catch (err) { $("loginerr").textContent = err.message; }
};
$("send").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("text").value;
  if (!text.trim()) return;
  $("text").value = "";
  try { await post("/api/send", {token, target: current.startsWith("*") ? "" : current, text}); }
  catch (err) { sys("Error: " + err.message); }
};
$("menu").onclick = () => $("side").classList.toggle("open");
window.addEventListener("pagehide", () => { if (token) navigator.sendBeacon("/api/disconnect", JSON.stringify({token})); });
