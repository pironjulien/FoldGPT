# Focus bridge checks

Run from the repository root:

```powershell
python -m unittest discover -s tests -p 'test_foldgpt_ime.py' -v
node tests/keyboard-focus.test.cjs
```

The Python checks require `websockets` and use an in-memory CDP transport. The
DOM checks require Node.js, Playwright and its bundled Chromium. They launch a
temporary headless browser, block network requests and use an inline fixture.
They do not use a personal browser profile, contact ChatGPT, run paid tasks or
control the phone.

The checks cover deliberate touch/re-tap signals, same-process frame handover,
open shadow DOM, CDP response matching, navigation context cleanup and concurrent
intent ordering. A Send-button regression verifies that the application's later
programmatic prompt focus cannot reopen the keyboard, while a new deliberate tap
can. Initialization, reconnection, window focus and visibility resume never open
the keyboard. Disposal and replacement leave one listener with increasing
sequence IDs. The hook transmits only boolean visibility, a fixed reason and a
sequence number.

Hook V5 supports `globalThis.__foldgptImeHook.dispose()` for live replacement.
V4 lacked removable listener handles and requires one document reload when
upgrading; replacing its global guard alone cannot remove its old listeners.

They do **not** establish that Android actually showed its keyboard, that Samsung
composition/autocorrect works, or that all official client windows are supported.
Cross-origin frames running in a separate renderer require CDP target attachment;
closed shadow roots cannot be inspected by this DOM hook. These remain device and
integration coverage limits, not claims of universal support.
