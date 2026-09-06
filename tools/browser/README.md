# FoldGPT external HTTP(S) opener

`foldgpt-open.py` replaces only the guest `/usr/local/bin/xdg-open` adapter.
Keep Debian's real `/usr/bin/xdg-open` intact. HTTP(S) arguments go to Android's
abstract Unix socket `foldgpt-url-<Android UID>`, using one bounded UTF-8 JSON
request line `{"url":"https://example.com/"}`. Other inputs/options execute the
original `/usr/bin/xdg-open` with unchanged arguments and no shell. A recursion
guard fails explicitly if a fallback child calls this adapter again for a
non-HTTP(S) input. HTTP(S) errors never fall back to another launch mechanism.

Set **FOLDGPT_URL_UID** from the native app UID in the trusted guest environment.
Until that is wired, the helper also accepts the existing FOLDGPT_IME_UID.
Do not infer the native identity from PRoot's virtualized `getuid()`.

The Activity integration calls `FoldUrlBridge.get().attach(this)` in Activity
creation, `.resume(this)` after resume, `.pause(this)` before pause, and
`.detach(this)` during destruction. No manifest component is necessary: the
singleton owns its private socket for the lifetime of attached Activities.
`FoldRuntimeService` supplies the actual Android UID, and the authenticated
guest bundle includes the opener. The development deployment helper preserves
the previous adapter and refuses an unrecognized replacement target.

The Android side verifies kernel peer credentials against its own UID; Python
also verifies the server UID before sending the URL. The socket is abstract and
descriptors are CLOEXEC. **Same UID is not guest-process isolation**: any process
with this Android UID can request a link while the Activity is foreground. The
configured UID is routing, not a secret or a bearer token. There is no TCP server.
Such a process could also occupy an unused abstract socket name and impersonate
the endpoint; same-UID credentials do not authenticate the native supervisor
against guest processes sharing that UID.

Validation permits HTTP(S), ordinary ASCII DNS/punycode, strict IPv4 and IPv6,
and ports 1–65535. Paths/query/fragment can contain valid UTF-8 (canonicalized to
ASCII escapes). Credentials, encoded hostnames, IPv6 scopes, ambiguous numeric
hosts, raw whitespace/control characters, encoded controls/backslashes,
malformed UTF-8/escapes, and oversized URLs are rejected. DNS name resolution
and HTTP fetching remain the selected Android handler's responsibility.

Android uses only an explicit `Intent.ACTION_VIEW` object with validated URI and
`CATEGORY_BROWSABLE`. It adds no grant/new-task flags, parses no intent strings,
and executes no shell. The tracked Activity must be resumed, focused, actually
visible, interactive and unlocked immediately before launch. FoldActivity's
hidden content view consequently prevents launches from its hidden display.

`{"accepted":true}` means Android's `startActivity` returned successfully; it
does not prove page loading, successful login, or user navigation. Refusals are
`{"accepted":false,"error":"not_visible"}` (or another fixed error code).
The helper returns zero only for a valid positive acknowledgement. URLs are
never logged, including URLs containing authorization codes in their query.

Request reading and UI dispatch each have a two-second deadline, and the Python
transaction has a five-second total deadline. A queued UI action is removed and
its future cancelled on timeout/teardown. A timeout that races a launch already
committed cannot undo Android's action; the helper reports failure and never
retries automatically. Listener shutdown precedes close to interrupt accept;
accepted sockets and reader threads are also closed/interrupted during teardown.

Host tests: `python -B -m unittest tools.browser.test_foldgpt_open -v`; abstract
socket/peer credential checks require Linux. `FoldWebUriTest` is pure JVM JUnit.
These tests do not establish Android lifecycle behavior or browser launching;
that requires device validation.

On 2026-09-06, the installed Android 17 debug build opened `https://example.com/`
from the real guest adapter. Android selected Chrome and its visible page showed
Example Domain. A second request while FoldGPT was behind Chrome failed with
`not_visible`, and the ambiguous numeric host `https://127.1/` failed with
`invalid_url`. The APK installed on the phone matched the locally built hash.
The official client's internal browser separately displayed Example Domain;
that manual navigation does not establish browser automation by a Codex task.
