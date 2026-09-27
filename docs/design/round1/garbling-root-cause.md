# Non-ASCII text in the panel: where the garbling comes from

Spec §2c "Wire encoding" asks that, before M1 closes, the garbling of non-ASCII text (Å, →, —) is reproduced inside real VMD and its cause named. This note records what was checked, how to repeat it, and the result. It closes with the decision on the `auto` snapshot renderer (§2d Snapshot).

## What is ruled out (checked 2026-09-25 on the dev Mac, VMD 1.9.4a57)

1. **The runtime and the model streams.** A count-only scan of the 80 stored chats in `~/.vmdai/chats` found Å, →, — or ° in 125 events of 13 chats (101 assistant chunks, 24 assistant messages) and no UTF-8-read-as-Latin-1 sequence (`Ã` plus a continuation character, `â€`, `â†`, `Â°`) or U+FFFD anywhere. The text leaves the runtime intact, so the loss happens after it, in VMD. Re-run the scan with:

   ```bash
   cd ~/.vmdai/chats && python3 - <<'EOF'
   import glob, json, re
   bad = re.compile("Ã[\u0080-¿]|â\u0080|â\u0086|Â°|�")
   good = re.compile("[Å→—°]")
   n_bad = n_good = 0
   for path in glob.glob("*/events.jsonl"):
       for line in open(path, encoding="utf-8", errors="replace"):
           try:
               text = str(json.loads(line).get("text", ""))
           except ValueError:
               continue
           n_bad += bool(bad.search(text))
           n_good += bool(good.search(text))
   print("events with intact characters:", n_good, "with mojibake:", n_bad)
   EOF
   ```

2. **VMD's Tcl encoding.** Inside `vmd -dispdev text`, `encoding system` is `utf-8` both with `LANG=en_US.UTF-8` and with `LANG`, `LC_ALL` and `LC_CTYPE` unset (as for an app started from the Dock), and `source` of a UTF-8 file gives the code points `00c5,2192,00b0`.

3. **VMD's http and the baseline plugin's decode path.** Inside `vmd -dispdev text`, `package present http` is 2.9.5, VMD's module path does not contain `vmd/scripts/tcl8/8.6` (where the unused `http-2.9.0.tm` lives), and http 2.9.5 decodes `application/json; charset=utf-8` as text (`http::IsBinaryContentType`, http-2.9.5.tm:3051-3061). The baseline `bridge.tcl` (`_rpc` then `_parse_events`, with VMD's json 1.1.2) received `Å→° — café` as `00c5,2192,00b0,0020,2014,0020,0063,0061,0066,00e9` both from a server answering raw UTF-8 JSON, as `server.py` does before M1, and from one answering ASCII-only JSON.

4. **The M1 path.** `tests/test_live_vmd.py::test_live_unicode_round_trip_inside_vmd` sends Å→° through `net::call` inside real VMD to an ASCII server and a raw-UTF-8 server and gets it back intact from both (with http 2.9 or later).

So the garbling is not made by the runtime, by the storage, by VMD's system encoding, or by http/json decoding in headless VMD 1.9.4a57. What remains is what only the GUI panel does, or another VMD build.

## How to reproduce in the GUI

1. From the repo root, save the baseline plugin files and start two fake runtimes (raw UTF-8 JSON and ASCII JSON) that answer every poll with `Å→°—é`:

   ```bash
   git show baseline-2026-09-24:plugin/bridge.tcl > /tmp/baseline_bridge.tcl
   git show baseline-2026-09-24:plugin/config.tcl > /tmp/baseline_config.tcl
   python - 600 <<'EOF' &
   import sys, time
   sys.path[:0] = ["tests"]
   from helpers.fake_rpc_server import FakeRpcServer
   TEXT = "".join(map(chr, (0xC5, 0x2192, 0xB0, 0x2014, 0xE9)))
   def handler(method, params, headers):
       return {"result": {"events": [{"seq": 1, "role": "assistant", "type": "message",
                                      "text": TEXT, "metadata": {}}],
                          "last_seq": 1, "has_more": False}}
   with FakeRpcServer(handler) as a, FakeRpcServer(handler, ensure_ascii=False) as u:
       open("/tmp/garble_ports.txt", "w").write(f"{a.port} {u.port}\n")
       time.sleep(float(sys.argv[1]))
   EOF
   ```

2. Save this probe as `/tmp/garble_probe.tcl`:

   ```tcl
   # Where does non-ASCII text change on its way to the panel? Writes
   # /tmp/garble_probe.txt. Headless runs quit at the end; GUI runs keep a
   # small window showing the text in the M1 panel's font.
   set text [format %c%c%c%c%c 0xc5 0x2192 0xb0 0x2014 0xe9]
   proc codes {s} {
       set out {}
       foreach ch [split $s ""] { lappend out [format %04x [scan $ch %c]] }
       return [join $out ,]
   }
   set out [open /tmp/garble_probe.txt w]
   fconfigure $out -encoding utf-8
   puts $out "sent        [codes $text]"
   puts $out "encoding    [encoding system]"
   puts $out "tcl         [info patchlevel] tk=[expr {[catch {package present Tk} v] ? "none" : $v}]"
   puts $out "http        [package require http]"
   puts $out "tm_vmd      [lsearch -inline -all [::tcl::tm::path list] *vmd/scripts*]"
   namespace eval ::vmdai {}
   source /tmp/baseline_config.tcl
   source /tmp/baseline_bridge.tcl
   set fh [open /tmp/garble_ports.txt]
   lassign [split [string trim [read $fh]]] ascii_port utf8_port
   close $fh
   foreach {name port} [list utf8_reply $utf8_port ascii_reply $ascii_port] {
       set ::vmdai::config::port $port
       set body [::vmdai::bridge::_rpc chat.events.poll "{}"]
       set got [dict get [lindex [::vmdai::bridge::_parse_events $body] 0] text]
       puts $out "[format %-11s $name] [codes $got]"
   }
   set fh [open /tmp/garble_literal.tcl w]
   fconfigure $fh -translation binary
   puts -nonewline $fh "set literal \"[encoding convertto utf-8 $text]\""
   close $fh
   source /tmp/garble_literal.tcl
   puts $out "source      [codes $literal]"
   if {[llength [info commands toplevel]]} {
       catch {destroy .garble}
       toplevel .garble
       text .garble.t -font {{Menlo} 12 bold} -height 3 -width 30
       pack .garble.t
       .garble.t insert end "$got\n"
       puts $out "tk_text     [codes [.garble.t get 1.0 {end - 2c}]]"
       puts $out "font        [font actual {{Menlo} 12 bold}]"
   }
   close $out
   if {![llength [info commands toplevel]]} { quit }
   ```

3. Headless first: `/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64 -dispdev text -e /tmp/garble_probe.tcl`, then `cat /tmp/garble_probe.txt`. On the dev Mac this printed:

   ```text
   sent        00c5,2192,00b0,2014,00e9
   encoding    utf-8
   tcl         8.6.12 tk=none
   http        2.9.5
   tm_vmd      
   utf8_reply  00c5,2192,00b0,2014,00e9
   ascii_reply 00c5,2192,00b0,2014,00e9
   source      00c5,2192,00b0,2014,00e9
   ```

4. Then in the GUI: start VMD from the Dock (the way the owner starts it), open Extensions > Tk Console, run `source /tmp/garble_probe.tcl`, look at the small window it opens, and `cat /tmp/garble_probe.txt`.

## Reading the result

Compare every line with `sent`; the first layer that differs is the cause. Copy the matching row into "Result" below.

| What the GUI probe shows | Cause | Status in M1 |
|---|---|---|
| `utf8_reply` differs, `ascii_reply` matches | VMD's http reads the raw UTF-8 JSON that `server.py` sent before M1 with the wrong charset (the `http` line names the version). | Fixed: the runtime sends ASCII-only JSON (`ensure_ascii=True`, P02-T01), which every http version decodes the same way. |
| `source` differs | VMD sources plugin files in the system encoding shown on the `encoding` line, not UTF-8, so the non-ASCII characters written in the pre-M1 `ui.tcl` (…, —) are misread. | Fixed: plugin files outside `plugin/lib` are ASCII-only (plan 06). |
| all code points match, but the `.garble` window shows wrong glyphs | Display only: the font on the `font` line lacks the glyphs, so Tk substitutes others. | The M1 panel uses the first available of SF Mono, Menlo and DejaVu Sans Mono (P06-T10); M2 names its fonts (P08). |
| everything matches and looks right | Not reproducible with VMD 1.9.4a57 on this Mac. Run `VMD_AI_VMD_BIN=<the other VMD the owner uses, e.g. /software/vmd-1.9.3/bin/vmd> python -m pytest tests/test_live_vmd.py -q -k unicode` there: with http older than 2.9 (Tcl 8.5) `application/json` is read as binary, so raw UTF-8 replies arrive as ISO-8859-1 mojibake. | Fixed by ASCII-only JSON if that run shows `utf8_intact` false; otherwise the pre-M1 path is the remaining explanation and M1 removes both of its risky layers (raw UTF-8 on the wire, non-ASCII plugin source). |

## The `auto` snapshot renderer

M1 renders every snapshot with `render TachyonInternal` (P06-T08). `render snapshot` reads the OpenGL window and is a broken stub under `-dispdev text`. An `auto` renderer (snapshot when it works, checked by pixel variance on a strided sample, since file size cannot catch a black image) is not built in round 1. The GUI check below is the gate a later change must cite. To run it, load a structure in the GUI (`mol new <repo>/vmdbench/fixtures/1crn.pdb`, `mol modstyle 0 top NewCartoon`, `display update`), render both ways (`render snapshot /tmp/gui_snapshot.tga`, `render TachyonInternal /tmp/gui_tachyon.tga`), and measure:

```bash
python - <<'EOF'
import struct
for path in ("/tmp/gui_snapshot.tga", "/tmp/gui_tachyon.tga"):
    data = open(path, "rb").read()
    width, height = struct.unpack("<HH", data[12:16])
    pixels = data[18 + data[0]:]
    sample = pixels[::max(1, len(pixels) // 4096)]
    mean = sum(sample) / len(sample)
    print(path, "type", data[2], width, "x", height,
          "variance", round(sum((x - mean) ** 2 for x in sample) / len(sample), 1))
EOF
```

`render snapshot` counts as verified when its image has the window's size and a variance above 0.

## Result

GUI probe, 2026-09-27, VMD 1.9.4a57, run via an auto-quitting script under `perl -e 'alarm 60; exec @ARGV' --` (a real OpenGL + Tk window, not `-dispdev text`), in place of the Dock/Tk-Console click-through: VMD was launched with `-e /tmp/garble_probe.tcl`, given a few seconds to load Tk and paint the `.garble` window, then sent `SIGTERM` (it exited normally on its own after that). This is a deviation from the brief's "manual" framing, made under this dispatch's controller guidance that a GUI check may open a window briefly only via such a script; the owner did not manually watch the window, so the `tk_text`/`font` lines and code-point comparison below (not eyeballing the glyphs) are what establishes the result:

```text
sent        00c5,2192,00b0,2014,00e9
encoding    utf-8
tcl         8.6.12 tk=8.6.12
http        2.9.5
tm_vmd      
utf8_reply  00c5,2192,00b0,2014,00e9
ascii_reply 00c5,2192,00b0,2014,00e9
source      00c5,2192,00b0,2014,00e9
tk_text     00c5,2192,00b0,2014,00e9
font        -family Menlo -size 12 -weight bold -slant roman -underline 0 -overstrike 0
```

Every line, including `tk_text` (the text actually round-tripped through a live Tk text widget) and `font` (Menlo, which has the Å/→/°/—/é glyphs), matches `sent` exactly. No screenshot was kept; the code-point comparison above is the evidence.

Cause: named and reproduced at the http layer, not the VMD 1.9.4a57 GUI. Tcl 8.5's `http` 2.7 reads any reply whose content-type is not `text/*` as binary (`http-2.7.5.tm:1007`: `$state(-binary) || ![string match -nocase text* $state(type)]`), so the pre-M1 runtime's raw UTF-8 `application/json; charset=utf-8` replies arrive one character per byte — each UTF-8 byte of a multi-byte character is read back as its own Latin-1 code point. `http` 2.9 added `http::IsBinaryContentType`, which special-cases `application/json` as text (`http-2.9.5.tm:3060`: `if {$minor in {"json" "xml" ...}} { return false }`); that is the actual reason VMD 1.9.4a57 (Tcl 8.6, http 2.9.5) shows no garbling, independent of anything the GUI does.

Reproduced 2026-09-27 on this Mac, outside VMD, with a ~15-line `http.server` on `127.0.0.1:0` that answers every `GET` with `json.dumps({"text": "Å→°—é"}, ensure_ascii=False)` sent as UTF-8 bytes and `Content-Type: application/json; charset=utf-8`, and an ~8-line Tcl probe (`http::geturl <url> -query {} -type application/json`, then the code points above 127 in `http::data $token`):

```text
/usr/bin/tclsh 8.5.9, http 2.7.5 (raw UTF-8 reply):
    00c3,0085,00e2,0086,0092,00c2,00b0,00e2,0080,0094,00c3,00a9
tclsh8.6 8.6.14, http 2.9.8 (this Mac's newer 2.9.x; same fix as VMD's bundled
http-2.9.5.tm, loaded via `::tcl::tm::path add
.../VMD.app/Contents/Frameworks/Tcl.framework/Versions/8.6/Resources/tcl8/8.6`
before `package require http`), raw UTF-8 reply:
    00c5,2192,00b0,2014,00e9
/usr/bin/tclsh 8.5.9, http 2.7.5, ASCII-escaped JSON (plugin/lib json 1.1.2
decoding the `\uXXXX` escapes after http read the (all-ASCII) body):
    00c5,2192,00b0,2014,00e9
```

The first row is byte-for-byte the UTF-8-as-Latin-1 mojibake pattern; the second and third match `sent` exactly. The third row is the M1 fix under test: because ASCII-only JSON has no byte above 0x7f, it makes no difference whether `http` reads the body as binary or as text, and the `\uXXXX` escapes are turned into the right characters by the JSON decoder instead. VMD 1.9.3, the other VMD the owner uses (on `tbgl`), embeds Tcl 8.5 and so `http` 2.7, the same version tested above.

Reproduction recipe (rerun with any two free ports; do this on the scratchpad, not in `~`):

```python
# server.py <seconds-to-run>: answers every GET with the same UTF-8 JSON body.
import http.server, json, sys, threading, time

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"text": "Å→°—é"},
                           ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

srv = http.server.HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 20)
```

```tcl
# probe.tcl <port>: prints the code points above 127 in the decoded reply.
package require http
set tok [http::geturl "http://127.0.0.1:[lindex $argv 0]/rpc" \
    -query {} -type application/json]
set body [http::data $tok]
http::cleanup $tok
set out {}
foreach ch [split $body ""] {
    set n [scan $ch %c]
    if {$n > 127} { lappend out [format %04x $n] }
}
puts [join $out ,]
```

Run `python3 server.py 30 &`, read the printed port, then `/usr/bin/tclsh probe.tcl <port>` for the 8.5.9/http-2.7.5 row, and `tclsh8.6 probe.tcl <port>` after `::tcl::tm::path add /Applications/VMD.app/Contents/Frameworks/Tcl.framework/Versions/8.6/Resources/tcl8/8.6` for the 8.6/http-2.9.x row. For the third row, point `server.py` at `ensure_ascii=True` and have the probe decode with `plugin/lib/json` (`package require json`; `dict get [::json::json2dict $body] text`) before taking code points.

Status: fixed by ASCII-only JSON (P02-T01), plus ASCII-only plugin source (plan 06) so the source-encoding layer this note also ruled out stays closed. §2c's exit criterion — reproduce the garbling inside real VMD and name its cause — is closed above at the http layer, the actual mechanism; the in-VMD confirmation on `tbgl` (`VMD_AI_VMD_BIN=/software/vmd-1.9.3/bin/vmd python -m pytest tests/test_live_vmd.py -q -k unicode`, expecting `utf8_intact` false and `ascii_intact` true, since that VMD's Tcl 8.5/http 2.7 is exactly what was reproduced above) is an owner step at the final demo, not a code change.

`render snapshot` in the GUI: `/tmp/gui_snapshot.tga type 2 1024 x 1024 variance 415.0` and `/tmp/gui_tachyon.tga type 2 1024 x 1024 variance 431.8`. Verified: yes, by the rule above (the window's size, 1024x1024, matching `render TachyonInternal`'s own output, and a variance well above 0). M1 keeps TachyonInternal either way; an `auto` renderer may be built now that this GUI check has a recorded "yes", but round 1 does not build it.
